# Unified Research Data MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2025--03--26-blue)](https://modelcontextprotocol.io/)

Hosts **MCP servers** and **web GUI tools** for research data management behind a single [Caddy](https://caddyserver.com/) reverse proxy on `researchmcp.duckdns.org`.

## Services

### MCP Servers

| Service | Backend | Auth | Source |
|---------|---------|------|--------|
| **datatagger-mcp** | Python / FastMCP | `/register` → JWT | [harrytyp/datatagger-mcp](https://github.com/harrytyp/datatagger-mcp) |
| **elabmcp-proxy** (elabFTW) | Python / Starlette + R / ellmer | Per-user R subprocess, JWT tokens | [MarvinLuepke/elabR](https://github.com/MarvinLuepke/elabR/tree/main/mcp/elabrmcp) |

### Web GUIs

| Service | Type | Access | Source |
|---------|------|--------|--------|
| **eConversion Knowledge Assistant** | Streamlit chat (956 papers, 42 PIs) | `econversion.researchmcp.duckdns.org` — password-protected | [alexburg14/MCP_eConversion](https://github.com/alexburg14/MCP_eConversion) |
| **elab App** | elabFTW companion GUI | `elab-app.researchmcp.duckdns.org` | [ffelsen/elab_app](https://github.com/ffelsen/elab_app) |
| **Proespm** | Scientific data reports | `proespm.researchmcp.duckdns.org` | [matkrin/proespm-py3](https://github.com/matkrin/proespm-py3) |

## Architecture

```
                               ┌──────────────┐
                               │    Caddy     │
                               └──────┬───────┘
                                      │
            ┌─────────────┬───────────┼─────────────┬──────────────┐
            ▼             ▼           ▼             ▼              ▼
   ┌──────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ datatagger-  │ │ elabmcp-   │ │ econver- │ │ elab-app │ │proespm-  │
   │ mcp :8000    │ │ proxy:8081 │ │ sion:8501│ │  :8501   │ │ app:8501 │
   │ Python/MCP   │ │ Py+R/MCP   │ │ Streamlit│ │  Stream- │ │ Stream-  │
   └──────────────┘ └────────────┘ └──────────┘ │  lit     │ │ lit      │
                                                 └──────────┘ └──────────┘
```

## eConversion Knowledge Assistant

The eConversion Knowledge Assistant is a web-based chat interface for the e-conversion research cluster (TUM / LMU / FHI / MPI FKF). It provides:

- **956 publications** from `e-conversion.de/publikationen`
- **953 abstracts** (99.7% coverage) — 905 from EndNote library, 47 from OpenAlex, 1 from Semantic Scholar
- **42 PI profiles** with 2314 linked publications
- **Semantic search** via BGE-small embeddings (384-dim)
- **LLM-backed answers** via GWDG SAIA / Academic Cloud Chat AI endpoint

> The app code lives at **[alexburg14/MCP_eConversion](https://github.com/alexburg14/MCP_eConversion)**.
> Only the deployment infrastructure (Dockerfile, Caddy route, docker-compose entry) is in this repo.

**Access:** `https://econversion.researchmcp.duckdns.org` — HTTP Basic Auth required.

---

## Deployment

### Requirements

- Docker & docker-compose
- Git
- Domain with DNS pointing to your server

### Setup

```bash
git clone https://github.com/harrytyp/unified-researchdata-mcp.git
cd unified-researchdata-mcp

# Clone dependencies
git clone https://github.com/harrytyp/datatagger-mcp.git
git clone https://github.com/MarvinLuepke/elabR.git
git clone https://github.com/ffelsen/elab_app.git
git clone https://github.com/matkrin/proespm-py3.git
git clone https://github.com/alexburg14/MCP_eConversion.git econversion

# Copy and edit environment
cp .env.example .env

# Build and start
docker compose up -d --build
```
