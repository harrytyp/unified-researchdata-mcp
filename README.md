# Unified Research Data MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2025--03--26-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![R](https://img.shields.io/badge/R-4.4.2-276DC3?logo=r&logoColor=white)](https://r-project.org)

Host two MCP servers — **[datatagger-mcp](https://github.com/harrytyp/datatagger-mcp)** and **[elabrmcp](https://github.com/MarvinLuepke/elabR/tree/main/mcp/elabrmcp)** (elabFTW) — behind a single [Caddy](https://caddyserver.com/) reverse proxy, each with mandatory **bring-your-own-API-key** registration.

> **Server admins never configure any API keys.** Every user registers their personal credentials via a web page. No secrets in `.env`, no shared tokens, no admin-managed keys.

| MCP Server | Backend | Auth Mechanism |
|---|---|---|
| **datatagger-mcp** | [Python / FastMCP](https://github.com/modelcontextprotocol/python-sdk) | Built-in `/register` → session token |
| **elabrmcp** (elabFTW) | [R / ellmer](https://cran.r-project.org/package=ellmer) + [mcptools](https://cran.r-project.org/package=mcptools) | **elabmcp-proxy** → per-user R subprocess |

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
6. 🧹 After 30 minutes idle, process is killed and memory reclaimed
```

---

## Caddy Configuration

Edit [`Caddyfile`](./Caddyfile) and replace `your-domain.com` with your actual domain:

```text
datatagger.your-domain.com { ... }
elab.your-domain.com       { ... }
```

For local testing without DNS, access the containers directly:

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

1. **Registration** — user enters credentials → stored in memory with [UUID4](https://docs.python.org/3/library/uuid.html) token
2. **SSE connect** — first `GET /mcp?token=X` spawns `Rscript -e "elabrmcp::elabr_mcp_server(type='stdio')"` with `ELABFTW_BASE_URL` and `ELABFTW_API_KEY` set via environment variables
3. **Bridge** — proxy translates [MCP SSE](https://spec.modelcontextprotocol.io/specification/2025-03-26/basic/transports/) events ↔ stdio [JSON-RPC](https://www.jsonrpc.org/) lines using [asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html)
4. **Isolation** — each user gets a separate R process, no shared state
5. **Cleanup** — processes are killed after 30 minutes of inactivity by a background task

---

## Security Audit

### Current posture

| Aspect | Status | Details |
|---|---|---|
| No admin-managed secrets | ✅ | `.env` contains no API keys |
| Per-user isolation | ✅ | Each user gets an OS-level R subprocess |
| Session expiry | ✅ | 30-minute inactivity timeout |
| In-transit encryption | ✅ | Terminated by Caddy (TLS) |
| Token-based auth | ✅ | UUID4 tokens, one per session |
| No persistent secrets | ⚠️ Partial | Tokens stored in-memory only (lost on restart) |

### Areas for improvement

#### 🔴 High priority

1. **Rate limiting on `/register`** — the registration endpoint has no rate limiting, making it vulnerable to credential-stuffing or DoS via excessive subprocess creation. A production deployment should add [slowapi](https://github.com/AsylumSecurity/fastapi-limiter) or a reverse-proxy rate limit.

2. **Subprocess resource caps** — each R process consumes 100-200 MB RAM and takes 5-15 seconds to start. A malicious user could register many tokens and trigger SSE connections to exhaust server memory. Mitigations:
   - Enforce a maximum number of concurrent sessions per IP
   - Set a hard global limit on running subprocesses
   - Add [Docker --memory limits](https://docs.docker.com/config/containers/resource_constraints/) on the container

3. **Parameterized subprocess isolation** — currently, all R subprocesses share the same Linux user inside the container. For stronger isolation, consider spawning each R process in a separate Docker container or using [nsjail](https://github.com/google/nsjail).

#### 🟡 Medium priority

4. **Audit logging** — there is no audit trail for registrations, tool invocations, or session expirations. Production deployments should log:
   - Registration events (anonymized: truncated token prefix)
   - Session creation and expiry
   - Error events (R subprocess crashes, auth failures)

5. **Token transmission in URL** — session tokens are passed as URL query parameters (`/mcp?token=X`). This exposes tokens in:
   - Server access logs
   - Browser history (if user visits the URL manually)
   - `Referer` headers
   - Consider moving the token to a header (`Authorization: Bearer X`) or a cookie

6. **HTTPS-only enforcement** — Caddy handles TLS, but the proxy containers also accept plain HTTP on their internal ports. A middleware should reject non- HTTPS requests (or rely on Caddy stripping them).

#### 🟢 Low priority

7. **Session persistence** — restarting the elabmcp-proxy container drops all active sessions. For high-availability deployments, consider storing session tokens in [Redis](https://redis.io/) with automatic expiry (TTL).

8. **Subprocess restart on crash** — if an R subprocess crashes, the SSE connection to the user drops and the session becomes unusable. The proxy could detect the crash and automatically re-spawn the subprocess for reconnect attempts.

9. **Memory-only credential lifetime** — credentials are stored in plain-text Python dicts. For advanced deployments, consider encrypting them at rest with a server-side key.

10. **Graceful shutdown** — when the container stops, active R subprocesses are killed immediately (`process.kill()`). A 5-second grace period with `process.terminate()` followed by `process.wait(timeout=5)` would be cleaner.

---

## Dependencies

| Component | Repository | Role |
|---|---|---|
| [elabR / elabrmcp](https://github.com/MarvinLuepke/elabR) | External | elabFTW R API client + MCP server |
| [datatagger-mcp](https://github.com/harrytyp/datatagger-mcp) | External | DataTagger MCP server |
| [ellmer](https://cran.r-project.org/package=ellmer) | CRAN | R MCP client library |
| [mcptools](https://cran.r-project.org/package=mcptools) | CRAN | R MCP transport layer |
| [FastAPI](https://fastapi.tiangolo.com) | PyPI | Python web framework (elabmcp-proxy) |
| [Caddy](https://caddyserver.com) | External | TLS reverse proxy |
| [Docker](https://www.docker.com) | External | Container runtime |
| [MCP Protocol](https://modelcontextprotocol.io/) | Specification | Model Context Protocol |

---

## License

This project is licensed under the [MIT License](LICENSE). The dependency repos ([elabR](https://github.com/MarvinLuepke/elabR), [datatagger-mcp](https://github.com/harrytyp/datatagger-mcp)) are governed by their respective licenses.