"""The ASGI application: MCP endpoint, registration page, health.

Auth is resolved per request by a plain ASGI middleware — not a Starlette
``BaseHTTPMiddleware``, which runs in its own task and would lose the context
variable the tool handlers read.
"""

import logging
import os
from contextlib import asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from . import client, server
from .auth import set_credential
from .config import settings
from .register import register_page, register_result

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nomad_mcp.app")


def _credential_from(scope) -> tuple[str | None, str]:
    """The raw credential of this request and how it arrived."""
    query = scope.get("query_string", b"").decode("utf-8", "replace")
    for part in query.split("&"):
        if part.startswith("token="):
            value = part[len("token=") :]
            if value:
                return value, "query"
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            decoded = value.decode("utf-8", "replace")
            if decoded.lower().startswith("bearer "):
                return decoded[7:].strip(), "header"
    return None, "none"


class CredentialMiddleware:
    """Put the caller's credential into the context before anything runs."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            raw, origin = _credential_from(scope)
            set_credential(raw, origin)
            path = scope.get("path", "")
            if settings.require_token and raw is None and path.startswith("/mcp"):
                response = JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32001, "message": "A token is required"},
                        "id": None,
                    },
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "server": "nomad-mcp",
            "version": "0.1.0",
            "default_pat": bool(settings.default_pat),
            "base_url": settings.base_url,
            "tools": len(server.tool_names()),
        }
    )


async def _validate_key(base_url: str, api_key: str) -> tuple[bool, str, str]:
    """Is this a usable NOMAD key, and whose? Returns (ok, name, message).

    `/users/me` is the natural probe but needs the `users:read` scope, which a
    data token usually lacks; a 403 there means the key is valid but scoped
    elsewhere, so a second probe on `/uploads` decides.
    """
    try:
        probe = await client.request("GET", "/users/me", base_url=base_url, api_key=api_key)
        data = probe.get("data") if isinstance(probe, dict) and isinstance(probe.get("data"), dict) else probe
        name = str(data.get("name") or data.get("username") or "") if isinstance(data, dict) else ""
        return True, name, ""
    except client.NomadError as exc:
        if exc.status == 401:
            return False, "", (
                "NOMAD rejected that key. Create a personal access token under "
                "your NOMAD account settings and paste it here."
            )
        if exc.status != 403:
            return False, "", f"Could not validate the key: {exc}"
    try:
        await client.request("GET", "/uploads", base_url=base_url, api_key=api_key, params={"page_size": 1})
        return True, "", ""
    except client.NomadError as exc:
        if exc.status in (401, 403):
            return False, "", (
                "NOMAD accepted the key but it may not read anything: it needs at "
                "least the uploads or entries read scope."
            )
        return False, "", f"Could not validate the key: {exc}"


async def register(request: Request) -> HTMLResponse:
    if request.method == "GET":
        return HTMLResponse(register_page(settings.base_url))
    form = await request.form()
    api_key = str(form.get("api_key", "")).strip()
    base_url = str(form.get("base_url", "")).strip() or settings.base_url
    selected = [str(name) for name in form.getlist("tools")] or None
    if not api_key:
        return HTMLResponse(
            register_page(base_url, error="A NOMAD API key is required."), status_code=400
        )
    ok, name, message = await _validate_key(base_url, api_key)
    if not ok:
        log.info("registration refused")
        return HTMLResponse(register_page(base_url, error=message), status_code=400)

    from .jwt_token import encode_token

    token = encode_token(base_url, api_key, profile="r", enabled_tools=selected)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    url = f"{scheme}://{host}{settings.url_prefix}/mcp?token={token}"
    return HTMLResponse(register_result(url, token, name, len(selected or server.tool_names())))


@asynccontextmanager
async def lifespan(_: Starlette):
    async with server.mcp.session_manager.run():
        log.info(
            "nomad-mcp ready: base_url=%s default_pat=%s anonymous=%s require_token=%s",
            settings.base_url,
            bool(settings.default_pat),
            settings.anonymous,
            settings.require_token,
        )
        yield
    await client.aclose()


mcp_app = server.mcp.streamable_http_app(
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    session_idle_timeout=1800,
)

app = Starlette(
    routes=[
        Route("/health", health),
        Route("/register", register, methods=["GET", "POST"]),
        Route("/", lambda _: PlainTextResponse("nomad-mcp — MCP at /mcp, registration at /register")),
        Mount("/", app=mcp_app),
    ],
    lifespan=lifespan,
)
app = CredentialMiddleware(app)
