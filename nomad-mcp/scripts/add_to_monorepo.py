#!/usr/bin/env python3
"""Add the NOMAD MCP service to the monorepo stack: compose service + Caddy route.

Idempotent: running it twice changes nothing. Rewrites files in place (same
inode) so bind-mounted single files keep working.
"""
import io
import re
import sys

ROOT = "/home/debian/unified-researchdata-mcp"
COMPOSE = f"{ROOT}/docker-compose.yml"
CADDY = f"{ROOT}/Caddyfile"

SERVICE = """  # ── NOMAD MCP (read-only, registration + deployment default PAT) ─────────
  nomad-mcp:
    build:
      context: .
      dockerfile: nomad-mcp/Dockerfile
    restart: unless-stopped
    expose:
      - "8000"
    environment:
      # The deployment's own NOMAD (the Oasis behind the internal nginx) unless
      # overridden; the register page lets a user point at any NOMAD instead.
      - NOMAD_BASE_URL=${NOMAD_MCP_BASE_URL:-http://proxy:80/nomad-oasis/api/v1}
      - NOMAD_GUI_URL=${NOMAD_MCP_GUI_URL:-}
      # Read-only access for callers that never register.
      - NOMAD_MCP_DEFAULT_PAT=${NOMAD_MCP_DEFAULT_PAT:-}
      - NOMAD_MCP_ALLOW_ANONYMOUS=${NOMAD_MCP_ALLOW_ANONYMOUS:-true}
      - NOMAD_MCP_REQUIRE_TOKEN=${NOMAD_MCP_REQUIRE_TOKEN:-false}
      - NOMAD_MCP_RATE_LIMIT=${NOMAD_MCP_RATE_LIMIT:-120}
      - NOMAD_MCP_MAX_RESPONSE_CHARS=${NOMAD_MCP_MAX_RESPONSE_CHARS:-60000}
      - NOMAD_MCP_TIMEOUT_S=${NOMAD_MCP_TIMEOUT_S:-60}
      - URL_PREFIX=/nm
      - MCP_PORT=8000
      - MCP_HOST=0.0.0.0
      - PYTHONUNBUFFERED=1
      - MCP_JWT_SECRET=${MCP_JWT_SECRET}
      - MCP_TOKEN_EXPIRY_DAYS=${MCP_TOKEN_EXPIRY_DAYS:-30}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
      interval: 30s
      timeout: 6s
      retries: 3
      start_period: 15s
    networks:
      - default
      - nomad_oasis_network
    mem_limit: 512m
    stop_grace_period: 15s

"""

CADDY_ROUTE = """\thandle_path /nm* {
\t\turi strip_prefix /nm
\t\treverse_proxy nomad-mcp:8000 {
\t\t\tflush_interval -1
\t\t}
\t}

"""


def read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def patch_compose(text):
    if "nomad-mcp:" in text:
        return text, "compose: already present"
    anchor = "  # ── elabFTW MCP (shared R worker, one process for all users) ──"
    if anchor not in text:
        return text, "compose: ANCHOR NOT FOUND"
    text = text.replace(anchor, SERVICE + anchor, 1)
    text = text.replace(
        "    depends_on:\n      - datatagger-proxy\n",
        "    depends_on:\n      - datatagger-proxy\n      - nomad-mcp\n",
        1,
    )
    return text, "compose: service inserted"


def patch_caddy(text):
    if "handle_path /nm*" in text:
        return text, "caddy: already present"
    if "@api path /dt/* /el/*\n" not in text:
        return text, "caddy: API matcher NOT FOUND"
    text = text.replace(
        "@api path /dt/* /el/*\n", "@api path /dt/* /el/* /nm/*\n", 1
    )
    anchor = "\thandle_path /dt* {\n"
    if anchor not in text:
        return text, "caddy: route anchor NOT FOUND"
    text = text.replace(anchor, CADDY_ROUTE + anchor, 1)
    text = text.replace(
        "# /, die MCP-Proxies unter /el und /dt und NOMAD - damit auch die SSO-Session -",
        "# /, die MCP-Proxies unter /el, /dt und /nm und NOMAD - damit auch die SSO-Session -",
        1,
    )
    return text, "caddy: route inserted"


def main():
    compose = read(COMPOSE)
    caddy = read(CADDY)
    new_compose, m1 = patch_compose(compose)
    new_caddy, m2 = patch_caddy(caddy)
    print(m1)
    print(m2)
    if "NOT FOUND" in m1 or "NOT FOUND" in m2:
        return 1
    if new_compose != compose:
        write(COMPOSE, new_compose)
    if new_caddy != caddy:
        write(CADDY, new_caddy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
