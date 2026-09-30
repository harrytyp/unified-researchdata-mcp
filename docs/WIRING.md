# Wiring the MCP services

How the repositories fit together, what has to change where, and how a deploy
runs. Written after measuring the test host, not from memory.

## The shape

```
GitHub / GitLab repos hold code          this repo holds the composition
─────────────────────────────────        ────────────────────────────────
tum-research-data-hub/datatagger-mcp  ─┐
tum-research-data-hub/elabmcp          ├─ submodule ─→ docker-compose.yml ─→ Caddy
e-conversion/nomad-oasis-mcp          ─┘                + Caddyfile            │
e-conversion/atlas (GitLab)            ── caddy/ ──────────────────────────→  │
                                                                              ▼
                                                        /dt  /nm  /el   (+ eLabFTW, apps)
```

Rules that keep it working:

1. One service, one repository. When a service has its own repository, the copy
   in this repo is deleted, otherwise there are two truths.
2. The composition repo pins a revision per service. Nothing runs that is not
   written down in `DEPLOYMENTS.md`.
3. Builds happen on the host (`docker compose build <service>`), then the
   container is swapped (`up -d <service>`). The running container keeps serving
   while the new image builds.
4. Caddy keeps one path prefix per upstream system. `/dt`, `/nm`, `/el` stay
   separate endpoints; the chat keeps its own repository and host.

## Change list per repository

### A. `unified-researchdata-mcp` (this repo, GitHub)

| # | Change | Status |
|---|---|---|
| A1 | Submodule URLs to HTTPS where the repository is public | done (`85b9dd2`) |
| A2 | `elabR` back to SSH: it is private, HTTPS asks for a username | done here |
| A3 | DataTagger submodule points at the org repository, pin unchanged (`f30b664`, byte-identical to what ran before) | done (`85b9dd2`) |
| A4 | Add submodule `elabmcp` → `https://github.com/tum-research-data-hub/elabmcp.git` | done (`8d2e6fb`, pinned `b72285bb`) |
| A5 | Serve `/el` from `./elabmcp` (environment names in the table below) | done (`edb2079`); the R service is stopped but still defined |
| A6 | Delete `elabmcp-proxy/` and the `elabR` submodule, drop the temporary `127.0.0.1:8082` port | open, after a rollback week |
| A7 | Delete `datatagger-proxy/` once the DataTagger repository serves `/dt` itself (it now carries `Dockerfile`, `Caddyfile`, `jwt_token.py`) | open, decision |
| A8 | Optional: `image: <name>:${TAG:-local}` per service so a rollback starts the previous image instead of rebuilding | open |
| A9 | Host checkout fetches over HTTPS | done: the `nomad` remote is HTTPS and is what deploys use; `origin` (SSH) is left alone |

### B. `tum-research-data-hub/datatagger-mcp` (GitHub)

Nothing is required for the deploy. The submodule pin `f30b664` is the same
revision as `main` there, verified by hashing the blobs, so the running `/dt` and
the repository are in sync.

Only if the service should be built from this repository instead of from the
in-tree `datatagger-proxy/` (A7) does it have to offer the same surface as the
proxy does today: `/register`, `/mcp`, `/status`, URL prefix support, and
`MCP_JWT_SECRET`. Its `Dockerfile` currently defaults to stdio mode, and its
compose file expects `MCP_MODE=hosted`, so that has to be verified before
switching, not assumed.

### C. `tum-research-data-hub/elabmcp` (GitHub)

Standalone Python replacement for the R-based `/el` proxy. No blockers.

| # | Change | Status |
|---|---|---|
| C1 | Compose file used `ELABFTW_MCP_AI_KEY`, but the code reads `ELABFTW_MCP_AI_API_KEY`; a containerised deploy would have started with the AI tools silently off | fixed (`839104f`) |
| C2 | Optional: tag `v0.1.0` so the pin can name a release instead of a commit | open |

