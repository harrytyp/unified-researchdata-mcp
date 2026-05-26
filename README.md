# Unified Research Data MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2025--03--26-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![R](https://img.shields.io/badge/R-4.4.2-276DC3?logo=r&logoColor=white)](https://r-project.org)

A self-hosted landing page for MCP servers and web tools on a single domain. Includes a static landing page at `researchmcp.duckdns.org`, MCP registration endpoints, and companion web apps.

| Service | Route | Tech |
|---|---|---|
| **datatagger-mcp** | [Python / FastMCP](https://github.com/modelcontextprotocol/python-sdk) | `/register` → HMAC-signed JWT (no server storage) |
| **elabrmcp** (elabFTW) | [R / ellmer](https://cran.r-project.org/package=ellmer) + [mcptools](https://cran.r-project.org/package=mcptools) | **elabmcp-proxy** → per-user R subprocess, JWT tokens |

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

### elabFTW / elabrmcp

```text
1. 👤 User visits  https://elab.your-domain.com/register
2. 🔑 Pastes their personal ELABFTW_BASE_URL + ELABFTW_API_KEY
3. 🔗 Receives scoped URL:  https://elab.your-domain.com/mcp?token=<uuid>
4. ⚙️ Registers URL in MCP client
5. 🚀 Proxy spawns a dedicated R subprocess with those credentials
6. 🧹 After 30 minutes idle, R process is killed and memory reclaimed
7. 🪙 Token is valid for 30 days — no re-registration needed after restarts
```

> **Note:** With path-based routing (single domain), replace the URLs accordingly:
> - Registration: `https://yourdomain.duckdns.org/datatagger/register` and `https://yourdomain.duckdns.org/elab/register`
> - MCP endpoints: `https://yourdomain.duckdns.org/datatagger/mcp` and `https://yourdomain.duckdns.org/elab/mcp`

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

1. **Registration** -- user enters credentials into web form -> server creates an HMAC-SHA256 JWT embedding the credentials (no server-side storage)
2. **R subprocess spawn** -- first `POST /mcp?token=X` spawns `Rscript -e "elabrmcp::elabr_mcp_server(type='stdio')"` with credentials as env vars
3. **Bridge** -- proxy translates MCP SSE events <-> stdio JSON-RPC lines via asyncio subprocess
4. **Isolation** -- each user gets a separate R process, no shared state
5. **Cleanup** -- processes killed after 30 minutes of inactivity

### Transport: stdio (not HTTP)

The R subprocess uses `type='stdio'` transport. This avoids a critical bug in R's HTTP backend (`type='http'`) which alternates between returning HTTP **200** and **202** for consecutive requests. This alternating behavior breaks any MCP client using Streamable HTTP (like Hermes Agent).

| Transport | Status | Issue |
|---|---|---|
| `type='http'` | Broken | R alternates 200/202 per request. proxy_request retries all get 202, client gets 502 |
| `type='stdio'` | Working | R reads JSON-RPC from stdin, writes to stdout. No HTTP layer = no 200/202 |

The stdio read timeout is 120s (configurable via `ELABMCP_STDIO_TIMEOUT`) to handle cold-start R package loading.

**Do NOT add a warmup/health-check request during ensure_running()** -- sending any request to R during startup creates a session collision. Even an empty POST body can leave R in a bad state.

### Known issues

- ~~Container restart wipes sessions:~~ **FIXED** — tokens are now self-contained JWTs signed with `MCP_JWT_SECRET`. Container restarts do NOT invalidate tokens. 30-day expiry.
- **Response timeout:** If R takes >120s to respond via stdout, the proxy returns 504. Increase ELABMCP_STDIO_TIMEOUT if needed.

### Running tests### Running tests

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
| Session expiry | ✅ | 30-minute inactivity (R process), 30-day token lifetime |
| In-transit encryption | ✅ | Terminated by Caddy (TLS) |
| Rate limiting | ✅ | [slowapi](https://github.com/AsylumSecurity/fastapi-limiter), 10 POST/min per IP |
| Subprocess resource caps | ✅ | `RLIMIT_AS` (256 MB), `RLIMIT_CPU` (300 s), `RLIMIT_NPROC` (64), global max 20 sessions |
| Audit logging | ✅ | Structured log at `ELABMCP_AUDIT_LOG` |
| Graceful shutdown | ✅ | `SIGTERM` → 3 s wait → `SIGKILL` |
| Docker resource limits | ✅ | Per-container `mem_limit` + `stop_grace_period` |
| Token-based auth | ✅ | HMAC-SHA256 JWTs, self-contained, no server storage |
| No persistent secrets | ✅ | JWTs are self-contained, no server-side credential storage |
| Test coverage | ✅ | 40 pytest + 15 Docker integration tests |

### Remaining areas

#### 🟡 Medium priority

1. **Token transmission in URL** — session tokens are passed as URL query parameters (`/mcp?token=X`). This exposes tokens in:
   - Server access logs
   - Browser history (if user visits the URL manually)
   - `Referer` headers
   - Consider moving the token to a header (`Authorization: Bearer X`) or a cookie

2. **HTTPS-only enforcement** — Caddy handles TLS, but the proxy containers also accept plain HTTP on their internal ports. A middleware should reject non- HTTPS requests (or rely on Caddy stripping them).

#### 🟢 Low priority

3. **Subprocess isolation** — all R subprocesses share the same Linux user inside the container. For stronger isolation, consider spawning each R process in a separate Docker container or using [nsjail](https://github.com/google/nsjail).


5. **Subprocess restart on crash** — if an R subprocess crashes, the SSE connection to the user drops and the session becomes unusable. The proxy could detect the crash and automatically re-spawn the subprocess for reconnect attempts.

6. **Memory-only credential lifetime** — credentials are stored in plain-text Python dicts. For advanced deployments, consider encrypting them at rest with a server-side key.

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
