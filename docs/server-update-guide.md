# Updating the NOMAD Server from GitHub — Quick Guide

How to pull the latest code from GitHub onto the server and restart the stack so
that plugin/schema changes take effect. Includes the common errors we have
encountered and how to fix them.

---

## 1. The big picture

- The **monorepo** on the server is at `~/unified-researchdata-mcp`.
- The **NOMAD stack** runs from `~/unified-researchdata-mcp/nomad/`
  (11 containers: app, 4×worker, north, proxy, temporal, elastic, mongo, postgresql).
- **Plugins live on the host** under `nomad/plugins/` and are **bind-mounted**
  into the container at `/app/plugins`. That means:
  - New/edited **plugin files are visible in the container immediately** after `git pull` —
    no image rebuild, no `docker build`, no `pip install`.
  - But NOMAD only **registers schemas/parsers at startup**, so most changes
    still need an app restart (see step 3).
- All secrets live in `nomad/.env` (gitignored — never committed, never pushed).

## 2. Pull the latest code

```bash
ssh debian@researchmcp.duckdns.org
cd ~/unified-researchdata-mcp
git status --short        # MUST be empty before pulling!
git pull origin master
```

**Rule: never pull with a dirty working tree.** If `git status --short` shows
anything, either commit it or stash it first (`git stash`, then `git stash pop`
after the pull). Pulling over local changes can cause merge conflicts.

## 3. Restart the app so the changes load

```bash
cd ~/unified-researchdata-mcp/nomad
docker restart nomad_oasis_app
```

Wait ~90 seconds, then verify:

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep nomad_oasis_app   # expect: (healthy)
curl -s -o /dev/null -w '%{http_code}\n' https://researchmcp.duckdns.org/nomad-oasis/gui/
```

- `docker restart` is enough for **schema/plugin code changes** (startup.sh runs
  again: it re-registers the entry points and reloads the metainfo).
- If `startup.sh` itself changed, **or** the container is in a broken state,
  use a full recreate instead:
  ```bash
  docker compose up -d --force-recreate app
  ```

## 4. After EVERY app restart/recreate: restart the proxy

```bash
docker restart nomad_oasis_proxy
```

**This is the #1 forgotten step.** The nginx proxy caches the app's IP at
startup. After the app container is recreated it gets a *new IP*, the proxy
still points at the old one, and the GUI shows **502 Bad Gateway** even though
`docker ps` says everything is healthy.

```bash
# quick check
curl -s -o /dev/null -w '%{http_code}\n' https://researchmcp.duckdns.org/nomad-oasis/gui/
# 200 = fine · 502 = restart the proxy (step 4)
```

## 5. Full-stack restart (after docker-compose.yaml / nomad.yaml changes)

```bash
cd ~/unified-researchdata-mcp/nomad
docker compose up -d          # recreates only what changed
docker restart nomad_oasis_proxy
```

For nomad.yaml config changes a `docker restart nomad_oasis_app` is usually
enough (the config is bind-mounted too); a compose `up -d` is the safe variant.

---

## Common errors (we have made all of these)

### Error 1: 502 Bad Gateway on `/nomad-oasis/gui/`
**Symptom:** `curl ... /nomad-oasis/gui/` → 502; landing page and `/nomad-oasis/`
(301) still work; `docker ps` shows the app as `(healthy)`.

**Cause:** nginx proxy has a stale DNS cache (old app IP).

**Fix:**
```bash
docker restart nomad_oasis_proxy
```

### Error 2: App stuck in `Restarting (1)` / crash loop
**Symptom:** `docker ps` shows `Restarting (1) 5 seconds ago` forever.

**Cause:** startup.sh or a plugin raises an exception at boot. The container
restarts, fails, restarts… To see the real error:
```bash
docker logs nomad_oasis_app 2>&1 | grep -iE 'error|traceback' | tail -10
```
Then fix the underlying issue (see below), pull, and restart.

### Error 3: `AttributeError: module 'instrument_data.entrypoint' has no attribute 'tga_parser'`
**Cause:** The entry-point registration in `startup.sh` / the `.dist-info`
`entry_points.txt` referenced the wrong object name. The parser entry point is
`instrument_data.entrypoint:tga_parser_entry_point` (with `_entry_point`).

**Fix:** Correct the name in `nomad/plugins/startup.sh` (it regenerates the
`.dist-info` at every startup), pull, restart app.

### Error 4: `ValidationError for ELNAnnotation`
**Symptom:** App crash loop; the error mentions `pydantic_core._pydantic_core.ValidationError`.
**Cause:** An invalid `component=` value in an `a_eln=ELNAnnotation(...)`.
Only these components exist in NOMAD 1.4.2:
`StringEditQuantity, NumberEditQuantity, BoolEditQuantity, EnumEditQuantity,
RichTextEditQuantity, DateTimeEditQuantity, FileEditQuantity, AuthorEditQuantity`
(and a few more). **There is no `SubSectionEditQuantity`** — for subsections use
plain `a_eln=ELNAnnotation()`.

**Fix:** Remove the invalid component, pull, restart.

### Error 5: `pint.errors.DimensionalityError: Cannot convert from 'delta_degree_Celsius / minute' to 'dimensionless'`
**Symptom:** `could not normalize section` error in the processing log; the
`.tprc` is not generated.

**Cause:** Reading a quantity value with `float(value)`. NOMAD stores unit-aware
quantities (pint), so `float()` on `10 delta_degC/min` fails.

**Fix:** Use the unit-aware helpers in `processor.py`:
```python
from instrument_data.processor import _to_unit
rate = _to_unit(seg.rate, "delta_degree_Celsius / minute")
temp = _to_unit(seg.end_temp, "degree_Celsius")   # absolute, not delta!
```

### Error 6: `git pull` fails with merge conflicts
**Symptom:** `git pull origin master` refuses or creates conflict markers.
**Cause:** Local uncommitted changes (often a stray `.bak` file or a local edit).

**Fix:**
```bash
git status --short          # see what's dirty
git stash                   # or commit the local change
git pull origin master
git stash pop
```

### Error 7: `Permission denied: '/nonexistent'` in the logs
**Symptom:** Log lines mention `/nonexistent` permission errors.
**Cause:** The container runs as a non-root user whose `HOME` is `/nonexistent`.
Harmless for normal operation (seen at startup), **not** a reason to restart.

---

## Golden rules

1. **`git status` empty before every pull.**
2. **After every app restart → `docker restart nomad_oasis_proxy`.**
3. **Never commit secrets:** `.env`, `.nomad_pat*`, `elab_key.txt` are ignored;
   `.bak`/`.save`/`.orig` files are ignored too — check `git status` before pushing.
4. **No internet in the container:** never add `pip install` to `startup.sh`;
   plugins load via the `.pth` bridge + `startup.sh` entry-point bootstrap.
5. **Verify after restart:** `docker ps | grep nomad_oasis_app` → `(healthy)`,
   and `curl https://researchmcp.duckdns.org/nomad-oasis/gui/` → 200.
