# elabFTW-NOMAD User Guide

## Setting Up elabFTW-NOMAD Links

This guide explains how users can link elabFTW experiments with NOMAD entries
using both the built-in `ElabftwProject` schema and the custom `ElabftwLinkedEntry` schema.

---

## Method A (Recommended): ElabftwSettings + ElabftwLinkedEntry

Best for: users who want to set their API key once and never type it again.

### Step 1: One-time Setup — Create your Settings

1. **PUBLISH → Uploads → CREATE A NEW UPLOAD → CREATE FROM SCHEMA**
2. Select **"elabFTW Settings"**
3. Name it exactly **"elabFTW Settings"** (the normalizer finds it by name)
4. Fill in:
   | Field | Value |
   |-------|-------|
   | `api_key` | Your personal elabFTW token from `My Account → API tokens` |
   | `api_base_url` | `https://elntest.ub.tum.de/api/v2` (default) |
5. Save

Your key is stored in your own private upload. Only you can see it.

### Step 2: Link an elabFTW Experiment/Item to NOMAD

1. **CREATE A NEW UPLOAD → CREATE FROM SCHEMA**
2. Select **"elabFTW Linked Entry"**
3. Give it a name
4. Under **config**:
   | Field | What to put |
   |-------|-------------|
   | `entity_type` | `experiment` (default) or `item` for database resources |
   | `sync_now` | Toggle to **true** |
   | `write_link_back` | Keep **true** to write NOMAD URL into elabFTW |
5. Under **experiments**, click + ADD and fill:
   | Field | What to put |
   |-------|-------------|
   | `elabftw_id` | The elabFTW ID number (e.g. `2339` for experiment, `1354` for item) |
6. Save

The normalizer:
- Reads your API key from your Settings entry
- Fetches the experiment/item title from elabFTW
- Writes a `NOMAD URL` back into elabFTW's extra fields
- Clears the API key from the entry data

### Verify

In elabFTW, open the linked experiment/item. Under **Extra fields**, you should see:
```
NOMAD URL: https://researchmcp.duckdns.org/...
NOMAD Synced: 2026-05-22T...
```

---

## Method B: Quick Sync (ElabftwProject — FAIRmat built-in)

Best for: one-off sync without setting up a personal config.

### Steps

1. Go to **PUBLISH → Uploads** and create a new upload
2. Click **CREATE FROM SCHEMA**
3. Select **"ElabFTW Project Import"** from the schema list
4. Name your entry (e.g. "elabFTW: Synthesis Run #42")
5. Click **CREATE**

Now fill in the configuration fields:

| Field | Description | Example |
|-------|-------------|---------|
| `project_url` | Full URL of the elabFTW experiment | `https://demo.elabftw.net/experiments.php?mode=view&id=42` |
| `api_key` | Your elabFTW API token | `72-xxxxxxxx...` |
| `api_url` | (Optional) Override API base URL | `https://custom-api/v2` |
| `Sync_Project` | **Toggle to `true` to trigger sync** | ✓ |

6. Toggle **Sync_Project** to `true`
7. Click the **Save** icon (💾) in the top-right
8. NOMAD fetches data from elabFTW and populates the entry

### What Gets Synced

| elabFTW field | NOMAD section |
|---------------|---------------|
| Title, author | Entry metadata |
| Body (HTML) | `Experiment Data → Description` |
| Tags/keywords | `Experiment Data → Tags` |
| Extra fields | `Experiment Data → Extra Fields` |
| Steps | `Experiment Data → Steps` |
| File attachments | `Experiment Files` |
| Status | Entry status |
| Creation date | `Experiment Data → Created At` |

**Security:** The API key is cleared from the entry after sync completes.
It is NOT stored permanently.

---

## Method B: Dynamic Linking (ElabftwLinkedEntry)

Best for: linking multiple experiments, automatic cross-referencing.

### Steps

1. Go to **PUBLISH → Uploads** and create a new upload
2. Click **CREATE FROM SCHEMA**
3. Select **"elabFTW Dynamic Link"** from the schema list
4. Name your entry (e.g. "My elabFTW Links")
5. Click **CREATE**

### Configuration

Under the **Config** subsection, fill in:

| Field | Description |
|-------|-------------|
| `api_base_url` | elabFTW API base URL (e.g. `https://demo.elabftw.net/api/v2`) |
| `api_key` | Your elabFTW API token (cleared after sync) |
| `sync_all_references` | Toggle to `true` to sync all experiments at once |
| `auto_resolve_links` | Keep `true` to auto-discover linked NOMAD entries |

