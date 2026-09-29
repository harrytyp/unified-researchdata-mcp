"""DataTagger MCP Proxy — FastAPI app with registration, auth, and MCP routing."""

import os
import json
import urllib.parse
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.shared.exceptions import MCPError

from datatagger_mcp.api import mcp as mcp_server
# The datatagger_mcp LIBRARY resolves auth from ITS OWN context vars
# (datatagger_mcp.api.session_key_var / session_base_url_var), falling
# back to env FDM_TOKEN. MCPTokenMiddleware sets them per request; it is a
# pure ASGI middleware so the values survive into the MCP handler
# (BaseHTTPMiddleware runs call_next in a separate task and loses them).
from datatagger_mcp.api import (
    session_key_var as _lib_session_key_var,
    session_base_url_var as _lib_session_base_url_var,
    transport_security_settings,
)
from .jwt_token import encode_token, decode_token

session_enabled_tools_var: ContextVar[Optional[list]] = ContextVar("session_enabled_tools", default=None)

app = FastAPI()

class URLPrefixFixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code in (307, 308, 301, 302):
            location = response.headers.get("location", "")
            if location and not location.startswith("/"):
                parsed = __import__("urllib.parse").parse.urlparse(location)
                forwarded = request.headers.get("x-forwarded-proto", "")
                if forwarded and parsed.scheme != forwarded:
                    loc = parsed._replace(scheme=forwarded).geturl()
                    response.headers["location"] = loc
        return response

app.add_middleware(URLPrefixFixMiddleware)

