# NOMAD MCP

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server for
the [NOMAD](https://nomad-lab.eu) API. It exposes NOMAD's read endpoints as MCP
tools, so an assistant can search entries, read archives, browse uploads and
datasets, look up schemas, and fetch crystal structures.

Built on the current protocol generation: MCP Python SDK **2.2.0** (streamable
HTTP transport, `MCPServer`, tool annotations). No deprecated SSE path, no
session state on the server beyond the transport's own.

## Tools

| Tool | NOMAD endpoint | What it does |
|---|---|---|
| `search_entries` | `POST /entries/query` | Search entries, returns one page plus `pagination.total` |
| `get_entry` | `GET /entries/{id}` | Metadata of one entry |
| `get_entry_archive` | `GET /entries/{id}/archive` | The full processed archive |
| `list_uploads` | `GET /uploads` | The account's uploads |
| `get_upload` | `GET /uploads/{id}` | One upload with files and status |
| `list_upload_entries` | `GET /uploads/{id}/entries` | Entries of one upload |
| `list_raw_files` | `GET /entries/{id}/rawdir` | The submitted files of an entry |
| `get_raw_file` | `GET /entries/{id}/raw/{path}` | The content of one raw file |
| `list_datasets` | `GET /datasets/` | Datasets |
| `get_dataset` | `GET /datasets/` | One dataset |
| `get_schema` | `GET /schemas/{id}` | A data schema |
| `search_quantities` | `POST /apps/search-quantities` | Which fields this instance can filter on |
| `get_info` | `GET /info` | Version, deployment, what it can parse |
| `get_me` | `GET /users/me` | Whose account the credential is |
| `get_structure` | `GET /systems/{id}` | An atomistic structure file |
| `list_groups` | `GET /groups` | User groups |

Every tool is annotated `readOnlyHint`/`idempotentHint`. Nothing in this server
writes to NOMAD; `POST` is used only where NOMAD models a *search* as a POST.

`GET /metainfo/{definition_id}` is deliberately not exposed: on a stock NOMAD it
answers 404 for the definition ids that appear in archives, so a tool around it
would fail more often than it helps.

## Authentication

Three ways in, in order of precedence:

1. **Registration token** — `?token=<jwt>` or `Authorization: Bearer <jwt>`.
   Minted by the register page from a user's own NOMAD personal access token.
   The token is self-contained (HMAC-SHA256, `MCP_JWT_SECRET`): it carries the
   base URL, the API key, and the selected tools. Nothing is stored server-side.
2. **A bare NOMAD personal access token** in the same two places — used
   directly against this deployment's NOMAD.
3. **Nothing** — the call runs as the deployment's own PAT
   (`NOMAD_MCP_DEFAULT_PAT`), read-only. That is what makes the server
   *autoconnected* for callers that never register: they get read access to
   whatever that PAT can see, and nothing more.

The credential is never logged, never echoed in an error message, and never
written to disk.

## Endpoints

| Path | Purpose |
|---|---|
| `/mcp` | MCP (streamable HTTP) |
| `/register` | Registration page: NOMAD API key in, personal MCP URL out |
| `/health` | Liveness plus the non-secret configuration |

Behind the stack's Caddy the server is reached at `/nm/*`, so the public URLs
are `https://<host>/nm/mcp` and `https://<host>/nm/register`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NOMAD_BASE_URL` | `https://nomad-lab.eu/prod/v1/api/v1` | NOMAD API to talk to |
| `NOMAD_GUI_URL` | central NOMAD GUI | Template for entry links |
| `NOMAD_MCP_DEFAULT_PAT` | empty | Deployment PAT used when a caller sends no credential |
| `NOMAD_MCP_ALLOW_ANONYMOUS` | `true` | `false` serves unauthenticated callers public data only |
| `NOMAD_MCP_REQUIRE_TOKEN` | `false` | `true` refuses callers without a credential |
| `MCP_JWT_SECRET` | — | HMAC secret for registration tokens (shared with the other proxies) |
| `MCP_TOKEN_EXPIRY_DAYS` | `30` | Lifetime of a registration token |
| `NOMAD_MCP_MAX_RESPONSE_CHARS` | `60000` | Responses above this are truncated with a note |
| `NOMAD_MCP_RATE_LIMIT` | `120` | Calls per minute per credential, `0` disables |
| `NOMAD_MCP_TIMEOUT_S` | `60` | NOMAD request timeout |
| `URL_PREFIX` | `/nm` | Path prefix the proxy strips |

## Running it

```bash
docker build -f nomad-mcp/Dockerfile -t nomad-mcp .
docker run --rm -p 8000:8000 \
  -e MCP_JWT_SECRET=... \
  -e NOMAD_BASE_URL=https://nomad-lab.eu/prod/v1/api/v1 \
  nomad-mcp
```

In the monorepo it is the `nomad-mcp` service of `docker-compose.yml`.

## Tests

`tests/smoke.py` starts the app in-process and drives it with a real MCP client
against a real NOMAD deployment — the tools must return real data, not mocks:

```bash
python tests/smoke.py
NOMAD_BASE_URL=https://<oasis>/api/v1 NOMAD_MCP_DEFAULT_PAT=<pat> python tests/smoke.py
```

It covers the tool listing and annotations, a live search with pagination, the
raw-file path, error handling for unknown ids, the registration flow (including
a refused key), and token integrity.
