# Three-Way Sync: elabFTW ↔ NOMAD

## Architecture

Everything runs inside the NOMAD Oasis server. The integration has two parts:

### 1. NOMAD Normalizer (auto, on every save)

```
Entry saved (any schema)
  │
  ▼
Normalizer runs ──► Detects elabFTW experiment ID
  │                   │
  │   Has ID? ───────► Fetches experiment from elabFTW API
  │   │                 ├── Populates entry title from elabFTW
  │   │                 └── Writes NOMAD URL back to elabFTW extra_fields
  │   │
  │   Auto-create? ───► Creates new elabFTW experiment
  │   │                 ├── Sets external_id on NOMAD entry
  │   │                 └── Writes NOMAD URL back to elabFTW
  │   │
  │   Clear API key
  │
  Done
```

### 2. Webhook (for "Send to NOMAD" from elabFTW)

```
elabFTW experiment
  │
  │ User clicks "Send to NOMAD" link
  ▼
Webhook endpoint ──► Fetches experiment data
  │                   │
  │                   ├── Creates NOMAD upload + entry
  │                   │     (with external_id = elabFTW ID)
  │                   │
  │                   └── Writes NOMAD URL → elabFTW extra_fields
  │
  ▼
User lands on NOMAD entry page
```

## File Layout

```
plugins/
├── elabftw_linker/              ← Legacy (simple cross-referencing)
├── three_way_sync/              ← Active bidirectional bridge
│   ├── __init__.py              Package init
│   ├── entrypoint.py            BridgeEntryPoint for NOMAD GUI registration
│   ├── schema.py                ELN schemas (ElabftwLinkedEntry, ElabftwMachineUpload, ElabftwSettings)
│   ├── normalizer.py            NOMAD normalizer (auto-link on save)
│   ├── webhook.py               Flask webhook + CLI importer
│   ├── config.yaml.template     User fills in their own API tokens
│   ├── pyproject.toml           Entry points for NOMAD discovery
│   └── configs/                 Per-user config files (legacy, use Settings entry instead)
├── startup.sh                   ← Copies egg-info to site-packages on boot
└── three_way_nomad_bridge.egg-info/  ← NOMAD plugin entry points
```

## Setup on Server

### 1. Copy plugin files

```bash
cd ~
git clone https://github.com/harrytyp/econversion-nomad.git
cp -r econversion-nomad/plugins/three_way_sync ~/nomad-distro-template/plugins/
cp -r econversion-nomad/plugins/three_way_nomad_bridge.egg-info ~/nomad-distro-template/plugins/
```

### 2. Create config (each user uses their own API tokens)

```bash
cp ~/nomad-distro-template/plugins/three_way_sync/config.yaml.template \
   ~/nomad-distro-template/plugins/three_way_sync/config.yaml
# Edit with YOUR API keys (not shared credentials)
```

### 3. Install Flask for webhook server

```bash
docker exec nomad_oasis_app pip install flask
```

### 4. Test

```bash
# Test import from CLI (inside container)
docker exec nomad_oasis_app python3 \
  /app/plugins/three_way_sync/webhook.py 42

# Test webhook
docker exec nomad_oasis_app python3 \
  /app/plugins/three_way_sync/webhook.py serve 8081
```

## Persistence (Docker Rebuild)

The plugin entry points are stored in `plugins/three_way_nomad_bridge.egg-info/`
(volume-mounted). For them to survive container recreation, two things are needed:

**Option A (current, survives restarts):** The `.pth` file in site-packages
tells Python to scan `/app/plugins` for egg-info at startup. This is set up
on the server and works across container restarts.

**Option B (for container recreation):** Override the NOMAD app command to
run `startup.sh` before starting NOMAD. This copies the egg-info to
site-packages:

```yaml
# In docker-compose.yaml, change the app command to:
command: bash /app/plugins/startup.sh
```

Then mount the script:
```yaml
volumes:
  - ./plugins/startup.sh:/app/plugins/startup.sh:ro
  - ./plugins/three_way_nomad_bridge.egg-info:/app/plugins/three_way_nomad_bridge.egg-info:ro
```

**Option C (most durable):** Rebuild the Docker image with the plugin as
a proper dependency (see `02-elabftw-plugin-install.md`).

## Adding "Send to NOMAD" to elabFTW

In elabFTW, create an **extra field** or **link** in your experiment template:

```
Send to NOMAD: https://researchmcp.duckdns.org/integrations/import/42
```

(Replace `42` with `{id}` if your template supports dynamic fields.)

When clicked, this imports the experiment into NOMAD and redirects the user
to the newly created entry page.

## Machine Uploads

When a machine uploads data to NOMAD:

```bash
curl -X POST http://localhost:8000/nomad-oasis/api/v1/uploads \
  -H "Authorization: Bearer YOUR_NOMAD_TOKEN" \
  -d '{"upload_name": "Sensor data 2026-05-21"}'

# Then create entry with ElabftwMachineUpload schema
curl -X POST http://localhost:8000/nomad-oasis/api/v1/uploads/{upload_id}/archive \
  -H "Authorization: Bearer YOUR_NOMAD_TOKEN" \
  -d '{
    "entry_name": "Sensor batch #42",
    "data": {
      "m_def": "three_way_sync.schema:ElabftwMachineUpload",
      "config": {
        "create_elabftw_experiment": true,
        "api_base_url": "https://elntest.ub.tum.de/api/v2",
        "api_key": "72-xxxx"
      }
    }
  }'
```

The normalizer auto-creates an elabFTW experiment and links back.

## Schema Reference

### ElabftwLinkedEntry

| Field | Type | Purpose |
|-------|------|---------|
| `title` | str | Entry title |
| `description` | RichText | Description |
| `config.api_base_url` | str | elabFTW API URL |
| `config.api_key` | password | API key (cleared after sync) |
| `config.sync_now` | bool | Toggle to fetch experiment data |
| `config.create_elabftw_experiment` | bool | Auto-create elabFTW experiment |
| `config.write_link_back` | bool | Write NOMAD URL → elabFTW |
| `experiments[].elabftw_id` | str | elabFTW experiment ID |
| `experiments[].elabftw_title` | str | Title (auto-fetched) |
| `experiments[].sync_status` | str | pending/synced/error |

### ElabftwMachineUpload

Same as `ElabftwLinkedEntry`, but intended for automated uploads.
`create_elabftw_experiment` defaults to `true` in normalizer logic.
