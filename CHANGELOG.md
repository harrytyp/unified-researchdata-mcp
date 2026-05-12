# Changelog

## [1.1.0] — 2026-05-08

### Fixed — 🔴 High Priority Security Items

#### 1. Rate limiting on `/register` (formerly: no rate limit)
- Integrated [slowapi](https://github.com/AsylumSecurity/fastapi-limiter) with a default of **10 POST requests per minute per IP**.
- Configurable via `ELABMCP_RATE_LIMIT` environment variable (e.g. `20/minute`, `100/hour`).
- Exceeded limits return HTTP 429 with standard `Retry-After` header.

#### 2. Subprocess resource caps (formerly: unbounded per-process consumption)
- **Global session limit** — hard cap of **20 concurrent R subprocesses** (`ELABMCP_MAX_SESSIONS`). Exceeding returns HTTP 503 to the SSE endpoint.
- **Memory limit** — `RLIMIT_AS` set to 256 MB per R subprocess (`ELABMCP_MAX_MEM_MB`). Exhaustion causes the process to receive `SIGSEGV` from the kernel.
- **CPU limit** — `RLIMIT_CPU` set to 300 seconds per R subprocess (`ELABMCP_MAX_CPU_SECONDS`). Exhaustion sends `SIGXCPU`.
- **Process limit** — `RLIMIT_NPROC` set to 64 per R subprocess, preventing fork bombs.
- **Capacity check** — the `/register` page now checks global capacity before creating a token, returning a clear error message if the server is full.

#### 3. Graceful subprocess shutdown (formerly: immediate `process.kill()`)
- Changed from `process.kill()` to:
  1. Send `SIGTERM` to allow R to clean up.
  2. Wait up to **3 seconds** for graceful exit.
  3. Fall back to `SIGKILL` if timeout expires.
- `stop_grace_period: 30s` set in `docker-compose.yml` so Docker gives the proxy time to drain.

#### 4. Docker resource limits (formerly: unbounded containers)
- `mem_limit: 2g` on `elabmcp-proxy` container (total, not per subprocess).
- `mem_limit: 512m` on `datatagger-mcp` container.
- `mem_limit: 128m` on `caddy` container.
- `stop_grace_period` set on all containers.

### Added — 🟡 Medium Priority Items

#### 5. Audit logging (formerly: no structured audit trail)
- New `elabmcp-proxy.audit` logger writes to `ELABMCP_AUDIT_LOG` (default: `/var/log/elabmcp-proxy/audit.log`).
- Events logged: `REGISTER`, `SSE_START`, `SSE_INVALID_TOKEN`, `POST_INVALID_TOKEN`, `POST_EXPIRED_SESSION`, `SESSION_EXPIRED`, `SERVER_SHUTDOWN`.
- Each event includes truncated token prefix and remote IP (where available).

### Changed
- `requirements.txt`: added `slowapi>=0.1.9`.
- `docker-compose.yml`: added per-container `mem_limit`, `stop_grace_period`, and environment variables for all caps.
- `app.py`: added `/status` endpoint returning `{"running_subprocesses": N, "registered_sessions": N}`.
