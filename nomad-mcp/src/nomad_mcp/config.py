"""Configuration, read once from the environment."""

import os
from dataclasses import dataclass, field

DEFAULT_BASE_URL = "https://nomad-lab.eu/prod/v1/api/v1"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    """Everything the server needs to know about its deployment."""

    # NOMAD API the tools talk to unless a token carries its own base URL
    base_url: str = field(
        default_factory=lambda: os.environ.get("NOMAD_BASE_URL", "").strip()
        or DEFAULT_BASE_URL
    )
    # the deployment's own PAT: read-only access without a registration
    default_pat: str = field(
        default_factory=lambda: os.environ.get("NOMAD_MCP_DEFAULT_PAT", "").strip()
    )
    # with a default PAT configured, an unauthenticated call uses it
    anonymous: bool = field(
        default_factory=lambda: _flag("NOMAD_MCP_ALLOW_ANONYMOUS", True)
    )
    # refuse callers without any credential at all
    require_token: bool = field(
        default_factory=lambda: _flag("NOMAD_MCP_REQUIRE_TOKEN", False)
    )
    # HMAC secret for the registration tokens
    jwt_secret: str = field(
        default_factory=lambda: os.environ.get("MCP_JWT_SECRET", "").strip()
    )
    token_expiry_days: int = field(
        default_factory=lambda: int(os.environ.get("MCP_TOKEN_EXPIRY_DAYS", "30"))
    )
    url_prefix: str = field(
        default_factory=lambda: os.environ.get("URL_PREFIX", "/nm").rstrip("/") or "/nm"
    )
    # HTTP
    host: str = field(default_factory=lambda: os.environ.get("MCP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("MCP_PORT", "8000")))
    timeout_s: float = field(
        default_factory=lambda: float(os.environ.get("NOMAD_MCP_TIMEOUT_S", "60"))
    )
    # responses larger than this are truncated with a note (characters)
    max_response_chars: int = field(
        default_factory=lambda: int(os.environ.get("NOMAD_MCP_MAX_RESPONSE_CHARS", "60000"))
    )
    # requests per minute per credential; 0 turns the limiter off
    rate_limit: int = field(
        default_factory=lambda: int(os.environ.get("NOMAD_MCP_RATE_LIMIT", "120"))
    )
    # the NOMAD deployment's GUI, used to build clickable entry links
    gui_url: str = field(
        default_factory=lambda: os.environ.get(
            "NOMAD_GUI_URL", "https://nomad-lab.eu/prod/v1/gui/entry/id/{}"
        )
    )


settings = Settings()
