# Unified Research Data MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2025--03--26-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![R](https://img.shields.io/badge/R-4.4.2-276DC3?logo=r&logoColor=white)](https://r-project.org)

A self-hosted landing page for MCP servers and web tools on a single domain. Includes a static landing page at `researchmcp.duckdns.org`, MCP registration endpoints, and companion web apps.

| Service | Route | Tech |
|---|---|---|
| **datatagger-mcp** | `/dt` | Python / FastMCP |
| **elabmcp-proxy** (elabFTW) | `/el` | Python / FastAPI + R / ellmer |
| **elab-app** | `elab-app.<domain>` | Streamlit (Python) |
| **proespm-app** | `proespm.<domain>` | Streamlit (Python) |
| **Landing page** | `/` | Static HTML |
| **NOMAD OASIS** | `/nomad-oasis` | Docker compose (separate) |

> Server admins never configure any API keys. Every user registers their personal credentials via a web page. No secrets in `.env`, no shared tokens, no admin-managed keys.

## Architecture

```text
                                    ┌──────────────┐
                                    │    Caddy     │
                                    └──────┬───────┘
                                           │
                         ┌─────────────────┼──────────────────┐
                         ▼                 ▼                  ▼
             ┌──────────────────┐ ┌──────────────────┐ ┌──────────────┐
             │  datatagger-mcp  │ │  elabmcp-proxy   │ │ Landing page │
             │  port 8000       │ │  port 8081       │ │  web/        │
             │  Python/FastMCP  │ │  Python/Starlette │ │  static HTML │
             │  /register       │ │  /register        │ └──────────────┘
             │  /mcp/?token=X   │ │  /mcp?token=X     │
             └──────────────────┘ └────────┬──────────┘
                                           │
                             ┌─────────────┼─────────────┐
                             ▼                           ▼
                  ┌──────────────────────┐    ┌──────────────────┐
                  │  Rscript per session  │    │  elab-app        │
                  │  elabrmcp (unmod.)    │    │  proespm-app     │
                  └──────────────────────┘    │  (Streamlit)     │
                                              └──────────────────┘
```

**elabR source code is never modified.** The elabmcp-proxy spawns the unmodified `elabrmcp::elabr_mcp_server(type='stdio')` with each user's credentials injected as environment variables. You can `git pull` elabR independently.

All MCP registration pages use JWT tokens (self-contained, no server-side storage). Registration forms match the dark theme of the landing page.

---

## Services

### MCP Servers (bring your own key)

| Server | Register at | Backend |
|---|---|---|
| **datatagger-mcp** | `/dt/register` | Python / FastMCP |
| **elabFTW MCP** | `/el/register` | R / ellmer via elabmcp-proxy |

Users visit the registration page, paste their personal API credentials, and receive a JWT URL to use in any MCP client (Claude Desktop, Cursor, Hermes, etc.).

### Web GUIs

| App | URL | Description |
|---|---|---|
| **NOMAD OASIS** | `/nomad-oasis/` | Materials science data management platform |
| **elab-app** | `elab-app.<domain>` | Streamlit companion for elabFTW (transcripts, templates) |
| **proespm-app** | `proespm.<domain>` | Upload scientific data files and generate HTML reports |

---

## Quick Start

### 1. Clone repos

```bash
git clone https://github.com/harrytyp/unified-researchdata-mcp.git
cd unified-researchdata-mcp

# Clone MCP server dependencies
git clone https://github.com/harrytyp/datatagger-mcp.git
git clone https://github.com/MarvinLuepke/elabR.git
```

### 2. Configure

```bash
cp .env.example .env
```

Set your DataTagger instance URL if not using the default. No API keys go here.

### 3. Deploy

```bash
docker compose up -d --build
```

Five containers are built:

| Container | Tech | Role |
|---|---|---|
| `datatagger-mcp` | Python / FastMCP | DataTagger MCP server |
| `elabmcp-proxy` | Python / FastAPI + R / ellmer | elabFTW auth-proxy + R subprocesses |
| `elab-app` | Python / Streamlit | elabFTW companion app |
| `proespm-app` | Python / Streamlit | Scientific data report generation |
| `caddy` | Caddy | TLS termination & reverse proxy |