class MCPTokenMiddleware:
    """Per-request authentication for the MCP endpoint.

    The token arrives as ``?token=…`` (the registered personal URL) or as an
    ``Authorization: Bearer …`` header. An unreadable/expired token is refused
    with HTTP 401 before the MCP layer sees the request; a valid one is turned
    into the library's context vars (API key + base URL) plus the token's tool
    scope, which ``ToolScopeMiddleware`` enforces inside the server.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        token = _extract_token(scope)
        payload = decode_token(token) if token else None
        if token and not payload:
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32001, "message": "Invalid or expired token"},
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return

        if payload:
            _lib_session_key_var.set(payload["k"])
            _lib_session_base_url_var.set(payload["u"])
            session_enabled_tools_var.set(payload.get("t"))

        await self.app(scope, receive, send)


def _extract_token(scope: Scope) -> str:
    """Read the token from the query string (?token=…) or the Authorization header."""
    query = scope.get("query_string", b"")
    if isinstance(query, bytes):
        query = query.decode("latin-1")
    for part in query.split("&"):
        if part.startswith("token="):
            return urllib.parse.unquote_plus(part[len("token="):])
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            raw = value.decode("latin-1")
            if raw.lower().startswith("bearer "):
                return raw[len("bearer "):].strip()
    return ""


app.add_middleware(MCPTokenMiddleware)


class ToolScopeMiddleware:
    """Restrict the served tool set to the scope of the request's token.

    Runs inside the MCP server (SDK v2 middleware chain), so it applies to both
    protocol eras: tools outside a token's scope disappear from ``tools/list``
    and are refused on ``tools/call``.
    """

    async def __call__(self, ctx, call_next):
        enabled = session_enabled_tools_var.get()
        if enabled is None:
            return await call_next(ctx)

        method = getattr(ctx, "method", "")
        params = getattr(ctx, "params", None) or {}
        if method == "tools/call" and params.get("name") not in enabled:
            raise MCPError(
                code=-32601,
                message=f"Tool {params.get('name')!r} is not enabled for this token",
            )

        result = await call_next(ctx)
        if method == "tools/list" and result is not None:
            tools = getattr(result, "tools", None)
            if tools is not None:  # pydantic result object
                result.tools = [t for t in tools if t.name in enabled]
            elif isinstance(result, dict) and isinstance(result.get("tools"), list):
                result["tools"] = [
                    t for t in result["tools"]
                    if (t.get("name") if isinstance(t, dict) else t.name) in enabled
                ]
        return result


mcp_server.middleware.append(ToolScopeMiddleware())

REG_CSS = """<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0b0f1a;color:#e8edf5;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#131827;border:1px solid #1f2b40;border-radius:14px;padding:2rem;max-width:480px;width:100%}
h2{font-size:1.15rem;font-weight:700;margin-bottom:0.3rem}
p{font-size:0.85rem;color:#8898b4;margin-bottom:1.25rem;line-height:1.5}
label{display:block;font-size:0.82rem;font-weight:600;margin-bottom:0.3rem;color:#8898b4}
input{width:100%;padding:0.6rem 0.75rem;background:#1a2236;border:1px solid #1f2b40;border-radius:8px;color:#e8edf5;font-size:0.9rem;outline:none;box-sizing:border-box;margin-bottom:0.85rem}
input:focus{border-color:#3b82f6}
button{width:100%;padding:0.6rem;background:#3b82f6;color:#fff;border:none;border-radius:8px;font-size:0.9rem;font-weight:600;cursor:pointer}
button:hover{opacity:0.9}
.url-box{background:#1a2236;border:1px solid #1f2b40;border-radius:8px;padding:0.85rem;font-family:monospace;font-size:0.78rem;word-break:break-all;margin:0.85rem 0;color:#e8edf5}
.note{font-size:0.78rem;color:#5c6f8c;margin-top:1rem}
a{color:#3b82f6;text-decoration:none;font-size:0.82rem}
a:hover{text-decoration:underline}
.tool-section{border:1px solid #1f2b40;border-radius:8px;margin-bottom:10px;overflow:hidden}
.tool-section-header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#1a2236;cursor:pointer;user-select:none;transition:background 0.15s}
.tool-section-header:hover{background:rgba(26,34,54,0.8)}
.tool-row{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:4px;transition:background 0.1s}
.tool-row:hover{background:#1a2236}
.tool-row label{display:flex;align-items:center;gap:8px;flex:1;cursor:pointer;min-height:28px}
.tool-info{background:none;border:1px solid #2a3f60;color:#5c6f8c;cursor:help;font-size:0.65rem;padding:1px 5px;border-radius:50%;opacity:0.6;transition:all 0.15s;width:18px;height:18px;line-height:16px;text-align:center;font-style:italic;font-family:serif}
.tool-info:hover{opacity:1;background:#1a2236;color:#8898b4}
.tool-desc{display:none;padding:6px 10px 6px 12px;font-size:0.72rem;color:#5c6f8c;line-height:1.4;background:rgba(26,34,54,0.3);border-radius:0 0 4px 4px}
.tool-row.expanded .tool-desc{display:block}
.cat-arrow{font-size:0.85rem;font-weight:700;color:#5c6f8c;transition:all 0.2s;display:inline-block;width:18px;text-align:center}
.tool-section.open .cat-arrow{content:"\2212"}
.tool-section-body{max-height:0;overflow:hidden;transition:max-height 0.3s ease}
.tool-section.open .tool-section-body{max-height:2000px}
.preset-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:24px}
.preset-card{flex:1;display:flex;flex-direction:column;padding:14px;background:#1a2236;border:1.5px solid #1f2b40;border-radius:8px;cursor:pointer;transition:all 0.15s ease;position:relative}
.preset-card:hover{border-color:#2a3f60;transform:translateY(-1px)}
.preset-card input{position:absolute;opacity:0;width:0;height:0}
.preset-card:has(input:checked){border-color:#3b82f6;background:rgba(59,130,246,0.06)}
.preset-radio{display:inline-block;width:18px;height:18px;border:2px solid #2a3f60;border-radius:50%;position:relative;flex-shrink:0}
.preset-card:has(input:checked) .preset-radio{border-color:#3b82f6}
.preset-radio::after{content:"";position:absolute;inset:3px;border-radius:50%;background:#3b82f6;transform:scale(0);transition:transform 0.15s ease}
.preset-card:has(input:checked) .preset-radio::after{transform:scale(1)}
.preset-card-text{margin-top:8px}
.preset-name{font-size:0.82rem;font-weight:600;color:#e8edf5;display:block}

.toggle-wrapper{display:flex;align-items:center;flex:1}
.toggle-label{display:flex;align-items:center;justify-content:space-between;width:100%;gap:12px;cursor:pointer;min-height:36px}
.toggle-text{font-size:0.78rem;color:#e8edf5;flex:1}
.toggle-switch{position:relative;width:44px;height:24px;flex-shrink:0}
.toggle-switch input{position:absolute;opacity:0;width:0;height:0}
.toggle-slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#2a3f60;border-radius:24px;transition:all 0.2s ease}
.toggle-slider::before{content:"";position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#8898b4;border-radius:50%;transition:all 0.2s ease}
.toggle-switch input:checked + .toggle-slider{background:#3b82f6}
.toggle-switch input:checked + .toggle-slider::before{transform:translateX(20px);background:#fff}
.preset-badge{font-size:0.7rem;color:#5c6f8c}</style>"""

def _dt_profile_form(base_url, api_key):
    css = REG_CSS
    # Tool definitions with proper descriptions
    read_tools = [
        ("search_datatagger","Search","Full-text search across projects, folders, and datasets"),
        ("list_projects","List projects","Browse all DataTagger projects with pagination"),
        ("get_project","Get project","View a single project and its metadata"),
        ("list_folders","List folders","Browse folders within a project"),
        ("get_folder","Get folder","View a single folder and its contents"),
        ("list_datasets","List datasets","Browse datasets within a folder with filtering"),
        ("download_version_file","Download file","Download a dataset file to your local machine"),
        ("get_folder_permissions","Folder permissions","List the users who may access a folder"),
        ("list_metadata","List metadata","Browse the available metadata template mappings"),
    ]
    write_tools = [
        ("create_project","Create project","Create a new top-level project"),
        ("update_project","Update project","Modify an existing project's name or description"),
        ("delete_project","Delete project","Permanently remove a project and all its contents"),
        ("create_folder","Create folder","Create a new folder inside a project"),
        ("update_folder","Update folder","Rename or update a folder"),
        ("delete_folder","Delete folder","Remove a folder and its datasets"),
        ("create_dataset","Create dataset","Create a new dataset entry inside a folder"),
        ("delete_dataset","Delete dataset","Permanently remove a dataset"),
        ("publish_dataset","Publish dataset","Finalize/commit a dataset (lock for editing)"),
        ("restore_dataset_version","Restore version","Roll back a dataset to a previous historical version"),
        ("compare_dataset_versions","Compare versions","View a diff between two dataset versions"),
        ("upload_dataset_file","Upload file","Upload a raw file from your computer to a dataset"),
        ("add_metadata_to_dataset","Add metadata","Attach structured metadata tags to a dataset"),
        ("set_folder_permissions","Set permissions","Grant or revoke folder access for other users"),
    ]

    # Build tool HTML with toggle switches and descriptions
    tools_html = '<div style="margin:20px 0"><h3 style="font-size:0.85rem;font-weight:600;color:#8898b4;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">Tools</h3>'
    
    for cat_id, cat_name, cat_tools in [("read","Read",read_tools),("write","Write",write_tools)]:
        tools_html += '<div class="tool-section"><div class="tool-section-header" onclick="toggleSection(\'' + cat_id + '\')"><label style="display:flex;align-items:center;gap:6px;font-size:0.78rem;font-weight:600;color:#8898b4;text-transform:uppercase;letter-spacing:0.05em;cursor:pointer"><div class="toggle-switch" style="width:44px;height:24px"><input type="checkbox" id="' + cat_id + '_toggle" checked onchange="event.stopPropagation();toggleCategoryCheckbox(\'' + cat_id + '\',this)" style="position:absolute;opacity:0;width:0;height:0"><span class="toggle-slider"></span></div>' + cat_name + ' <span style="color:#5c6f8c;font-weight:400">(' + str(len(cat_tools)) + ')</span></label><span class="cat-arrow" id="' + cat_id + '_arrow">+</span></div><div class="tool-section-body" id="' + cat_id + '">'
        for t_name, t_label, t_desc in cat_tools:
            # Toggle switch HTML
            tools_html += '<div class="tool-row" onclick="if(!event.target.closest(''.toggle-switch''))this.classList.toggle(''expanded'')"><div class="toggle-wrapper"><label class="toggle-label"><span class="toggle-text">' + t_label + '</span><div class="toggle-switch"><input type="checkbox" name="tools" value="' + t_name + '" class="' + cat_id + '_item" checked><span class="toggle-slider"></span></div></label></div></div>'
        tools_html += '</div></div>'
    tools_html += '</div>'

    js = "<script>function toggleSection(id){var parent=document.getElementById(id).parentElement;var arr=document.getElementById(id+'_arrow');var open=parent.classList.toggle('open');arr.textContent=open?'−':'+'}function toggleCategoryCheckbox(cid,cb){var items=document.querySelectorAll('.'+cid+'_item');items.forEach(function(t){t.checked=cb.checked});updateAllToggle()}function updateAllToggle(){['read','write'].forEach(function(id){var ct=document.getElementById(id+'_toggle');if(ct){var its=document.querySelectorAll('.'+id+'_item');ct.checked=Array.from(its).every(function(t){return t.checked})}})}function applyPreset(p){var r=document.querySelectorAll('.read_item'),w=document.querySelectorAll('.write_item');if(p==='r'){r.forEach(function(t){t.checked=true});w.forEach(function(t){t.checked=false})}else if(p==='h'){r.forEach(function(t){t.checked=true});w.forEach(function(t){var n=t.value;t.checked=(n==='publish_dataset'||n==='add_metadata_to_dataset'||n==='restore_dataset_version'||n==='compare_dataset_versions')})}else if(p==='f'){r.forEach(function(t){t.checked=true});w.forEach(function(t){t.checked=true})}updateAllToggle()}document.querySelectorAll('input[name=profile][data-preset]').forEach(function(r){r.addEventListener('change',function(){applyPreset(this.value)})});document.querySelectorAll('.toggle-switch input').forEach(function(cb){cb.addEventListener('change',function(){var cl=Array.from(this.classList).find(function(c){return c.endsWith('_item')});if(cl){var id=cl.replace('_item','');var ct=document.getElementById(id+'_toggle');var its=document.querySelectorAll('.'+cl);ct.checked=Array.from(its).every(function(t){return t.checked})}})});document.addEventListener('DOMContentLoaded',function(){applyPreset('h')});</script>"

    return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>DataTagger MCP Registration</title>' + css + '</head><body><div class="card"><h2>DataTagger MCP Registration</h2><p class="sub">Key validated. <span style="display:inline-block;padding:3px 10px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.2);border-radius:6px;font-size:0.78rem;font-weight:700;color:#3b82f6;text-transform:uppercase;letter-spacing:0.03em">write key</span><br>Choose your tools:</p><form method="post"><input type="hidden" name="base_url" value="' + base_url + '"><input type="hidden" name="api_key" value="' + api_key + '"><input type="hidden" name="validated" value="1"><div style="margin-bottom:20px"><h3 style="font-size:0.85rem;font-weight:600;color:#8898b4;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">Profile Preset</h3><div class="preset-grid"><label class="preset-card"><input type="radio" name="profile" value="r" data-preset="r" style="display:none"><span class="preset-radio"></span><span class="preset-card-text"><span class="preset-name">Read-only</span><span class="preset-badge">Browse &amp; search only</span></span></label><label class="preset-card"><input type="radio" name="profile" value="h" data-preset="h" checked style="display:none"><span class="preset-radio"></span><span class="preset-card-text"><span class="preset-name">Hybrid</span><span class="preset-badge">Read + publish, metadata</span></span></label><label class="preset-card"><input type="radio" name="profile" value="f" data-preset="f" style="display:none"><span class="preset-radio"></span><span class="preset-card-text"><span class="preset-name">Full</span><span class="preset-badge">All tools enabled</span></span></label></div></div>' + tools_html + '<button type="submit">Generate MCP URL</button></form></div>' + js + '</body></html>'

@app.api_route("/register", methods=["GET", "POST"])
async def register_route(request: Request):
    if request.method == "GET":
        prefix = os.environ.get("URL_PREFIX", "/dt").rstrip("/") or "/dt"
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>DataTagger MCP Registration</title>{REG_CSS}</head><body>
<div class="card">
<h2>DataTagger MCP Registration</h2>
<p>Enter your DataTagger API key to generate a permanent MCP session URL.</p>
<form method="post">
<label>DataTagger Base URL</label>
<input type="text" name="base_url" value="https://datatagger.ub.tum.de" required>
<label>DataTagger API Token</label>
<input type="password" name="api_key" placeholder="Paste your DataTagger API token" required>
<button type="submit">Validate Key</button>
</form>
</div></body></html>""")
    if request.method == "POST":
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        base_url = str(form.get("base_url", "https://datatagger.ub.tum.de")).strip()
        validated = str(form.get("validated", "")).strip()
        if not api_key:
            return HTMLResponse(REG_CSS + "<div class=card><h2>Error</h2><p>API Key is required</p></div>", status_code=400)
        if validated != "1":
            # Step 1: validate key, then show profile form
            try:
                import httpx
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.get(
                        f"{base_url.rstrip('/')}/api/v1/project/?limit=1",
                        headers={"Authorization": f"Bearer {api_key}"}
                    )
                    if resp.status_code == 401:
                        return HTMLResponse(REG_CSS + "<div class=card><h2>Invalid Key</h2><p>Token rejected by DataTagger API (HTTP 401). Check your token.</p></div>", status_code=401)
                    if resp.status_code == 403:
                        return HTMLResponse(REG_CSS + "<div class=card><h2>Access Denied</h2><p>Token valid but access denied (HTTP 403). Check permissions.</p></div>", status_code=403)
                    if resp.status_code != 200:
                        return HTMLResponse(REG_CSS + f"<div class=card><h2>Validation Failed</h2><p>DataTagger API returned HTTP {resp.status_code}.</p></div>", status_code=400)
            except httpx.ConnectError:
                return HTMLResponse(REG_CSS + "<div class=card><h2>Connection Error</h2><p>Could not connect to DataTagger API. Check the base URL.</p></div>", status_code=400)
            except Exception as e:
                return HTMLResponse(REG_CSS + f"<div class=card><h2>Error</h2><p>Validation failed: {e}</p></div>", status_code=500)
            # Show profile form after validation
            prefix = os.environ.get("URL_PREFIX", "/dt").rstrip("/") or "/dt"
            return HTMLResponse(_dt_profile_form(base_url, api_key))
        try:
            # Step 2: already validated, generate token
            selected_tools = form.getlist("tools")
            enabled_tools = selected_tools if selected_tools and "all" not in selected_tools else None
            token = encode_token(base_url, api_key, enabled_tools=enabled_tools)
        except RuntimeError as e:
            return HTMLResponse(REG_CSS + f"<div class=card><h2>Error</h2><p>{e}</p></div>", status_code=500)
        forwarded = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host", "localhost:8000")
        prefix = os.environ.get("URL_PREFIX", "/dt").rstrip("/") or "/dt"
        personal = f"{forwarded}://{host}{prefix}/mcp?token={token}"
        register = f"{prefix}/register"
        buttons = '''<div style="display:flex;gap:10px;margin-top:18px;flex-direction:column">
  <div style="display:flex;gap:10px">
    <button onclick="(function(e){var b=document.querySelector('.url-box');if(!b||!b.textContent)return;var u=b.textContent.trim();var t=u.split('token=')[1];if(!t)return;t=t.split(/[\s<&]/)[0];navigator.clipboard.writeText(t).then(function(){var btn=e.currentTarget||e;btn.innerHTML='\u2713 Copied';btn.style.borderColor='#22c55e';setTimeout(function(){btn.innerHTML='\U0001f4cb Copy Token';btn.style.borderColor=''},2500)}).catch(function(){prompt('Token:',t)})})(this)" type="button" title="Copy only the JWT token (without URL)" style="flex:1;padding:11px 16px;background:#1a2236;color:#e8edf5;border:1.5px solid #2a3f60;border-radius:10px;font-size:0.82rem;font-weight:600;cursor:copy;font-family:inherit;display:flex;align-items:center;gap:8px;justify-content:center;transition:all 0.15s ease;min-height:44px" onmousedown="this.style.transform='scale(0.97)'" onmouseup="this.style.transform=''" onmouseleave="this.style.transform=''">\U0001f4cb Copy Token</button>
    <button onclick="(function(e){var b=document.querySelector('.url-box');if(!b||!b.textContent)return;var u=b.textContent.trim();navigator.clipboard.writeText(u).then(function(){var btn=e.currentTarget||e;btn.innerHTML='\u2713 Copied';btn.style.background='#22c55e';setTimeout(function(){btn.innerHTML='\U0001f4c2 Copy URL';btn.style.background=''},2500)}).catch(function(){prompt('URL:',u)})})(this)" type="button" title="Copy the full MCP URL with token" style="flex:1;padding:11px 16px;background:#3b82f6;color:#fff;border:none;border-radius:10px;font-size:0.82rem;font-weight:600;cursor:copy;font-family:inherit;display:flex;align-items:center;gap:8px;justify-content:center;transition:all 0.15s ease;min-height:44px" onmousedown="this.style.transform='scale(0.97)'" onmouseup="this.style.transform=''" onmouseleave="this.style.transform=''">\U0001f4c2 Copy URL</button>
  </div>
  <p style="font-size:0.7rem;color:#5c6f8c;margin:4px 0 0;text-align:center">Click to copy &mdash; token only or full URL</p>
</div>'''
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Registration Successful</title>{REG_CSS}</head><body>
<div class="card"><h2>Registration Successful</h2>
<p>Use the following URL in your MCP client:</p>
<p style="font-size:0.78rem;color:#8898b4;margin-bottom:12px">Key type: <span style="display:inline-block;padding:2px 8px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.2);border-radius:4px;font-size:0.72rem;font-weight:600;color:#3b82f6">write</span></p>
<div class="url-box">{personal}</div>
<p class="note">Token expires in 30 days.</p>
{buttons}
<a href="{register}">&larr; Register another key</a>
</div></body></html>""")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>DataTagger MCP Registration</title>{REG_CSS}</head><body>
<div class="card"><h2>DataTagger MCP Registration</h2>
<p>Enter your API token to generate a personal MCP URL.</p>
<form method="post">
<label>API Token</label>
<input type="password" name="api_key" placeholder="Paste your token here" required>
<label>Data Tagger Base URL</label>
<input type="text" name="base_url" value="https://datatagger.ub.tum.de">
<div style="margin:20px 0">
<h3 style="font-size:0.95rem;font-weight:600;margin:0 0 12px;color:#e8edf5">Select Tools</h3>
<p style="font-size:0.78rem;color:#8898b4;margin-bottom:16px">Choose which MCP tools to enable. Toggle entire categories or individual tools.</p>

<div style="margin-bottom:12px">
<label style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.82rem;font-weight:600">
<input type="checkbox" name="tools" value="all" checked style="accent-color:#3b82f6" onchange="toggleAllTools(this)">
<span style="color:#e8edf5">All Tools</span>
</label>
</div>
<div style="margin-bottom:16px">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
<label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;font-weight:600;color:#8898b4;text-transform:uppercase;letter-spacing:0.05em">
<input type="checkbox" id="cat_read_toggle" checked style="accent-color:#3b82f6" onchange="toggleCategory('cat_read', this)">
Read (9)
</label>
</div>
<div id="cat_read" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px">
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="search_datatagger" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Global search</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="list_projects" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">List projects</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="get_project" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Get project</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="list_folders" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">List folders</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="get_folder" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Get folder</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="list_datasets" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">List datasets</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="download_version_file" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Download file</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="get_folder_permissions" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Folder permissions</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="list_metadata" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">List metadata</span>
</label>
</div>
</div>
<div style="margin-bottom:16px">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
<label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;font-weight:600;color:#8898b4;text-transform:uppercase;letter-spacing:0.05em">
<input type="checkbox" id="cat_write_toggle" checked style="accent-color:#3b82f6" onchange="toggleCategory('cat_write', this)">
Write (14)
</label>
</div>
<div id="cat_write" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px">
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="create_project" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Create project</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="update_project" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Update project</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="delete_project" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Delete project</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="create_folder" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Create folder</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="update_folder" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Update folder</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="delete_folder" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Delete folder</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="create_dataset" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Create dataset</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="delete_dataset" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Delete dataset</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="publish_dataset" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Publish dataset</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="restore_dataset_version" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Restore version</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="compare_dataset_versions" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Compare versions</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="upload_dataset_file" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Upload file</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="add_metadata_to_dataset" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Add metadata</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="set_folder_permissions" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Set permissions</span>
</label>
</div>
</div>
<script>
function toggleAllTools(checkbox) {{
  var allCheckboxes = document.querySelectorAll('input[name="tools"]');
  allCheckboxes.forEach(function(cb) {{ cb.checked = checkbox.checked; }});
  var catToggles = document.querySelectorAll('[id$="_toggle"]');
  catToggles.forEach(function(ct) {{ ct.checked = checkbox.checked; }});
}}
function toggleCategory(catId, checkbox) {{
  var items = document.querySelectorAll('.' + catId + '_item');
  items.forEach(function(item) {{ item.checked = checkbox.checked; }});
  updateAllToolsCheckbox();
}}
function updateAllToolsCheckbox() {{
  var allCheckbox = document.querySelector('input[name="tools"][value="all"]');
  var allItems = document.querySelectorAll('input[name="tools"]:not([value="all"])');
  var allChecked = Array.from(allItems).every(function(cb) {{ return cb.checked; }});
  allCheckbox.checked = allChecked;
}}
document.addEventListener('DOMContentLoaded', function() {{
  var itemCheckboxes = document.querySelectorAll('input[name="tools"]:not([value="all"])');
  itemCheckboxes.forEach(function(cb) {{
    cb.addEventListener('change', function() {{
      var classes = this.className.split(' ');
      var catId = classes.find(function(c) {{ return c.endsWith('_item'); }});
      if (catId) {{
        catId = catId.replace('_item', '');
        var catCheckbox = document.getElementById(catId + '_toggle');
        var catItems = document.querySelectorAll('.' + catId + '_item');
        var allCatChecked = Array.from(catItems).every(function(item) {{ return item.checked; }});
        catCheckbox.checked = allCatChecked;
      }}
      updateAllToolsCheckbox();
    }});
  }});
}});
</script>
</div>
<script>
function toggleAllTools(checkbox) {{
  var tools = document.querySelectorAll('input[name="tools"]:not([value="all"])');
  tools.forEach(function(t) {{ t.checked = checkbox.checked; }});
}}
</script>
<button type="submit">Generate MCP URL</button>
</form>
</div></body></html>""")


# The MCP endpoint is served by the SDK's own Streamable-HTTP app: it speaks the
# 2026-07-28 revision (stateless — no Mcp-Session-Id, every request carries its
# own _meta, Mcp-Method/Mcp-Name headers) and keeps serving older clients that
# still open an initialize handshake. stateless_http=True is what makes any
# replica able to answer any request.
_mcp_http_app = mcp_server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    transport_security=transport_security_settings(),
    host="127.0.0.1",
)

@asynccontextmanager
async def _lifespan(_: FastAPI):
    # FastAPI does not run the lifespan of a mounted Starlette app, so the MCP
    # session manager is started here — without it the mounted app raises
    # "Task group is not initialized".
    async with mcp_server.session_manager.run():
        yield


app.router.lifespan_context = _lifespan

# Mounted last: the routes above (/register) win, everything else goes to MCP.
app.mount("/", _mcp_http_app)
