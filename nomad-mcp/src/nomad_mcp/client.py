"""The NOMAD API, read-only.

One shared HTTP client, one method per shape of request. Nothing here sends a
credential anywhere but to the configured NOMAD deployment, and no error
message carries the token.
"""

import json
import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("nomad_mcp.client")

_client: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout_s, connect=15.0),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            headers={"User-Agent": "nomad-mcp/0.1 (+unified-researchdata-mcp)"},
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class NomadError(RuntimeError):
    """A NOMAD request that did not answer with data."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _clean(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop what was not asked for; NOMAD rejects empty filters."""
    if not params:
        return {}
    return {
        k: v
        for k, v in params.items()
        if v is not None and v != "" and v != [] and v != {}
    }


def _detail(response: httpx.Response) -> str:
    """NOMAD's own error text, without echoing anything we sent."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        text = response.text or ""
        return text[:300] if text else response.reason_phrase
    if isinstance(body, dict):
        for key in ("detail", "message", "error"):
            value = body.get(key)
            if isinstance(value, str):
                return value[:300]
            if value is not None:
                return json.dumps(value)[:300]
    return json.dumps(body)[:300]


async def request(
    method: str,
    path: str,
    *,
    base_url: str,
    api_key: str = "",
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    """One call against the NOMAD API. Raises NomadError on anything else."""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = await http().request(
            method.upper(), url, params=_clean(params), json=body, headers=headers
        )
    except httpx.TimeoutException as exc:
        raise NomadError(504, f"NOMAD did not answer within {settings.timeout_s:.0f}s") from exc
    except httpx.HTTPError as exc:
        raise NomadError(502, f"Could not reach NOMAD: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise NomadError(response.status_code, _detail(response))

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    # the structure endpoint answers with a file body
    return {"text": response.text}
