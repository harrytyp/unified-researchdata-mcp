# elabFTW Plugin Installation

This guide covers adding elabFTW integration to an existing NOMAD Oasis
(installed via `nomad-distro-template`). See `01-oasis-deployment.md` first
if the Oasis isn't running yet.

---

## Architecture

The elabFTW integration involves two components:

| Component | Source | License |
|-----------|--------|---------|
| **Base plugin** (`nomad-external-eln-integrations`) | [FAIRmat-NFDI](https://github.com/FAIRmat-NFDI/nomad-external-eln-integrations) | Apache 2.0 |
| **Custom linker** (`plugins/elabftw_linker/`) | This repo (`econversion-nomad`) | MIT |

The base plugin provides:
- `ElabftwProject` ELN schema — online API sync (one entry at a time)
- `ELabFTWParser` — offline .eln file parsing (batch import)

The custom linker adds:
- `ElabftwLinkedEntry` — multiple experiment refs per entry
- Auto cross-reference resolution during normalization
- Standalone batch sync CLI

---

## Step 1: Add Dependency to pyproject.toml

On the Oasis server:

```bash
cd ~/nomad-distro-template
```

Edit `pyproject.toml` to add the FAIRmat plugin to the `plugins` list:

```toml
[project.optional-dependencies]
plugins = [
    "nomad-north-jupyter>=0.2.5",
    "nomad-external-eln-integrations @ git+https://github.com/FAIRmat-NFDI/nomad-external-eln-integrations.git",
]
```

The plugin is **not on PyPI** — only on GitHub. The `@ git+https` syntax
tells `uv` to clone it directly. It brings in these transitive dependencies:
`nomad-openbis`, `lxml-html-clean`, `texttable`.

---

## Step 2: Regenerate uv.lock

The Docker build uses `uv` with `UV_FROZEN=1`, which reads from
`uv.lock` — NOT from `pyproject.toml`. The lock file must be in sync.

```bash
# Install uv temporarily
python3 -m venv /tmp/uv_venv
/tmp/uv_venv/bin/pip install uv

# Regenerate lock file
cd ~/nomad-distro-template
/tmp/uv_venv/bin/uv lock

# Verify
grep "nomad-external-eln-integrations" uv.lock
```

**Hiccup:** `uv lock --extra plugins` doesn't work in newer uv.
Just run `uv lock` (no flags) — it resolves all dependencies.

---

## Step 3: Build Custom Docker Image

The production image `ghcr.io/fairmat-nfdi/nomad-distro-template:main`
cannot be modified. Build a custom image:

```bash
cd ~/nomad-distro-template
DOCKER_BUILDKIT=1 docker build --target final -t nomad-distro-template:with-elabftw .
```

**Hiccup 1:** BuildKit is required. Without `DOCKER_BUILDKIT=1`:
```
the --mount option requires BuildKit
```

**Hiccup 2:** Takes 3-5 minutes on a small VM. Normal.

**Hiccup 3:** `docker compose build app` returns "No services to build"
because the `app` service has no `build:` section — use `docker build` directly.

---

## Step 4: Update docker-compose.yaml

### Change images

```yaml
app:
    image: nomad-distro-template:with-elabftw        # was ghcr.io/...
    # ... rest unchanged

north:
    image: nomad-distro-template:with-elabftw

worker:
    image: nomad-distro-template:with-elabftw
```

### Add volume mount for custom linker

```yaml
app:
    volumes:
      - ./.volumes/fs:/app/.volumes/fs
      - ./plugins:/app/plugins    # ← add this
    environment:
      PYTHONPATH: /app/plugins    # ← add this
```

### Add PYTHONPATH environment variable

```yaml
app:
    environment:
      PYTHONPATH: /app/plugins
      # ... existing env vars
```

---

## Step 5: Deploy Custom Linker

Clone this repo and copy the plugin:

```bash
cd ~
git clone https://github.com/harrytyp/econversion-nomad.git
cp -r econversion-nomad/plugins/elabftw_linker ~/nomad-distro-template/plugins/
```

**Note:** The directory must be named `elabftw_linker` (underscore), not
`elabftw-linker` (hyphen). Python packages use underscores.

---

## Step 6: Restart & Verify

```bash
cd ~/nomad-distro-template
docker compose up -d app north worker
docker exec nomad_oasis_proxy nginx -s reload

# Verify custom linker is importable
docker exec nomad_oasis_app python3 -c "import elabftw_linker; print('OK')"

# Verify base plugin is importable
docker exec nomad_oasis_app python3 -c \
  "import nomad_external_eln_integrations; print('OK')"
```

Check the NOMAD About page (`/nomad-oasis/gui/about/information`):

| Field | Should show |
|-------|-------------|
| plugin packages | `nomad_external_eln_integrations, nomad_north_jupyter` |
| parsers | `...elabftw_parser_entry_point` |
| schema packages | `...elabftw_schema` |

---

## Files Changed on the Oasis Server

| File | Change |
|------|--------|
| `pyproject.toml` | Added git dependency |
| `uv.lock` | Regenerated |
| `docker-compose.yaml` | Image tags, volume mount, PYTHONPATH |
| `plugins/elabftw_linker/*` | New directory (from this repo) |

---

## Rollback

```bash
cd ~/nomad-distro-template
git checkout docker-compose.yaml pyproject.toml uv.lock
docker compose pull app north worker
docker compose up -d app north worker
docker exec nomad_oasis_proxy nginx -s reload
```

---

## Integration Methods (What Each Does)

### Online API Sync — `ElabftwProject` schema (FAIRmat)

1. Create ELN entry → select **"ElabFTW Project Import"**
2. Fill in `project_url` + `api_key`
3. Toggle `Sync_Project` → Save
4. NOMAD calls `GET /api/v2/experiments/{id}?format=json&json=true`
5. Maps response to NOMAD schema via JMESPath
6. API key is cleared after sync (not persisted)

### Offline Parse — `ELabFTWParser` (FAIRmat)

1. Export experiment from elabFTW as **ELN Archive (.eln)**
2. Upload to NOMAD via PUBLISH → Uploads
3. Parser auto-detects RO-Crate format
4. Creates separate entries per experiment with files and metadata
5. Sets `metadata.external_id` for cross-referencing

### Dynamic Linking — `ElabftwLinkedEntry` schema (Custom)

1. Create ELN entry → select schema
2. Add multiple elabFTW experiment IDs
3. Set API key + toggle sync
4. Fetches titles, sets sync status, timestamps
5. Searches NOMAD for other entries with same `external_id`
6. Populates `linked_nomad_entry_id` with cross-references

### Batch Sync — `sync.py` (Custom)

```bash
docker exec nomad_oasis_app python3 /app/plugins/elabftw_linker/sync.py \
    --api-url https://your-instance/api/v2 \
    --api-key 72-xxx
```

Scans all NOMAD entries with `external_id`, fetches latest from elabFTW.
