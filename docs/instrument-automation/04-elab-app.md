# elab-app: Streamlit elabFTW Logger

## Overview

[elab-app](https://github.com/ffelsen/elab_app) is a Streamlit-based app that
provides a simple chat-like interface for creating structured experiment entries
in elabFTW. It is deployed as a Docker container on the same server as the other
MCP services.

**URL**: https://elab-app.researchmcp.duckdns.org

## Deployment

### Dockerfile

Location: `/home/debian/unified-researchdata-mcp/elab-app/Dockerfile`

```dockerfile
FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y git
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN uv tool install git+https://github.com/ffelsen/elab_app
ENV PATH="/root/.local/bin:${PATH}"
RUN elab-app config set elab_host https://elntest.ub.tum.de/api/v2
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
EXPOSE 8501
CMD ["elab-app", "start"]
```

### Docker Compose Service

```yaml
elab-app:
  build:
    context: ./elab-app
  restart: unless-stopped
  expose:
    - "8501"
  mem_limit: 256m
  stop_grace_period: 10s
  volumes:
    - elab_app_data:/root/.config/elab_app
```

### Persistent Volume

`elab_app_data` is a named Docker volume mounted at `/root/.config/elab_app`
inside the container, which stores:

| Path | Content |
|------|---------|
| `keys/` | Encrypted per-user API key files (.enc, Fernet/PBKDF2) |
| `templates/` | YAML user-defined templates |
| `config.toml` | App configuration (elab_host) |

This volume persists across container restarts so users don't lose their
credentials.

### Reverse Proxy

Caddy routes `elab-app.researchmcp.duckdns.org` to the container:

```caddy
elab-app.researchmcp.duckdns.org {
    reverse_proxy elab-app:8501 {
        flush_interval -1
    }
}
```

## User Workflow

1. Open https://elab-app.researchmcp.duckdns.org
2. **First-time**: Enter initials → set PIN → paste elabFTW API key → "Set up"
3. **Returning**: Select initials → enter PIN → "Log in"
4. After login, the **Log** page opens with tabbed input:
   - **Chat**: Free-text natural language logging
   - **Template**: Structured input using YAML templates
   - **Voice**: Whisper-based transcription (optional install)
   - **CSV**: Bulk CSV upload
   - **Sketch**: Drawable canvas annotations

## Features

- Encrypted per-user API key store (Fernet/PBKDF2, PIN-protected)
- Auto-linking of referenced resources/experiments as database links
- Hashtag autocomplete (# for resources and experiments)
- Multi-team login with team selection dialog
- Automated log table merging and version tracking
- Failed-entry retry mechanism with red highlighting
- Version check against GitHub releases

## Updating

To update the container to a newer elab-app version:

```bash
docker compose build elab-app   # rebuilds with latest from GitHub
docker compose up -d elab-app   # restarts the service
```

The Dockerfile does `uv tool install git+https://github.com/ffelsen/elab_app`
at build time, so rebuilding pulls the latest version from the main branch.