Environment names the server actually reads (from `config.py`): `MCP_JWT_SECRET`,
`MCP_TOKEN_EXPIRY_DAYS`, `ELABFTW_MCP_URL_PREFIX`, `ELABFTW_MCP_PORT`,
`ELABFTW_MCP_HOST`, `ELABFTW_MCP_CONFIG`, `ELABFTW_MCP_AUDIT_LOG`,
`ELABFTW_MCP_AI_API_KEY`, `ELABFTW_MCP_AI_BASE_URL`, `ELABFTW_MCP_AI_MODEL`.
Entry point for hosted mode: `elabftw-mcp --hosted --host 0.0.0.0 --port 8081`.

### D. `e-conversion/nomad-oasis-mcp` (GitHub)

Nothing is required. For production, two lines in this repo's compose decide
whether unregistered callers get read access: `NOMAD_MCP_ALLOW_ANONYMOUS` and
`NOMAD_MCP_REQUIRE_TOKEN` (today: allowed, which is the test setting).

### E. `e-conversion/atlas` (GitLab)

Nothing to change. It supplies `caddy/econverse.caddy`, which the Caddy of this
stack mounts read-only. If a host name changes, both repositories have to change
with it.

## Verified on the test host

Measured, not assumed:

- The host reaches the public repositories over HTTPS with no credentials:
  `datatagger-mcp f30b664`, `elabmcp c41bd11`, `nomad-oasis-mcp de520ac`.
- `elabR` is private. `git ls-remote https://github.com/MarvinLuepke/elabR.git`
  fails with `could not read Username`. Hence A2.
- `docker build` over an HTTPS clone works: `elabmcp` 187 MB, `datatagger-mcp`
  (org repository) 183 MB. Both verified in a temporary directory; no service or
  container was touched, and the images were removed afterwards.
- Inside the built image: `elabftw_mcp 0.1.0`, 41 tools registered.
- Disk on the host: 73 GB free of 99 GB.

## Deploy

```bash
cd ~/unified-researchdata-mcp
git fetch nomad && git merge --ff-only nomad/master     # or origin, once A9 is done
git submodule sync --recursive
git submodule update --init --recursive                 # elabR needs a deploy key; skip it while unused
docker compose build datatagger-proxy nomad-mcp elabmcp-proxy
docker compose up -d datatagger-proxy nomad-mcp elabmcp-proxy
docker compose ps
```

Rollback: `git checkout <previous commit>`, `git submodule update`, `docker
compose build` and `up -d` again. With A8 it is `docker compose up -d` with the
previous tag and no build.

## Done on 2026-09-30 (the `/el` switch)

Measured, in this order:

* both servers answered with the same 41 tools, the same tool names, and the same entities
  (user 194 "ELN-User RDM", team 29, the same experiment categories); the old one printed R
  text, the new one JSON
* the canary ran on `127.0.0.1:8082` beside the R service, which kept serving `/el` untouched
* after the Caddyfile change, `/el` answered from the new container; registration through
  Caddy, `tools/list` (41), `get_connection_info`, `list_experiments` and a
  `create_experiment` write with an API cleanup all passed (9/9)
* the R container was then stopped; `/el`, `/dt` and `/nm` stayed at HTTP 200 and the write
  check passed again (9/9). Container: 65 MiB of 512 MiB, 0.25 % CPU

Two things learned on the way, worth remembering:

* a single-file bind mount pins the inode: after `git checkout` replaced the `Caddyfile`, a
  `caddy reload` inside the container still read the old file. `docker compose restart caddy`
  fixes it; `up -d` does not, because the service definition did not change.
* `git fetch` recurses into submodules by default and fails on the private `elabR` URL. Use
  `git -c fetch.recurseSubmodules=no fetch <remote>` on this host.

## Rollback

`docker compose up -d elabmcp-proxy` and point the Caddyfile back at
`reverse_proxy elabmcp-proxy:8081`. The old image and the `elabR` checkout are still on the
host.