### 4. Landing page

The static landing page at `web/index.html` is served by Caddy. Edit it to update service cards, descriptions, and links. No rebuild needed -- just edit the file and Caddy serves the new version.

---

## Caddy Configuration

Edit `Caddyfile` to match your domain setup. The current config uses `researchmcp.duckdns.org` with path-based routing and subdomains for Streamlit apps:

```caddy
elab-app.<domain> {
    reverse_proxy elab-app:8501
}

proespm.<domain> {
    reverse_proxy proespm-app:8501
}

<domain> {
    handle_path /dt* { reverse_proxy datatagger-mcp:8000 }
    handle_path /el* { reverse_proxy elabmcp-proxy:8081 }
    handle /nomad-oasis/* { reverse_proxy proxy:80 }
    root * /srv/http
    file_server browse
}
```

### Local testing

| Service | URL |
|---|---|
| DataTagger registration | `http://localhost:8000/register` |
| elabFTW registration | `http://localhost:8081/register` |
| elab-app | `http://localhost:8501` |
| proespm-app | `http://localhost:8501` |

---

## elabmcp-proxy

The elabmcp-proxy is a Python / FastAPI service that adds per-user authentication in front of elabrmcp without modifying its source code.

```
elabmcp-proxy/
├── Dockerfile              # R + elabR + elabrmcp + Python proxy
├── requirements.txt
├── pyproject.toml
└── src/elabmcp_proxy/
    ├── __init__.py
    ├── __main__.py         # Entry point
    ├── app.py              # FastAPI: /register, SSE<->stdio bridge
    └── session.py          # Per-user R subprocess lifecycle
```

### How it works

1. **Registration** -- user enters credentials, gets a JWT token (self-contained, no server storage)
2. **SSE connect** -- first `GET /mcp?token=X` spawns `Rscript -e "elabrmcp::elabr_mcp_server(type='stdio')"` with credentials via environment variables
3. **Bridge** -- proxy translates MCP SSE events to stdio JSON-RPC lines
4. **Cleanup** -- processes killed after 30 minutes of inactivity

### Running tests

```bash
cd elabmcp-proxy
pip install -e ".[dev]"
pytest tests/ -v

# Docker integration tests:
DOCKER_TESTS=1 pytest tests/test_docker_services.py -v
```

---

## Security

| Aspect | Status | Details |
|---|---|---|
| No admin-managed secrets | ✅ | `.env` contains no API keys |
| Per-user isolation | ✅ | Each user gets an OS-level R subprocess |
| Session expiry | ✅ | 30-minute inactivity timeout |
| In-transit encryption | ✅ | Terminated by Caddy (TLS) |
| Rate limiting | ✅ | slowapi, 10 POST/min per IP |
| Subprocess resource caps | ✅ | RLIMIT_AS (256 MB), RLIMIT_CPU (300 s), RLIMIT_NPROC (64), max 20 sessions |
| Token-based auth | ✅ | JWT tokens, self-contained |
| Audit logging | ✅ | Structured log at ELABMCP_AUDIT_LOG |
| Graceful shutdown | ✅ | SIGTERM -> 3s wait -> SIGKILL |
| Docker resource limits | ✅ | Per-container mem_limit + stop_grace_period |
| No persistent secrets | ⚠️ Partial | Sessions in-memory only (lost on restart) |

---

## Dependencies

| Component | Repository | Role |
|---|---|---|
| elabR / elabrmcp | [MarvinLuepke/elabR](https://github.com/MarvinLuepke/elabR) | elabFTW R API client + MCP server |
| datatagger-mcp | [harrytyp/datatagger-mcp](https://github.com/harrytyp/datatagger-mcp) | DataTagger MCP server |
| elab_app | [ffelsen/elab_app](https://github.com/ffelsen/elab_app) | elabFTW Streamlit companion |
| proespm-py3 | [matkrin/proespm-py3](https://github.com/matkrin/proespm-py3) | Scientific data report generator |
| ellmer | CRAN | R MCP client library |
| mcptools | CRAN | R MCP transport layer |
| FastAPI | PyPI | Python web framework (elabmcp-proxy) |
| Caddy | External | TLS reverse proxy |

## License

MIT
