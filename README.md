# Unified MCP Hosting — elabFTW + DataTagger

Hosts two MCP servers behind a single Caddy reverse proxy, each with per-user
**bring-your-own-API-key** registration:

| MCP Server | Backend | User Auth |
|------------|---------|-----------|
| **datatagger-mcp** | Python (FastMCP) | Built-in `/register` → session token |
| **elabrmcp** (elabFTW) | R (ellmer/mcptools) | **elabmcp-proxy** → spawns per-user R subprocess |

---

## Architecture

```
                               ┌──────────────┐
                               │    Caddy     │
                               └──────┬───────┘
                                      │
                         ┌────────────┼────────────┐
                         ▼            ▼            │
             ┌──────────────────┐ ┌──────────────────┐
             │  datatagger-mcp  │ │  elabmcp-proxy   │
             │  port 8000       │ │  port 8081       │
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

**elabR source code is never modified.** The proxy spawns the unmodified
`elabrmcp::elabr_mcp_server(type='stdio')` with each user's credentials
injected as environment variables. You can `git pull` elabR independently.

---

## Setup

### 1. Clone this repo and its dependencies

```bash
git clone <your-repo-url> unified-mcp
cd unified-mcp

# Clone the two MCP server repos alongside it
git clone https://github.com/harrytyp/datatagger-mcp.git
git clone https://github.com/MarvinLuepke/elabR.git
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:
```env
# DataTagger (optional — users can also register on the web page)
FDM_BASE_URL=https://datatagger.ub.tum.de
FDM_TOKEN=
```

### 3. Deploy

```bash
docker compose up -d --build
```

This builds three containers:
- **unified-mcp-datatagger-mcp** — DataTagger MCP server (Python)
- **unified-mcp-elabmcp-proxy** — elabFTW auth-proxy (R + Python)
- **unified-mcp-caddy** — reverse proxy (routes by subdomain)

---

## User Workflow

### DataTagger

```
1. User visits  https://datatagger.your-domain.com/register
2. Pastes personal FDM_TOKEN
3. Receives scoped URL:  https://datatagger.your-domain.com/mcp/?token=<uuid>
4. Registers URL in MCP client (Claude Desktop, etc.)
```

### elabFTW / elabrmcp

```
1. User visits  https://elab.your-domain.com/register
2. Pastes personal ELABFTW_BASE_URL + ELABFTW_API_KEY
3. Receives scoped URL:  https://elab.your-domain.com/mcp?token=<uuid>
4. Registers URL in MCP client
5. Proxy spawns a dedicated R subprocess with those credentials
6. After 30 min idle, process is killed and memory reclaimed
```

---

## Caddy Configuration

Edit `Caddyfile` and replace `your-domain.com` with your actual domain:

```
datatagger.your-domain.com { ... }
elab.your-domain.com       { ... }
```

For local testing without DNS, change the ports in `Caddyfile` to serve on
`localhost` and access them at `http://localhost:8080` / `http://localhost:8081`.

---

## elabmcp-proxy (auth-proxy for elabrmcp)

The key component that makes per-user registration work without modifying
elabR. Located in `elabmcp-proxy/`:

```
elabmcp-proxy/
├── Dockerfile              # Builds R + elabR + elabrmcp + Python proxy
├── requirements.txt
├── pyproject.toml
└── src/elabmcp_proxy/
    ├── __init__.py
    ├── __main__.py         # Entry point:  python3 -m elabmcp_proxy
    ├── app.py              # FastAPI app:  /register, GET/POST /mcp
    └── session.py          # RProcessHandle: spawns/kills R subprocesses
```

### How it works

1. **Registration** — user enters credentials → stored in memory with UUID token
2. **SSE connect** — first `GET /mcp?token=X` spawns
   `Rscript -e "elabrmcp::elabr_mcp_server(type='stdio')"` with
   `ELABFTW_BASE_URL` and `ELABFTW_API_KEY` set via environment
3. **Bridge** — proxy translates SSE events ↔ stdio JSON-RPC lines
4. **Isolation** — each user gets a separate R process, no shared state
5. **Cleanup** — processes are killed after 30 minutes of inactivity

---

## Components

| Directory | Source | Purpose |
|-----------|--------|---------|
| `elabR/` | [GitHub](https://github.com/MarvinLuepke/elabR) | elabFTW R API client + elabrmcp MCP server |
| `datatagger-mcp/` | [GitHub](https://github.com/harrytyp/datatagger-mcp) | DataTagger MCP server |
| `elabmcp-proxy/` | **this repo** | Multi-user auth-proxy wrapping elabrmcp |
| `docker-compose.yml` | **this repo** | Orchestration |
| `Caddyfile` | **this repo** | Reverse proxy routing |