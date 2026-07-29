# elabFTW-NOMAD Integration — Installation & Setup

## Overview

This document details the installation of the **nomad-external-eln-integrations** plugin
on a NOMAD Oasis (v1.4.2) and the custom **elabFTW Dynamic Linker** extension.

Two integration methods are available:

| Method | Description | Use Case |
|--------|-------------|----------|
| Offline (batch) | Export .eln from elabFTW, upload to NOMAD | One-time imports |
| Online (API sync) | NOMAD fetches data live from elabFTW API | Ongoing sync |

---

## Architecture

```
┌──────────────────────────────┐
│       researchmcp.duckdns.org  │
│  ┌────────────────────────┐  │
│  │   Caddy (reverse proxy) │  │  HTTPS → /nomad-oasis/*
│  └────────┬───────────────┘  │
│           │                  │
│  ┌────────▼───────────────┐  │
│  │   nginx (proxy:80)     │  │  Serves static + proxies to app:8000
│  └────────┬───────────────┘  │
│           │                  │
│  ┌────────▼───────────────┐  │
│  │   app:8000 (NOMAD)     │  │  Custom image with plugin
│  │   + plugins/ volume    │  │  ⤷ nomad-external-eln-integrations
│  └────────────────────────┘  │  ⤷ elabftw-linker (custom)
│                              │
│  elabFTW instance (hosted)   │  API accessible from app container
└──────────────────────────────┘
```

---

## Step 1: Add Plugin to pyproject.toml

**File:** `~/nomad-distro-template/pyproject.toml`

```toml
[project.optional-dependencies]
plugins = [
    "nomad-north-jupyter>=0.2.5",
    "nomad-external-eln-integrations @ git+https://github.com/FAIRmat-NFDI/nomad-external-eln-integrations.git",
]
```

**Why `@ git+https`:** The package is NOT on PyPI or the MPCDF registry.
It lives at `github.com/FAIRmat-NFDI/nomad-external-eln-integrations`.

---

## Step 2: Regenerate uv.lock

The NOMAD Docker build uses `uv` with `UV_FROZEN=1`, which requires the lock
file to be in sync with pyproject.toml.

**On the server:**

```bash
# Install uv temporarily
python3 -m venv /tmp/uv_venv
/tmp/uv_venv/bin/pip install uv

# Regenerate lock file in the project directory
cd ~/nomad-distro-template
/tmp/uv_venv/bin/uv lock

# Verify the plugin is resolved
grep -A2 'nomad-external-eln-integrations' uv.lock | head -10
```

**Expected output:**
```
name = "nomad-external-eln-integrations"
version = "0.1.0"
```

**Hiccup:** `uv lock --extra plugins` doesn't work in newer uv versions.
Just run `uv lock` without flags — it resolves ALL dependencies.

---

## Step 3: Build Custom Docker Image

**Important:** The production `ghcr.io/fairmat-nfdi/nomad-distro-template:main`
image cannot be modified. You must build a custom image.

```bash
cd ~/nomad-distro-template
DOCKER_BUILDKIT=1 docker build --target final -t nomad-distro-template:with-elabftw .
```

The Dockerfile uses multi-stage builds:
1. `builder` — installs Python deps via `uv sync --extra plugins`
2. `docs` — clones nomad-docs repo and builds documentation
3. `final` — copies venv + docs into minimal runtime image

**Hiccup 1:** BuildKit is required (the Dockerfile uses `--mount=type=bind`).
Without `DOCKER_BUILDKIT=1`, you get:
```
the --mount option requires BuildKit
```

**Hiccup 2:** The build takes ~3 minutes on a small VM (3.8GB RAM, 2 CPUs).
Most time is spent in `uv sync` (resolving 229 packages) and `mkdocs build`.

---

## Step 4: Update docker-compose.yaml

Change `app`, `north`, and `worker` services to use the custom image:

```yaml
app:
    image: nomad-distro-template:with-elabftw       # was: ghcr.io/...
    restart: unless-stopped
    # ... rest unchanged

north:
    image: nomad-distro-template:with-elabftw       # was: ghcr.io/...
    restart: unless-stopped

worker:
    image: nomad-distro-template:with-elabftw       # was: ghcr.io/...
    restart: unless-stopped
```

Also add a volume mount for the custom dynamic-linker scripts:

```yaml
app:
    volumes:
      - ./plugins:/app/plugins
```

---

## Step 5: Restart Containers

```bash
cd ~/nomad-distro-template
docker compose up -d app north worker
```

The proxy (nginx) caches the upstream app IP at startup. After restarting
the app container:

```bash
# Reload nginx to pick up the new upstream IP
docker exec nomad_oasis_proxy nginx -s reload
```

---

## Step 6: Verify Plugin Is Loaded

Check the NOMAD About page:

```
https://researchmcp.duckdns.org/nomad-oasis/gui/about/information
```

Under **"About this distribution"**, you should see:

| Field | Value |
|-------|-------|
| plugin packages | `nomad_external_eln_integrations, nomad_north_jupyter` |
| parsers | `...elabftw_parser_entry_point` |
| schema packages | `...elabftw_schema`, `...labfolder_schema`, `...openbis_schema` |
| example uploads | `...elabftwexample` |

You can also verify from CLI:

```bash
docker exec nomad_oasis_app python3 -c \
  "import nomad_external_eln_integrations; print('OK')"
```

---

## Step 7: Install Custom Dynamic Linker Plugin

The base plugin provides the `ElabftwProject` schema (one-shot API sync).
The **elabFTW Dynamic Linker** extends this with:

- `ElabftwLinkedEntry` schema — stores multiple experiment refs per entry
- Automatic cross-reference resolution during normalization
- Standalone batch sync script

**Files** (in `~/nomad-distro-template/plugins/elabftw-linker/`):

| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `schema.py` | `ElabftwLinkedEntry` ELN schema |
| `normalizer.py` | Normalizer hook for auto-resolving links |
| `sync.py` | Standalone batch sync CLI |

---

## Files Changed Summary

| File | Change |
|------|--------|
| `pyproject.toml` | Added git dependency to `plugins` list |
| `uv.lock` | Regenerated (4 new packages: nomad-external-eln-integrations, nomad-openbis, lxml-html-clean, texttable) |
| `docker-compose.yaml` | Image tag changed for app, north, worker; volume mount for plugins |
| `Dockerfile` | Unchanged (base image reused with build args) |
| `configs/nomad.yaml` | Unchanged (auto-discovers plugins via entry points) |

---

## Rollback

To revert to the stock NOMAD image:

```bash
cd ~/nomad-distro-template
git checkout docker-compose.yaml pyproject.toml uv.lock
docker compose pull app north worker
docker compose up -d app north worker
docker exec nomad_oasis_proxy nginx -s reload
```
