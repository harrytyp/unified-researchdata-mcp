"""DataTagger MCP Proxy — FastAPI app with registration, auth, and MCP routing."""

import os
import json
from contextvars import ContextVar
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from datatagger_mcp.api import mcp as mcp_server
from .jwt_token import encode_token, decode_token

session_key_var: ContextVar[Optional[str]] = ContextVar("session_key", default=None)
session_base_url_var: ContextVar[Optional[str]] = ContextVar("session_base_url", default=None)
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

class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if "/mcp" in request.url.path:
            token = request.query_params.get("token", "")
            if not token:
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    token = auth[7:]
            if token:
                try:
                    payload = decode_token(token)
                    session_key_var.set(payload["k"])
                    session_base_url_var.set(payload["u"])
                    session_enabled_tools_var.set(payload.get("t"))
                except Exception:
                    return JSONResponse(
                        {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Invalid token"}},
                        status_code=401,
                    )
        return await call_next(request)

app.add_middleware(TokenAuthMiddleware)

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
</style>"""

def _dt_profile_form(base_url, api_key):
    css = REG_CSS
    read_tools = [("search_datatagger","Search"),("list_projects","List projects"),("get_project","Get project"),("list_folders","List folders"),("get_folder","Get folder"),("list_datasets","List datasets"),("download_fdm_file","Download file")]
    write_tools = [("create_project","Create project"),("update_project","Update project"),("delete_project","Delete project"),("create_folder","Create folder"),("update_folder","Update folder"),("delete_folder","Delete folder"),("create_dataset","Create dataset"),("delete_dataset","Delete dataset"),("publish_dataset","Publish dataset"),("restore_dataset_version","Restore version"),("compare_dataset_versions","Compare versions"),("upload_dataset_file","Upload file"),("add_metadata_to_dataset","Add metadata")]
    th = ""
    for name, label in read_tools:
        th += '<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem"><input type="checkbox" name="tools" value="' + name + '" data-cat="read" checked style="accent-color:#3b82f6"><span style="color:#e8edf5">' + label + '</span></label>'
    for name, label in write_tools:
        th += '<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem"><input type="checkbox" name="tools" value="' + name + '" data-cat="write" checked style="accent-color:#3b82f6"><span style="color:#e8edf5">' + label + '</span></label>'
    return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>DataTagger MCP Registration</title>' + css + '</head><body><div class="card"><h2>DataTagger MCP Registration</h2><p class="sub">Key validated. Choose your tools:</p><form method="post"><input type="hidden" name="base_url" value="' + base_url + '"><input type="hidden" name="api_key" value="' + api_key + '"><input type="hidden" name="validated" value="1"><div style="margin-bottom:20px"><h3 style="font-size:0.95rem;font-weight:600;margin:0 0 12px;color:#e8edf5">Profile Presets</h3><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px"><label style="display:flex;flex-direction:column;align-items:center;padding:16px;background:#1a2236;border:1.5px solid #1f2b40;border-radius:10px;cursor:pointer"><input type="radio" name="profile" value="r" data-preset="r" style="display:none"><span style="font-size:0.82rem;font-weight:600;color:#e8edf5;margin-bottom:4px">Read-only</span><span style="font-size:0.72rem;color:#5c6f8c;text-align:center">Browse and search</span></label><label style="display:flex;flex-direction:column;align-items:center;padding:16px;background:#1a2236;border:1.5px solid #1f2b40;border-radius:10px;cursor:pointer"><input type="radio" name="profile" value="h" data-preset="h" checked style="display:none"><span style="font-size:0.82rem;font-weight:600;color:#e8edf5;margin-bottom:4px">Hybrid</span><span style="font-size:0.72rem;color:#5c6f8c;text-align:center">Read + metadata</span></label><label style="display:flex;flex-direction:column;align-items:center;padding:16px;background:#1a2236;border:1.5px solid #1f2b40;border-radius:10px;cursor:pointer"><input type="radio" name="profile" value="f" data-preset="f" style="display:none"><span style="font-size:0.82rem;font-weight:600;color:#e8edf5;margin-bottom:4px">Full</span><span style="font-size:0.72rem;color:#5c6f8c;text-align:center">All tools enabled</span></label></div></div><div style="margin-bottom:20px"><h3 style="font-size:0.95rem;font-weight:600;margin:0 0 12px;color:#e8edf5">Select Tools</h3><div style="margin-bottom:12px"><label style="display:flex;align-items:center;gap:6px;padding:8px 12px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.82rem;font-weight:600"><input type="checkbox" name="tools" value="all" checked style="accent-color:#3b82f6" onchange="toggleAllTools(this)"><span style="color:#e8edf5">All Tools</span></label></div><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:6px">' + th + '</div></div><button type="submit">Generate MCP URL</button></form></div><script>function toggleAllTools(cb){document.querySelectorAll("input[name=tools]").forEach(function(t){if(t.value!=="all")t.checked=cb.checked})}function applyPreset(p){var r=document.querySelectorAll("input[name=tools][data-cat=read]"),w=document.querySelectorAll("input[name=tools][data-cat=write]"),a=document.querySelector("input[name=tools][value=all]");if(p==="r"){r.forEach(function(t){t.checked=!0});w.forEach(function(t){t.checked=!1})}else if(p==="h"){r.forEach(function(t){t.checked=!0});w.forEach(function(t){t.checked=!1})}else if(p==="f"){r.forEach(function(t){t.checked=!0});w.forEach(function(t){t.checked=!0})}var all=document.querySelectorAll("input[name=tools]:not([value=all])");var c=Array.from(all).every(function(t){return t.checked});if(a)a.checked=c}document.querySelectorAll("input[name=profile][data-preset]").forEach(function(r){r.addEventListener("change",function(){applyPreset(this.value)})});document.addEventListener("DOMContentLoaded",function(){applyPreset("h")});</script></body></html>'

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
        personal = f"{forwarded}://{host}{prefix}/mcp/?token={token}"
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
Read (7)
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
<input type="checkbox" name="tools" value="download_fdm_file" checked class="cat_read_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Download file</span>
</label>
</div>
</div>
<div style="margin-bottom:16px">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
<label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;font-weight:600;color:#8898b4;text-transform:uppercase;letter-spacing:0.05em">
<input type="checkbox" id="cat_write_toggle" checked style="accent-color:#3b82f6" onchange="toggleCategory('cat_write', this)">
Write (15)
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
<input type="checkbox" name="tools" value="update_project" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Update project</span>
</label>
<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a2236;border:1px solid #1f2b40;border-radius:6px;cursor:pointer;font-size:0.75rem">
<input type="checkbox" name="tools" value="update_folder" checked class="cat_write_item" style="accent-color:#3b82f6">
<span style="color:#e8edf5">Update folder</span>
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

@app.api_route("/mcp", methods=["GET", "POST"])
async def mcp_handler(request: Request):
    if request.method == "GET":
        return Response(status_code=204)
    body = await request.json()
    msg_id = body.get("id", 1)
    method = body.get("method", "")
    params = body.get("params", {})
    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "datatagger-mcp", "version": "0.1.0"},
        }})
    elif method == "notifications/initialized":
        return JSONResponse(None, status_code=202)
    elif method == "tools/list":
        tools = await mcp_server.list_tools()
        enabled = session_enabled_tools_var.get()
        result = [{"name": t.name, "description": t.description or "",
                    "inputSchema": t.inputSchema or {"type": "object", "properties": {}}}
                  for t in tools
                  if enabled is None or t.name in enabled]
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": result}})
    elif method == "tools/call":
        enabled = session_enabled_tools_var.get()
        if enabled is not None and params["name"] not in enabled:
            tool_name = params["name"]
            return JSONResponse({"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": "Tool " + repr(tool_name) + " is not enabled for this token"}})
        try:
            raw = await mcp_server.call_tool(params["name"], params.get("arguments", {}))
        except Exception as e:
            return JSONResponse({"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32603, "message": str(e)}})
        content = []
        for c in raw:
            if hasattr(c, "text"):
                content.append({"type": "text", "text": c.text})
            else:
                content.append({"type": "text", "text": str(c)})
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {"content": content}})
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}})
