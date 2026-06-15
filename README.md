# Unified Research Data MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2025--03--26-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![R](https://img.shields.io/badge/R-4.4.2-276DC3?logo=r&logoColor=white)](https://r-project.org)

Host two MCP servers — **[datatagger-mcp](https://github.com/harrytyp/datatagger-mcp)** and **[elabrmcp](https://github.com/MarvinLuepke/elabR/tree/main/mcp/elabrmcp)** (elabFTW) — behind a single [Caddy](https://caddyserver.com/) reverse proxy, each with mandatory **bring-your-own-API-key** registration.

> **Server admins never configure any API keys.** Every user registers their personal credentials via a web page. No secrets in `.env`, no shared tokens, no admin-managed keys.

| MCP Server | Backend | Auth Mechanism |
|---|---|---|
| **datatagger-mcp** | [Python / FastMCP](https://github.com/modelcontextprotocol/python-sdk) | `/register` → HMAC-signed JWT (no server storage) |
| **elabrmcp** (elabFTW) | [R / ellmer](https://cran.r-project.org/package=ellmer) + [mcptools](https://cran.r-project.org/package=mcptools) | **elabmcp-proxy** → per-user R subprocess, JWT tokens |

### Web GUIs

| Service | Type | Access | Source |
|---------|------|--------|--------|
| **eConversion Knowledge Assistant** | Streamlit chat (956 papers, 42 PIs) | `econversion.researchmcp.duckdns.org` — password-protected | [alexburg14/MCP_eConversion](https://github.com/alexburg14/MCP_eConversion) |
| **elab App** | elabFTW companion GUI | `elab-app.researchmcp.duckdns.org` | [ffelsen/elab_app](https://github.com/ffelsen/elab_app) |
| **Proespm** | Scientific data reports | `proespm.researchmcp.duckdns.org` | [matkrin/proespm-py3](https://github.com/matkrin/proespm-py3) |



---

## Architecture

```text
                               ┌──────────────┐
                               │    Caddy     │
                               └──────┬───────┘
                                      │
                         ┌────────────┼────────────┐
                         ▼            ▼            │
             ┌──────────────────┐ ┌──────────────────┐
             │  datatagger-mcp  │ │  elabmcp-proxy   │
             │  port 8000       │ │  port 8081       │
             │  Python/FastMCP  │ │  Python/Starlette │
             │  /register →     │ │  /register →     │
             │  /mcp/?token=X   │ │  /mcp?token=X    │
             └──────────────────┘ └────────┬─────────┘
                                           │ spawns R subprocesses
                                           ▼
                               ┌──────────────────────┐
                               │  Rscript per session  │
                               │  elabrmcp (unmod.)    │
                               └──────────────────────┘
```

**elabR source code is never modified.** The [elabmcp-proxy](./elabmcp-proxy) spawns the unmodified `elabrmcp::elabr_mcp_server(type='stdio')` with each user's credentials injected as environment variables. You can `git pull` [elabR](https://github.com/MarvinLuepke/elabR) independently.



## eConversion Knowledge Assistant

The [eConversion Knowledge Assistant](https://econversion.researchmcp.duckdns.org) is a web-based chat interface for the e-conversion research cluster (TUM / LMU / FHI / MPI FKF). It provides:

- **956 publications** from `e-conversion.de/publikationen`
- **953 abstracts** (99.7% coverage) — 905 from EndNote library, 47 from OpenAlex, 1 from Semantic Scholar
- **42 PI profiles** with 2,314 linked publications
- **Semantic search** via BGE-small embeddings (384-dim)
- **LLM-backed answers** via GWDG SAIA / Academic Cloud Chat AI endpoint

> The app code lives at **[alexburg14/MCP_eConversion](https://github.com/alexburg14/MCP_eConversion)**.
> Only the deployment infrastructure (Dockerfile, Caddy route, docker-compose entry) is in this repo.

**Access:** `https://econversion.researchmcp.duckdns.org` — password-protected with HTTP Basic Auth.

---

---

## Quick Start

### 1. Clone repos

```bash
git clone https://github.com/harrytyp/unified-researchdata-mcp.git
cd unified-researchdata-mcp

# Clone the two MCP server dependencies alongside it
git clone https://github.com/harrytyp/datatagger-mcp.git
git clone https://github.com/MarvinLuepke/elabR.git
```

### 2. Configure

```bash
cp .env.example .env
```

Set your [DataTagger](https://datatagger.ub.tum.de) instance URL if not using the default — **no API keys go here**.

### 3. Deploy

```bash
docker compose up -d --build
```

[Three containers](docker-compose.yml) are built:

| Container | Tech Stack | Role |
|---|---|---|
| `unified-mcp-datatagger-mcp` | [Python](https://python.org) / [FastMCP](https://github.com/modelcontextprotocol/python-sdk) | [DataTagger](https://github.com/harrytyp/datatagger-mcp) MCP server |
| `unified-mcp-elabmcp-proxy` | [Python](https://python.org) / [FastAPI](https://fastapi.tiangolo.com) + [R](https://r-project.org) / [ellmer](https://cran.r-project.org/package=ellmer) | elabFTW auth-proxy + per-user R subprocesses |
| `unified-mcp-caddy` | [Caddy](https://caddyserver.com) | TLS termination & reverse proxy |

---

## User Workflow

### DataTagger

```text
1. 👤 User visits  https://datatagger.your-domain.com/register
2. 🔑 Pastes their personal FDM_TOKEN
3. 🔗 Receives scoped URL:  https://datatagger.your-domain.com/mcp/?token=<uuid>
4. ⚙️ Registers URL in MCP client (Claude Desktop, KISSKI, etc.)
```

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

> **DuckDNS auto-update:** See [docs/duckdns-setup.md](docs/duckdns-setup.md) for the cronjob setup to keep your domain IP current.

## Caddy Configuration

Edit [`Caddyfile`](./Caddyfile) to match your domain setup.

### Option 1: Two subdomains (recommended for production)

Replace `your-domain.com` with your actual domain:

```text
datatagger.your-domain.com { ... }
elab.your-domain.com       { ... }
```

### Option 2: Single domain with path-based routing (e.g., DuckDNS)

If you only have one domain (like a DuckDNS subdomain), use `handle_path` to strip the prefix:

```caddy
yourdomain.duckdns.org {
    handle_path /datatagger/* {
        reverse_proxy datatagger-mcp:8000
    }

    handle_path /elab/* {
        reverse_proxy elabmcp-proxy:8081
    }
}
```

Then access:
- DataTagger registration: `https://yourdomain.duckdns.org/datatagger/register`
- elabFTW registration:   `https://yourdomain.duckdns.org/elab/register`

### Local testing without DNS

Access the containers directly:

| Service | URL |
|---|---|
| DataTagger registration | `http://localhost:8000/register` |
| elabFTW registration   | `http://localhost:8081/register` |

---

## elabmcp-proxy

The [elabmcp-proxy](./elabmcp-proxy) is a [Python](https://python.org) / [FastAPI](https://fastapi.tiangolo.com) service that adds per-user authentication in front of [elabrmcp](https://github.com/MarvinLuepke/elabR/tree/main/mcp/elabrmcp) without modifying its source code.

```text
elabmcp-proxy/
├── Dockerfile              # R + elabR + elabrmcp + Python proxy
├── requirements.txt
├── pyproject.toml
└── src/elabmcp_proxy/
    ├── __init__.py
    ├── __main__.py         # Entry point
    ├── app.py              # FastAPI: /register, SSE↔stdio bridge
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

# Docker integration tests (requires running containers):
DOCKER_TESTS=1 pytest tests/test_docker_services.py -v
```

---

## Security Audit

> 📋 Full changelog: [CHANGELOG.md](./CHANGELOG.md)

### Current posture

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
| [elabR / elabrmcp](https://github.com/MarvinLuepke/elabR) | External | elabFTW R API client + MCP server |
| [datatagger-mcp](https://github.com/harrytyp/datatagger-mcp) | External | DataTagger MCP server |
| [eConversion](https://github.com/alexburg14/MCP_eConversion) | External | eConversion publication search (Streamlit) |
| [elab_app](https://github.com/ffelsen/elab_app) | External | elabFTW companion web app |
| [proespm-py3](https://github.com/matkrin/proespm-py3) | External | Scientific data reports web app |
| [ellmer](https://cran.r-project.org/package=ellmer) | CRAN | R MCP client library |
| [mcptools](https://cran.r-project.org/package=mcptools) | CRAN | R MCP transport layer |
| [FastAPI](https://fastapi.tiangolo.com) | PyPI | Python web framework (elabmcp-proxy) |
| [Caddy](https://caddyserver.com) | External | TLS reverse proxy |
| [Docker](https://www.docker.com) | External | Container runtime |
| [MCP Protocol](https://modelcontextprotocol.io/) | Specification | Model Context Protocol |

---

## License

This project is licensed under the [MIT License](LICENSE). The dependency repos ([elabR](https://github.com/MarvinLuepke/elabR), [datatagger-mcp](https://github.com/harrytyp/datatagger-mcp)) are governed by their respective licenses.