### Adding Experiments

Under the **Experiments** subsection, click **+ ADD** to add each elabFTW
experiment you want to link:

| Field | Description |
|-------|-------------|
| `elabftw_id` | The elabFTW experiment ID (the number after `?id=` in the URL) |
| `elabftw_url` | (Optional) Full URL for reference |

### Syncing

1. Set **Sync all references** to `true`
2. Save the entry
3. NOMAD fetches data for ALL added experiments:
   - Populates `elabftw_title` (fetched from API)
   - Sets `sync_status` to `synced` (or `error`)
   - Records `last_synced` timestamp
4. If `auto_resolve_links` is `true`, NOMAD also:
   - Searches for other entries with the same elabFTW IDs
   - Populates `linked_nomad_entry_id` with internal references
5. The API key is cleared after sync

---

## Method C: Batch Sync (CLI)

Best for: periodic automated sync of ALL elabFTW-linked entries.

### Usage

```bash
docker exec nomad_oasis_app python3 /app/plugins/elabftw-linker/sync.py \
    --api-url https://your-elabftw-instance/api/v2 \
    --api-key 72-your-api-key
```

### What It Does

1. Queries the NOMAD API for all entries with `external_id` set
2. For each, fetches the latest data from elabFTW
3. Reports synced/error counts

### Automating with Cron

```bash
# Run every 6 hours
0 */6 * * * docker exec nomad_oasis_app python3 \
  /app/plugins/elabftw-linker/sync.py \
  --api-url https://your-elabftw-instance/api/v2 \
  --api-key 72-your-api-key \
  >> /var/log/elabftw-sync.log 2>&1
```

---

## Method D: Offline Batch Import

Best for: importing archived experiments that no longer need live updates.

1. In elabFTW, export experiment(s) as **ELN Archive (.eln)**
2. In NOMAD, **PUBLISH → Uploads → CREATE A NEW UPLOAD**
3. Upload the `.eln` file(s)
4. NOMAD auto-parses and creates entries for each experiment

No API credentials needed.

---

## Understanding Cross-References

### How Linking Works

When an entry has elabFTW references, the system:

1. **Sets `metadata.external_id`** on each parsed entry (from elabFTW URL)
2. **During normalization**, searches NOMAD for other entries with the same `external_id`
3. **Creates internal references** (`../uploads/{upload_id}/archive/{entry_id}#data`)
4. **Populates `linked_nomad_entry_id`** on the dynamic link entry

### Viewing Links

In the NOMAD GUI:

1. Open an entry that has elabFTW links
2. Go to the **DATA** tab
3. Under **Entry** → **data**, you'll see the elabFTW section
4. The `linked_nomad_entry_id` field shows which other NOMAD entries
   reference the same elabFTW experiment

These appear as clickable links in the GUI.

---

## Schema Reference

### ElabftwExperimentRef

| Quantity | Type | Description |
|----------|------|-------------|
| `elabftw_id` | str | elabFTW experiment ID |
| `elabftw_url` | str | Full URL |
| `elabftw_title` | str | Title (fetched) |
| `sync_status` | str | pending/synced/error |
| `last_synced` | Datetime | Last sync timestamp |
| `linked_nomad_entry_id` | str[*] | Linked NOMAD entries |

### ElabftwDynamicLinkConfig

| Quantity | Type | Default | Description |
|----------|------|---------|-------------|
| `api_base_url` | str | — | elabFTW API base URL |
| `api_key` | str | — | API token (cleared after sync) |
| `sync_all_references` | bool | false | Trigger sync on save |
| `auto_resolve_links` | bool | true | Auto-discover cross-refs |

---

## Troubleshooting

### "No API key configured" warning

You need to set the API key in the entry's config section before syncing.

### Sync status stays "error"

1. Check the elabFTW API is reachable from the NOMAD server
2. Verify the API token is valid (not expired/revoked)
3. Check that the experiment ID exists in elabFTW
4. Look at NOMAD app logs: `docker logs nomad_oasis_app | grep elabFTW`

### "Could not resolve links" warning

This is non-critical. It means the normalizer couldn't search for cross-references,
which is expected if:
- The entry hasn't been published yet
- The search index hasn't updated
- The user session doesn't have search permissions

### Entry doesn't appear in GUI after sync

The sync populates the entry's data model, but the GUI may need a page refresh.
Try navigating away and back, or check the entry's JSON directly via the API:

```bash
curl -s http://localhost:8000/api/v1/uploads/{upload_id}/archive/{entry_id}
```
