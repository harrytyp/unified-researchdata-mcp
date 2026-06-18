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

app = FastAPI()

class URLPrefixFixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code in (307, 308, 301, 302):
            location = response.headers.get("location", "")
            if location and not location.startswith("/"):
                parsed = __import__("urllib.parse").urlparse(location)
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

@app.api_route("/register", methods=["GET", "POST"])
async def register_route(request: Request):
    if request.method == "POST":
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        base_url = str(form.get("base_url", "https://datatagger.ub.tum.de")).strip()
        if not api_key:
            return HTMLResponse(REG_CSS + "<div class=card><h2>Error</h2><p>API Key is required</p></div>", status_code=400)
        try:
            token = encode_token(base_url, api_key)
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
        result = [{"name": t.name, "description": t.description or "",
                    "inputSchema": t.inputSchema or {"type": "object", "properties": {}}}
                  for t in tools]
        return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": result}})
    elif method == "tools/call":
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
