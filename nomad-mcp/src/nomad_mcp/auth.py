"""Whose NOMAD account a call runs as.

The credential travels in the query string (``?token=``) or as
``Authorization: Bearer``. An ASGI middleware puts the raw value into a
context variable before the MCP handler runs — the same request, the same
task, so the value is there when a tool executes. It is never logged.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass

from .config import settings
from .jwt_token import decode_token

log = logging.getLogger("nomad_mcp.auth")

# raw credential of the request being handled, set by the ASGI middleware
_credential: ContextVar[str | None] = ContextVar("nomad_credential", default=None)
# how the credential arrived, for the audit line
_source: ContextVar[str] = ContextVar("nomad_credential_source", default="none")


@dataclass(frozen=True)
class Credential:
    """A resolved NOMAD identity: where to talk and with which key."""

    base_url: str
    api_key: str
    profile: str
    enabled_tools: tuple[str, ...] | None
    origin: str

    @property
    def read_only(self) -> bool:
        return self.profile != "f"


def set_credential(raw: str | None, origin: str) -> None:
    _credential.set(raw)
    _source.set(origin)


def resolve() -> Credential:
    """The credential for the current call.

    A registration token carries the user's own PAT and base URL; a bare
    value is taken as a NOMAD personal access token for this deployment; with
    nothing at all the deployment's own read-only PAT is used, if it has one.
    """
    raw = _credential.get()
    origin = _source.get()
    if raw:
        payload = decode_token(raw)
        if payload is not None:
            tools = payload.get("t")
            return Credential(
                base_url=(payload.get("u") or settings.base_url).rstrip("/"),
                api_key=payload.get("k", ""),
                profile=payload.get("p") or "r",
                enabled_tools=tuple(tools) if tools else None,
                origin=f"token/{origin}",
            )
        # not one of ours: a NOMAD PAT handed over directly
        return Credential(
            base_url=settings.base_url,
            api_key=raw,
            profile="r",
            enabled_tools=None,
            origin=f"pat/{origin}",
        )
    if raw is None and not settings.anonymous:
        return Credential(
            base_url=settings.base_url,
            api_key="",
            profile="r",
            enabled_tools=None,
            origin="anonymous",
        )
    return Credential(
        base_url=settings.base_url,
        api_key=settings.default_pat,
        profile="r",
        enabled_tools=None,
        origin="deployment-default" if settings.default_pat else "anonymous",
    )


def allowed(tool_name: str) -> bool:
    """Whether the current credential may call this tool."""
    credential = resolve()
    if credential.enabled_tools is None:
        return True
    return tool_name in credential.enabled_tools
