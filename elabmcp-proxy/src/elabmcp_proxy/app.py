"""FastAPI app: registration UI + per-session SSEÔåöstdio MCP bridge."""

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from .session import (
    RProcessHandle,
    SESSION_TIMEOUT,
    acquire_session_slot,
    get_running_count,
    release_session_slot,
)

logger = logging.getLogger("elabmcp-proxy.app")

# ÔöÇÔöÇ Rate limiting ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
limiter = Limiter(key_func=get_remote_address, default_limits=[])
token_store: dict[str, RProcessHandle] = {}

# ÔöÇÔöÇ Audit logging ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ
_audit_log_path = os.environ.get("ELABMCP_AUDIT_LOG", "/var/log/elabmcp-proxy/audit.log")
_audit_log_dir = os.path.dirname(_audit_log_path)
if _audit_log_dir and not os.path.exists(_audit_log_dir):
    try:
        os.makedirs(_audit_log_dir, exist_ok=True)
    except OSError:
        pass

_audit_logger = logging.getLogger("elabmcp-proxy.audit")
_audit_handler = logging.FileHandler(_audit_log_path, delay=True)
_audit_handler.setFormatter(logging.Formatter(
    "%(asctime)s\t%(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
))
_audit_logger.addHandler(_audit_handler)
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False


def _audit(event: str, **kwargs):
    parts = [event]
    for k, v in sorted(kwargs.items()):
        parts.append(f"{k}={v}")
    _audit_logger.info("\t".join(parts))


# ÔöÇÔöÇ HTML templates ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

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


# ÔöÇÔöÇ Routes ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

async def register_page(request: Request):
    if request.method == "POST":
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        base_url = str(form.get("base_url", "")).strip()
        remote_ip = request.client.host if request.client else "unknown"

        if not api_key or not base_url:
            return HTMLResponse(_create_register_form("API Key and Base URL are required."), status_code=400)

        # Check global session capacity before creating handle
        slot_ok = await acquire_session_slot()
        if not slot_ok:
            logger.warning(
                "Registration denied: at capacity (%d/%d) from %s",
                get_running_count(),
                int(os.environ.get("ELABMCP_MAX_SESSIONS", "20")),
                remote_ip,
            )
            return HTMLResponse(
                _create_register_form(
                    "Server is at maximum capacity. Please try again later."
                ),
                status_code=503,
            )
        # Release the slot we just took ÔÇö it will be re-acquired when SSE connects
        await release_session_slot()

        token = str(uuid.uuid4())
        token_store[token] = RProcessHandle(token, base_url, api_key)
        forwarded_proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host", "localhost:8081")
        url_prefix = os.environ.get("URL_PREFIX", "")
        if not url_prefix or not url_prefix.strip():
            url_prefix = "/el"
        elif not url_prefix.startswith("/"):
            url_prefix = "/" + url_prefix
        url_prefix = url_prefix.rstrip("/")
        personal_url = f"{forwarded_proto}://{host}{url_prefix}/mcp?token={token}"
        logger.info("Registered new session token=%s from %s", token[:8], remote_ip)
        _audit("REGISTER", token_prefix=token[:8], remote_ip=remote_ip)
        return HTMLResponse(_registration_success_page(personal_url))
    return HTMLResponse(_create_register_form())


async def sse_stream(request: Request):
    token = request.query_params.get("token", "")
    handle = token_store.get(token)
    if handle is None:
        _audit("SSE_INVALID_TOKEN", token_prefix=token[:8] if token else "none")
        return HTMLResponse("Invalid or expired token.", status_code=401)
    handle.touch()
    try:
        await handle.ensure_running()
    except RuntimeError as e:
        logger.warning("SSE spawn denied: %s", e)
        return HTMLResponse(str(e), status_code=503)

    _audit("SSE_START", token_prefix=token[:8])

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    url_prefix = os.environ.get("URL_PREFIX", "")
    if not url_prefix or not url_prefix.strip():
        url_prefix = "/el"
    elif not url_prefix.startswith("/"):
        url_prefix = "/" + url_prefix
    url_prefix = url_prefix.rstrip("/")
    messages_url = f"{scheme}://{host}{url_prefix}/mcp?token={token}"

    q = await handle.subscribe()

    async def event_generator():
        try:
            yield f"event: endpoint\ndata: {messages_url}\n\n"
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
    token = request.query_params.get("token", "")
    handle = token_store.get(token)
    if handle is None:
        _audit("POST_INVALID_TOKEN", token_prefix=token[:8] if token else "none")
        return HTMLResponse("Invalid or expired token.", status_code=401)
    if not handle.is_alive:
        _audit("POST_EXPIRED_SESSION", token_prefix=token[:8])
        return HTMLResponse("Session expired, please re-register.", status_code=410)
    body = await request.body()
    q = await handle.subscribe()
    try:
        await handle.write_stdin(body + b"\n")
        try:
            line = await asyncio.wait_for(q.get(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("MCP response timeout for token=%s", token[:8])
            return HTMLResponse("Timed out waiting for R subprocess response.", status_code=504)
        text = line.decode(errors="replace").rstrip()
        if text:
            return PlainTextResponse(text)
        return HTMLResponse("empty response from R subprocess", status_code=502)
    finally:
        handle.unsubscribe(q)


async def status_endpoint(request: Request):
    running = get_running_count()
    registered = len(token_store)
    return HTMLResponse(
        json.dumps({"running_subprocesses": running, "registered_sessions": registered}),
        media_type="application/json",
    )


# ÔöÇÔöÇ Background tasks ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

async def cleanup_expired_sessions():
    while True:
        try:
            now = time.time()
            expired = [(t, h) for t, h in token_store.items() if h.expired]
            for t, h in expired:
                logger.info("Cleaning up expired session token=%s", t[:8])
                _audit("SESSION_EXPIRED", token_prefix=t[:8])
                await h.shutdown()
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
        _audit("SERVER_SHUTDOWN", token_prefix=token[:8])
        await handle.shutdown()
    token_store.clear()


# ÔöÇÔöÇ App factory ÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇÔöÇ

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.api_route("/register", methods=["GET", "POST"])
    @limiter.limit(os.environ.get("ELABMCP_RATE_LIMIT", "10/minute"))
    async def register_route(request: Request):
        return await register_page(request)

    @app.get("/mcp")
    async def mcp_sse(request: Request):
        return await sse_stream(request)

    @app.post("/mcp")
    async def mcp_post(request: Request):
        return await mcp_messages(request)

    @app.get("/status")
    async def status_route(request: Request):
        return await status_endpoint(request)

    return app
