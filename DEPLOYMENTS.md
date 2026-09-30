# What runs on the deployment

One line per service: where its code comes from, and which revision is pinned in
this repository. Bump the pin, then follow "Deploy" in `docs/WIRING.md`.

| Service | Source | Pinned at | Serves |
|---|---|---|---|
| `datatagger-proxy` | in-tree `datatagger-proxy/` + submodule `datatagger-mcp` | `f30b664` | `/dt` |
| `nomad-mcp` | submodule `nomad-mcp` (`e-conversion/nomad-oasis-mcp`) | `de520ac` | `/nm` |
| `elabmcp-proxy` | in-tree `elabmcp-proxy/` + submodule `elabR` (R worker) | `12a2e39` | `/el` |
| `elabftw` | image `elabftw/elabimg:6.0.2` | image tag | eLabFTW itself |
| `elab-mysql` | image `mysql:8.4` | image tag | eLabFTW database |
| `caddy` | image `caddy:2` + `Caddyfile` + `../atlas/caddy` | image tag | TLS and routing for all of the above |
| `elab-app` | in-tree `elab-app/` | this commit | eLabFTW helper app |
| `proespm-app` | in-tree `proespm-app/` | this commit | proESPM helper app |

The host checkout is `~/unified-researchdata-mcp`. It has two remotes: `origin`
(SSH, the build host has no GitHub key) and `nomad` (HTTPS, works). Use the
HTTPS path.

## History

| Date | Change |
|---|---|
| 2026-09-30 | Submodule URLs to HTTPS where the repositories are public; `elabR` back to SSH because it is private (see `.gitmodules`) |
| 2026-09-29 | `/dt` served by the MCP SDK app (protocol 2026-07-28), DataTagger library pinned to `f30b664` |
