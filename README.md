# Unified Research Data MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2026--07--28-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![R](https://img.shields.io/badge/R-4.4.2-276DC3?logo=r&logoColor=white)](https://r-project.org)

Host three MCP servers — **[datatagger-mcp](https://github.com/harrytyp/datatagger-mcp)**, **[elabrmcp](https://github.com/MarvinLuepke/elabR/tree/main/mcp/elabrmcp)** (elabFTW) and **[nomad-oasis-mcp](https://github.com/e-conversion/nomad-oasis-mcp)** (NOMAD) — behind a single [Caddy](https://caddyserver.com/) reverse proxy. Each takes the caller's own credentials; the NOMAD server additionally ships a read-only deployment key so a demo account is connected without registering anything.

> **Users register their own credentials via a web page.** The one exception is the NOMAD server's read-only deployment key (`NOMAD_MCP_DEFAULT_PAT`), which serves callers that never register. It is read-only, optional, and the only shared token in `.env`.

| MCP Server | Backend | Auth Mechanism |
|---|---|---|
| **datatagger-mcp** | [Python / FastMCP](https://github.com/modelcontextprotocol/python-sdk) | `/register` → HMAC-signed JWT (no server storage) |
| **elabrmcp** (elabFTW) | [R / ellmer](https://cran.r-project.org/package=ellmer) + [mcptools](https://cran.r-project.org/package=mcptools) | **elabmcp-proxy** → per-user R subprocess, JWT tokens |
| **nomad-oasis-mcp** (NOMAD) | [Python / MCP SDK](https://github.com/e-conversion/nomad-oasis-mcp) | `/register` → HMAC-signed JWT, or the deployment's read-only key |

### Web GUIs

| Service | Type | Access | Source |
|---------|------|--------|--------|
| **Atlas** (e-converse) | Chat assistant over the cluster's sources, including NOMAD | `econverse.e-conversion.de` — the application's own sign-in | deployment [e-conversion/atlas](https://gitlab.lrz.de/e-conversion/atlas), software [cluster-research-assist](https://github.com/e-conversion/cluster-research-assist) |
| **elab App** | elabFTW companion GUI | `elab-app.researchmcp.duckdns.org` | [ffelsen/elab_app](https://github.com/ffelsen/elab_app) |
| **Proespm** | Scientific data reports | `proespm.researchmcp.duckdns.org` | [matkrin/proespm-py3](https://github.com/matkrin/proespm-py3) |



---

## Architecture

```text
                     ┌────────────┐
                     │   Caddy    │  TLS, one entry point for every host
                     └──────┬─────┘
        ┌───────────────┬───┴────────┬───────────────┬──────────────┐
        ▼               ▼            ▼               ▼              ▼
      /dt             /el          /nm        /nomad-oasis/*   econverse host
  datatagger-     elabmcp-     nomad-mcp      NOMAD Oasis      cra:8501
  proxy:8000      proxy:8081     :8000        (nginx → app)    (atlas)
        │               │            │
        ▼               ▼            ▼
   DataTagger      Rscript per    NOMAD API, read-only: the caller's own
   API             session        PAT, or the deployment's read-only key
```

**elabR source code is never modified.** The [elabmcp-proxy](./elabmcp-proxy) spawns the unmodified `elabrmcp::elabr_mcp_server(type='stdio')` with each user's credentials injected as environment variables. You can `git pull` [elabR](https://github.com/MarvinLuepke/elabR) independently.



## Atlas (e-converse)

The cluster's chat assistant, served at <https://econverse.e-conversion.de>. It
answers over the sources a user connects: elabFTW, DataTagger and NOMAD, each
through its MCP server.

The application is public and carries no cluster-specific code
([cluster-research-assist](https://github.com/e-conversion/cluster-research-assist)).
Everything that makes it *this* deployment — configuration, branding, the
library bundle — lives in the private
[atlas](https://gitlab.lrz.de/e-conversion/atlas) repository, which also owns the
Caddy host block for `econverse.e-conversion.de`. This stack does not copy that
block; it imports it (see [Caddy Configuration](#caddy-configuration)).

---

---

## Quick Start

### 1. Clone repos

```bash
git clone https://github.com/harrytyp/unified-researchdata-mcp.git
cd unified-researchdata-mcp

# Registered submodules: datatagger-mcp, elabR, nomad-mcp
git submodule update --init

# Web apps, which are plain checkouts rather than submodules
git clone https://github.com/ffelsen/elab_app.git
git clone https://github.com/matkrin/proespm-py3.git
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
| `datatagger-proxy` | [Python](https://python.org) / [FastMCP](https://github.com/modelcontextprotocol/python-sdk) | [DataTagger](https://github.com/harrytyp/datatagger-mcp) MCP server |
| `elabmcp-proxy` | [Python](https://python.org) / [FastAPI](https://fastapi.tiangolo.com) + [R](https://r-project.org) / [ellmer](https://cran.r-project.org/package=ellmer) | elabFTW auth-proxy + per-user R subprocesses |
| `nomad-mcp` | [Python](https://python.org) / [MCP SDK](https://github.com/e-conversion/nomad-oasis-mcp) | NOMAD MCP server, read-only |
| `caddy` | [Caddy](https://caddyserver.com) | TLS termination & reverse proxy |
| `elabftw` + `elab-mysql` | [elabFTW](https://www.elabftw.net) | the ELN itself |
| `elab-app`, `proespm-app` | Streamlit | companion GUIs |

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

### Running tests

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
| Admin-managed secrets | ⚠️ | one: the NOMAD server's read-only deployment key (`NOMAD_MCP_DEFAULT_PAT`) |
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
| [nomad-oasis-mcp](https://github.com/e-conversion/nomad-oasis-mcp) | External | NOMAD MCP server (read-only) |
| [cluster-research-assist](https://github.com/e-conversion/cluster-research-assist) | External | the chat assistant (Atlas) |
| [elab_app](https://github.com/ffelsen/elab_app) | External | elabFTW companion web app |
| [proespm-py3](https://github.com/matkrin/proespm-py3) | External | Scientific data reports web app |
| [ellmer](https://cran.r-project.org/package=ellmer) | CRAN | R MCP client library |
| [mcptools](https://cran.r-project.org/package=mcptools) | CRAN | R MCP transport layer |
| [FastAPI](https://fastapi.tiangolo.com) | PyPI | Python web framework (elabmcp-proxy) |
| [Caddy](https://caddyserver.com) | External | TLS reverse proxy |
| [Docker](https://www.docker.com) | External | Container runtime |
| [MCP Protocol](https://modelcontextprotocol.io/) | Specification | Model Context Protocol |

---



---

## Updating

### Update the main repo

```bash
git pull
docker compose up -d --build
```

This rebuilds all images with the latest code and restarts containers.

### Update a single submodule

```bash
git pull                          # new submodule pointer
git submodule update --init <name>  # fetch the new code
docker compose up -d --build <name> # rebuild + restart that one container
```

Example for elabR:
```bash
git pull
git submodule update --init elabR
docker compose up -d --build elabmcp-proxy
```

Registered submodules live in [`.gitmodules`](.gitmodules):
- `datatagger-mcp` → `harrytyp/datatagger-mcp`
- `elabR` → `MarvinLuepke/elabR`
- `nomad-mcp` → `e-conversion/nomad-oasis-mcp` (HTTPS, so it clones without a key)

## License

This project is licensed under the [MIT License](LICENSE). The dependency repos ([elabR](https://github.com/MarvinLuepke/elabR), [datatagger-mcp](https://github.com/harrytyp/datatagger-mcp)) are governed by their respective licenses.