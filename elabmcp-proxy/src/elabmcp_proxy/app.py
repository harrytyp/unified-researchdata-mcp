"""FastAPI app: registration UI + per-session SSE↔stdio MCP bridge."""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import HTMLResponse, StreamingResponse

from .session import RProcessHandle, SESSION_TIMEOUT

logger = logging.getLogger("elabmcp-proxy.app")

token_store: dict[str, RProcessHandle] = {}


def _create_register_form(error: str = "") -> str:
    err_html = f'<p style="color:red">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>elabFTW MCP Registration</title>
<style>
body {{ font-family: sans-serif; padding: 20px; max-width: 600px; margin: 40px auto; }}
label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
input[type=text], input[type=password] {{ width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; margin-bottom: 15px; }}
button {{ background: #3498db; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; font-size: 1em; width: 100%; }}
</style></head><body>
<div style="border:1px solid #ddd;border-radius:8px;padding:20px;box-shadow:0 2px 10px rgba(0,0,0,0.1)">
<h2 style="color:#2c3e50;">elabFTW MCP Registration</h2>
<p style="color:#666;">Enter your elabFTW credentials to generate a personal MCP session URL.</p>
{err_html}
<form method="post">
<label>elabFTW Base URL:</label>
<input type="text" name="base_url" value="https://eln.example.org" required>
<label>elabFTW API Key:</label>
<input type="password" name="api_key" placeholder="Paste your elabFTW API key" required>
<button type="submit">Generate MCP URL</button>
</form>
</div></body></html>"""


def _registration_success_page(personal_url: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Registration Successful</title>
<style>
body {{ font-family: sans-serif; padding: 20px; max-width: 600px; margin: 40px auto; }}
</style></head><body>
<div style="border:1px solid #ddd;border-radius:8px;padding:20px;box-shadow:0 2px 10px rgba(0,0,0,0.1)">
<h2 style="color:#2c3e50;">Registration Successful</h2>
<p>Use the following URL in your MCP client (Claude Desktop, KISSKI, etc.):</p>
<div style="background:#f8f9fa;padding:15px;border-radius:4px;word-break:break-all;font-family:monospace;border:1px solid #eee;margin:10px 0;">
{personal_url}
</div>
<p style="color:#666;font-size:0.9em;margin-top:20px;">
Session expires after 30 minutes of inactivity.
</p>
<a href="/register" style="color:#3498db;">&larr; Register another key</a>
</div></body></html>"""


async def register_page(request: Request):
    if request.method == "POST":
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        base_url = str(form.get("base_url", "")).strip()
        if not api_key or not base_url:
            return HTMLResponse(_create_register_form("API Key and Base URL are required."), status_code=400)
        token = str(uuid.uuid4())
        token_store[token] = RProcessHandle(token, base_url, api_key)
        forwarded_proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host", "localhost:8081")
        personal_url = f"{forwarded_proto}://{host}/mcp?token={token}"
        logger.info("Registered new session token=%s", token[:8])
        return HTMLResponse(_registration_success_page(personal_url))
    return HTMLResponse(_create_register_form())


async def sse_stream(request: Request):
    token = request.query_params.get("token", "")
    handle = token_store.get(token)
    if handle is None:
        return HTMLResponse("Invalid or expired token.", status_code=401)
    handle.touch()
    await handle.ensure_running()

    # Build the messages endpoint URL (same path, POST)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    messages_url = f"{scheme}://{host}/mcp?token={token}"

    q = await handle.subscribe()

    async def event_generator():
        try:
            # 1. Send endpoint event so the client knows where to POST
            yield f"event: endpoint\ndata: {messages_url}\n\n"
            # 2. Forward R subprocess stdout lines as SSE message events
            while True:
                line = await q.get()
                text = line.decode(errors="replace").rstrip()
                if text:
                    yield f"event: message\ndata: {text}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            handle.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def mcp_messages(request: Request):
    """POST endpoint — forwards client JSON-RPC message to the R subprocess."""
    token = request.query_params.get("token", "")
    handle = token_store.get(token)
    if handle is None:
        return HTMLResponse("Invalid or expired token.", status_code=401)
    if not handle.is_alive:
        return HTMLResponse("Session expired, please re-register.", status_code=410)
    body = await request.body()
    await handle.write_stdin(body + b"\n")
    return HTMLResponse("ok", status_code=200)


async def cleanup_expired_sessions():
    while True:
        try:
            now = time.time()
            expired = [t for t, h in token_store.items() if h.expired]
            for t in expired:
                logger.info("Cleaning up expired session token=%s", t[:8])
                await token_store[t].shutdown()
                del token_store[t]
        except Exception:
            logger.exception("Session cleanup error")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_expired_sessions())
    yield
    task.cancel()
    for token, handle in list(token_store.items()):
        await handle.shutdown()
    token_store.clear()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.api_route("/register", methods=["GET", "POST"])
    async def register_route(request: Request):
        return await register_page(request)

    @app.get("/mcp")
    async def mcp_sse(request: Request):
        return await sse_stream(request)

    @app.post("/mcp")
    async def mcp_post(request: Request):
        return await mcp_messages(request)

    return app
