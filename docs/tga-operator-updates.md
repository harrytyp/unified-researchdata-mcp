# Releasing the operator EXE (self-updating)

The operator app updates itself. The feed and the binary are two different
surfaces, and both have to move together:

| What | Where |
|---|---|
| Version the app compares against | `tga/tga_v2/version.py` (`APP_VERSION`) |
| Feed the app reads | `web/tga-operator/latest.json` → `https://researchdata.e-conversion.de/tga-operator/latest.json` (Caddy serves `web/` as `/srv/http`) |
| Binary | GitHub release asset, addressed by the feed |
| Digest next to the binary | `<exe>.sha256`, shipped in `dist/` and as a release asset |

`web/` is bind-mounted into the Caddy container, so the feed only changes after
the server checkout moves. Nothing installs without a matching sha256, and the
app never swaps itself without the operator confirming it.

## Steps

1. **Bump the version** in `tga/tga_v2/version.py`.

2. **Build in the dedicated build env** (never the main interpreter, never
   `%TEMP%`; and drop `PYTHONPATH` — the Hermes shell exports its own
   site-packages, which makes the venv import a foreign pydantic and every
   import fail):

   ```bash
   cp tga/tga_v2/{main.py,backend.py,updater.py,version.py} ~/tga-build/
   cd ~/tga-build
   env -u PYTHONPATH .venv/Scripts/python.exe -m PyInstaller --noconfirm TGA_Operator.spec
   ls -l dist/TGA_Operator.exe      # ~34 MB; ~440 MB means the wrong interpreter
   ```

3. **Digest next to the binary**, then copy both into the repo's `tga/dist/`:

   ```bash
   cd ~/tga-build/dist
   sha256sum TGA_Operator.exe > TGA_Operator.exe.sha256
   cp TGA_Operator.exe TGA_Operator.exe.sha256 <repo>/tga/dist/
   ```

4. **Feed** — `web/tga-operator/latest.json` (size and digest in bytes/hex):

   ```json
   {
     "version": "1.2.0",
     "url": "https://github.com/harrytyp/unified-researchdata-mcp/releases/download/v1.2.0/TGA_Operator.exe",
     "sha256": "<64 hex>",
     "size": 34123456,
     "notes": "Self-update, sha256 next to the EXE",
     "mandatory": false,
     "page": "https://github.com/harrytyp/unified-researchdata-mcp/releases/tag/v1.2.0"
   }
   ```

5. **Release** the tag with the EXE and its `.sha256` as assets (the app
   downloads from `latest.json`'s `url`, so the asset name must match).

6. **Push**, then move the server checkout so the feed is live
   (`git pull` fails on the SSH remote; use the HTTPS one):

   ```bash
   ssh debian@researchmcp.duckdns.org 'cd ~/unified-researchdata-mcp \
     && git -c fetch.recurseSubmodules=no fetch nomad master \
     && git merge --ff-only FETCH_HEAD'
   ```

7. **Verify** the feed is the one you wrote, and that the digest matches the
   asset:

   ```bash
   curl -s https://researchdata.e-conversion.de/tga-operator/latest.json
   curl -sL -o /tmp/x.exe <url> && sha256sum /tmp/x.exe
   ```

## What the app does with it

On start (and on *Settings → Check now*) it reads the feed, compares with
`APP_VERSION` and shows a badge in the header. "Download and restart" fetches
the binary into `%USERPROFILE%\.tga_updates`, verifies size and sha256, writes a
small `.cmd` that waits for the process to exit, renames the old EXE aside,
moves the new one in and restarts it.

The rename-retry loop in `updater._swap_script` deliberately avoids
`tasklist | find`: on any machine with git-bash on PATH, `find` resolves to GNU
find and the wait never terminates.
