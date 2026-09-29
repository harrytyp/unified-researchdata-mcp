"""Self-contained HMAC-signed tokens for registered users.

Token format: ``urlsafe_base64(json_payload).hex(HMAC-SHA256)``
Payload: ``{"u": <base64 base_url>, "k": <base64 api_key>, "p": <profile>,
"t": <enabled tool names or null>, "exp": <unix seconds>}``

Same scheme as the DataTagger proxy, so one mental model covers both.
The token is self-contained: the server stores nothing.
"""

import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_EXPIRY_DAYS = int(os.environ.get("MCP_TOKEN_EXPIRY_DAYS", "30"))


def _secret() -> str:
    secret = os.environ.get("MCP_JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "MCP_JWT_SECRET is not set. Generate one with: "
            'python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"'
        )
    return secret


def encode_token(
    base_url: str,
    api_key: str,
    *,
    profile: str = "r",
    enabled_tools: list[str] | None = None,
    expiry_days: int | None = None,
) -> str:
    """Create a self-contained HMAC-signed token with embedded credentials."""
    days = TOKEN_EXPIRY_DAYS if expiry_days is None else expiry_days
    payload = {
        "u": base64.urlsafe_b64encode(base_url.encode()).decode(),
        "k": base64.urlsafe_b64encode(api_key.encode()).decode(),
        "p": profile,
        "exp": int(time.time()) + days * 86400,
    }
    if enabled_tools is not None:
        payload["t"] = enabled_tools
    payload_b64 = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    sig = hmac.new(_secret().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_token(token: str) -> dict | None:
    """Decode and verify a token. Returns the payload or None."""
    try:
        secret = _secret()
    except RuntimeError:
        return None
    try:
        payload_b64, sig = token.split(".", 1)
        expected = hmac.new(
            secret.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if time.time() > payload.get("exp", 0):
            return None
        payload["u"] = base64.urlsafe_b64decode(payload["u"]).decode()
        payload["k"] = base64.urlsafe_b64decode(payload["k"]).decode()
        return payload
    except Exception:  # noqa: BLE001 -- anything malformed is an invalid token
        return None
