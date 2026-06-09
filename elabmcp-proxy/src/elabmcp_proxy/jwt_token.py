"""JWT-like token encode/decode using HMAC-SHA256 (no external libs needed).

Token format: urlsafe_base64(json_payload).hex(HMAC-SHA256)
Payload: {"u": <base64 base_url>, "k": <base64 api_key>, "p": <profile>, "exp": <unix_epoch_seconds>}
Profile: "r" = readonly, "h" = hybrid, "f" = full (write)
The token is self-contained — no server-side storage required.
Expiry: 30 days from registration.
"""

import base64
import hashlib
import hmac
import json
import os
import time

TOKEN_EXPIRY_DAYS = int(os.environ.get("MCP_TOKEN_EXPIRY_DAYS", "30"))

# ── Shared helper: load JWT secret from env ──────────────────────────────────

def _get_jwt_secret() -> str:
    """Get the JWT signing secret from environment."""
    secret = os.environ.get("MCP_JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "MCP_JWT_SECRET environment variable is not set. "
            "Generate one with: python3 -c \"import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())\""
        )
    return secret


# ── Token encoding ───────────────────────────────────────────────────────────

def encode_token(base_url: str, api_key: str, profile: str = 'r', secret: str | None = None, expiry_days: int | None = None) -> str:
    """Create a self-contained HMAC-signed token with embedded credentials."""
    if secret is None:
        secret = _get_jwt_secret()
    if expiry_days is None:
        expiry_days = TOKEN_EXPIRY_DAYS

    payload = {
        "u": base64.urlsafe_b64encode(base_url.encode()).decode(),
        "k": base64.urlsafe_b64encode(api_key.encode()).decode(),
        "p": profile,
        "exp": int(time.time()) + expiry_days * 86400,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


# ── Token decoding ───────────────────────────────────────────────────────────

def decode_token(token: str, secret: str | None = None) -> dict | None:
    """Decode and verify token. Returns payload dict or None if invalid/expired."""
    if secret is None:
        try:
            secret = _get_jwt_secret()
        except RuntimeError:
            return None

    try:
        payload_b64, sig = token.split(".", 1)
        # Verify signature
        expected_sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        # Decode payload
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        # Check expiry
        if time.time() > payload.get("exp", 0):
            return None
        # Backward compat: old tokens without profile default to readonly
        if "p" not in payload:
            payload["p"] = "r"
        # Decode embedded strings
        payload["u"] = base64.urlsafe_b64decode(payload["u"]).decode()
        payload["k"] = base64.urlsafe_b64decode(payload["k"]).decode()
        return payload
    except (ValueError, KeyError, json.JSONDecodeError, Exception):
        return None
