# Infrastructure: Server, Docker, Reverse Proxy, MCP Services

## Server Overview

| Property | Value |
|----------|-------|
| Hostname | researchmcp.duckdns.org |
| OS | Debian 12 (Bookworm) |
| CPU | (shared) |
| RAM | 3.8 GiB total (~1 GiB free after stack) |
| Disk | ~99 GiB (45 GiB used) |
| Docker | 20.10.24 |
| SSH User | debian |

## Docker Compose Stack

All services run under a single docker-compose.yml at:
`/home/debian/unified-researchdata-mcp/docker-compose.yml`

```
unified-researchdata-mcp/
├── docker-compose.yml          # All services
├── Caddyfile                    # Reverse proxy routes
├── elab-app/
│   └── Dockerfile               # elab-app Streamlit container
├── elabmcp-proxy/               # elabFTW MCP proxy (Python + R)
├── datatagger-mcp/              # DataTagger MCP proxy
├── web/                         # Landing page static files
└── caddy_data/                  # Caddy TLS certificates (Docker volume)
```

## Services

### Caddy (Reverse Proxy)
- **Image**: caddy:2
- **Ports**: 80 (HTTP), 443 (HTTPS)
- **Memory**: 128 MB
- Auto-TLS via Let's Encrypt for `researchmcp.duckdns.org`
- ISRG Root X1 appended to TLS chain for Windows Python client compatibility

#### Routing Rules

| Subdomain / Path | Target | Service |
|---|---|---|
| `researchmcp.duckdns.org/dt/*` | `datatagger-mcp:8000` | DataTagger MCP |
| `researchmcp.duckdns.org/el/*` | `elabmcp-proxy:8081` | elabFTW MCP |
| `researchmcp.duckdns.org/nomad-oasis/*` | `proxy:80` | NOMAD Oasis (via NOMAD's nginx) |
| `elab-app.researchmcp.duckdns.org` | `elab-app:8501` | elab-app Streamlit |
| `researchmcp.duckdns.org/` | File server | Landing page |

### elabFTW MCP Proxy
- **Image**: Built from `elabmcp-proxy/Dockerfile`
- **Transport**: stdio (R subprocess), HTTP proxy frontend
- **R version**: 4.4.2 (rocker/r-ver base)
- **Memory**: 2 GB limit
- **Sessions**: Max 3 concurrent, 128 MB per session
- **Tools**: 22 MCP tools (experiment CRUD, item CRUD, templates, links, etc.)

The MCP server authentication uses per-request credential injection:
- `HTTP_X_ELABFTW_API_KEY` header
- `HTTP_X_ELABFTW_BASE_URL` header

Users register at: `https://researchmcp.duckdns.org/el/register`

### DataTagger MCP Proxy
- **Memory**: 512 MB
- MCP endpoint at: `https://researchmcp.duckdns.org/dt/mcp?token=...`
- Users register at: `https://researchmcp.duckdns.org/dt/register`

### elab-app (Streamlit Logger)
**Separate documentation**: [04-elab-app.md](04-elab-app.md)

- **Image**: Built from `elab-app/Dockerfile`
- **Tech**: Python 3.13 + Streamlit 1.57
- **Port**: 8501 (internal)
- **Memory**: 256 MB
- **Volume**: `elab_app_data` → `/root/.config/elab_app` (persists user API keys + templates)
- **Default host**: `https://elntest.ub.tum.de/api/v2`

## MCP Client Configuration

All MCP clients (Hermes Agent, Claude Desktop, Cursor, etc.) connect via the
Streamable HTTP transport:

```yaml
mcp_servers:
  elabmcp:
    url: "https://researchmcp.duckdns.org/el/mcp?token=<register-me>"
    timeout: 120
  datatagger:
    url: "https://researchmcp.duckdns.org/dt/mcp?token=<register-me>"
    timeout: 120
```

Tokens expire after 30 minutes. Users re-register at the `/register` endpoint
to obtain a fresh token. The registration stores the elabFTW API key server-side
in the proxy's session store (ephemeral — lost on container restart).

## NOMAD Oasis

- **Running alongside** the MCP services on the same server
- Uses the official `ghcr.io/fairmat-nfdi/nomad-distro-template:main` image
- NOMAD's nginx proxy runs on port 8080/8443
- Caddy routes `/nomad-oasis/*` to NOMAD's nginx proxy
- 6 worker containers (template workers)
- Elasticsearch, MongoDB, PostgreSQL, Temporal as backing services

## Landing Page

The landing page at `https://researchmcp.duckdns.org/` shows three service cards:
- **DataTagger** — register for a key, copy URL, paste into agent
- **elabFTW** — register for a key, copy URL, paste into agent
- **NOMAD OASIS** — link to the Oasis GUI

Plus a 3-step "How to Use" guide explaining the workflow.
