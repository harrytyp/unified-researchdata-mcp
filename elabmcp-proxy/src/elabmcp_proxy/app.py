"""FastAPI app: registration UI + shared R worker proxy."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import HTMLResponse, Response

from .jwt_token import encode_token, decode_token
from .r_worker import SharedRWorker

logger = logging.getLogger("elabmcp-proxy.app")

# ── Rate limiting ──
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ── Shared R worker (one process, all users) ──
r_worker = SharedRWorker()

# ── Audit logging ──
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


# ── Auth helper ──

def _get_creds_from_jwt(token: str) -> tuple[str, str] | None:
    """Decode JWT and return (api_key, base_url) or None."""
    payload = decode_token(token)
    if payload is None:
        return None
    return payload["k"], payload["u"]


# ── HTML templates ──

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
<p style="color:#666;">Enter your elabFTW credentials to generate a permanent MCP session URL.</p>
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
<p>Use the following URL in your MCP client (Claude Desktop, KISSKI, any MCP agent):</p>
<div style="background:#f8f9fa;padding:15px;border-radius:4px;word-break:break-all;font-family:monospace;border:1px solid #eee;margin:10px 0;">
{personal_url}
</div>
<p style="color:#666;font-size:0.9em;margin-top:20px;">
Token expires in 30 days — re-visit this page to generate a new one.<br>
Single shared R worker — no per-user processes, supports unlimited users.
</p>
<a href="/register" style="color:#3498db;">&larr; Register another key</a>
</div></body></html>"""


# ── Routes ──

async def register_page(request: Request):
    if request.method == "POST":
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        base_url = str(form.get("base_url", "")).strip()
        remote_ip = request.client.host if request.client else "unknown"

        if not api_key or not base_url:
            return HTMLResponse(_create_register_form("API Key and Base URL are required."), status_code=400)

        try:
            token = encode_token(base_url, api_key)
        except RuntimeError as e:
            logger.error("Token creation failed: %s", e)
            return HTMLResponse(
                _create_register_form("Server misconfiguration: MCP_JWT_SECRET not set."),
                status_code=500,
            )

        forwarded_proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host", "localhost:8081")
        url_prefix = os.environ.get("URL_PREFIX", "")
        if not url_prefix or not url_prefix.strip():
            url_prefix = "/el"
        elif not url_prefix.startswith("/"):
            url_prefix = "/" + url_prefix
        url_prefix = url_prefix.rstrip("/")
        personal_url = f"{forwarded_proto}://{host}{url_prefix}/mcp?token={token}"
        logger.info("Registered new JWT token from %s", remote_ip)
        _audit("REGISTER", remote_ip=remote_ip)
        return HTMLResponse(_registration_success_page(personal_url))
    return HTMLResponse(_create_register_form())


async def handle_mcp(request: Request):
    """Handle both GET and POST to /mcp.

    GET  → ensure R worker is running, return 204 (no SSE streaming).
    POST → decode JWT, proxy to shared R worker with auth headers.
    """
    if request.method == "GET":
        # Ensure the shared R worker is running
        if not r_worker.is_alive:
            try:
                await r_worker.start()
            except RuntimeError as e:
                return HTMLResponse(str(e), status_code=503)
        return Response(status_code=204)

    # POST: decode JWT and proxy to R
    token = request.query_params.get("token", "")
    creds = _get_creds_from_jwt(token)
    if creds is None:
        _audit("POST_INVALID_TOKEN", token_prefix=token[:16] if token else "none")
        return HTMLResponse("Invalid or expired token.", status_code=401)

    api_key, base_url = creds

    if not r_worker.is_alive:
        try:
            await r_worker.start()
        except RuntimeError as e:
            return HTMLResponse(str(e), status_code=503)

    body = await request.body()
    status, resp_text = await r_worker.proxy_request(api_key, base_url, body)

    if status == 202:
        # Notification accepted — no response body
        return Response(status_code=202)

    if status == 200 and resp_text:
        return Response(
            content=resp_text,
            media_type="application/json",
        )

    if status == 200 and not resp_text:
        return HTMLResponse("Empty response from R worker", status_code=502)

    return HTMLResponse(resp_text or f"R worker error (HTTP {status})", status_code=status)


async def status_endpoint(request: Request):
    return HTMLResponse(
        json.dumps({
            "r_worker_alive": r_worker.is_alive,
            "r_worker_ready": r_worker.is_ready,
        }),
        media_type="application/json",
    )


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the shared R worker at boot
    try:
        await r_worker.start()
    except RuntimeError as e:
        logger.error("Failed to start shared R worker: %s", e)
    yield
    await r_worker.shutdown()


# ── App factory ──

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.api_route("/register", methods=["GET", "POST"])
    @limiter.limit(os.environ.get("ELABMCP_RATE_LIMIT", "10/minute"))
    async def register_route(request: Request):
        return await register_page(request)

    @app.api_route("/mcp", methods=["GET", "POST"])
    async def mcp_route(request: Request):
        return await handle_mcp(request)

    @app.get("/status")
    async def status_route(request: Request):
        return await status_endpoint(request)

    return app
