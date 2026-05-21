"""Session management — per-user credential store and R subprocess lifecycle."""

import asyncio
import logging
import os
import random
import shutil
import signal
import time

try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    HAS_RESOURCE = False
    resource = None  # type: ignore[assignment]

from typing import Optional

logger = logging.getLogger("elabmcp-proxy.session")

SESSION_TIMEOUT = 1800  # 30 minutes

# ── Resource limits applied to each R subprocess ──────────────────────────────
MAX_CONCURRENT_SESSIONS = int(os.environ.get("ELABMCP_MAX_SESSIONS", "20"))
MAX_MEM_MB = int(os.environ.get("ELABMCP_MAX_MEM_MB", "256"))
MAX_CPU_SECONDS = int(os.environ.get("ELABMCP_MAX_CPU_SECONDS", "300"))

# ── Transport mode for R subprocess ──────────────────────────────────────────
# Options: "stdio" (default, for local/agent use) or "http" (for hosted/proxied)
# When "http", each R subprocess runs as an HTTP server on a dynamically assigned port.
R_TRANSPORT = os.environ.get("ELABMCP_R_TRANSPORT", "stdio").lower()
HTTP_MIN_PORT = 18080
HTTP_MAX_PORT = 18280

# ── Global counter (not a cap per se, enforced on spawn) ──────────────────────
_total_running = 0
_total_running_lock = asyncio.Lock()

# ── HTTP port allocator (for http transport mode) ─────────────────────────────
_http_ports_used: set[int] = set()
_http_port_lock = asyncio.Lock()


def _pick_http_port() -> int:
    """Pick a random available port in the allowed range."""
    for _ in range(100):  # max retries
        port = random.randint(HTTP_MIN_PORT, HTTP_MAX_PORT)
        if port not in _http_ports_used:
            _http_ports_used.add(port)
            return port
    raise RuntimeError(f"No available HTTP port in range {HTTP_MIN_PORT}-{HTTP_MAX_PORT}")


async def acquire_session_slot() -> bool:
    async with _total_running_lock:
        global _total_running
        if _total_running >= MAX_CONCURRENT_SESSIONS:
            return False
        _total_running += 1
        return True


async def release_session_slot():
    async with _total_running_lock:
        global _total_running
        _total_running = max(0, _total_running - 1)


def get_running_count() -> int:
    return _total_running


def _setrlimit(prlimit=None):
    """Apply resource limits. Called in the child pre-exec.

    When ``os.prlimit`` is unavailable the preexec callback is invoked with
    no arguments; ``prlimit`` defaults to ``resource.setrlimit`` so the limits
    still apply in that case.
    """
    if not HAS_RESOURCE:
        return
    if prlimit is None:
        prlimit = resource.setrlimit  # type: ignore[assignment]
    try:
        prlimit(resource.RLIMIT_AS, (MAX_MEM_MB * 1024 * 1024, MAX_MEM_MB * 1024 * 1024))
    except Exception:
        pass
    try:
        prlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS + 10))
    except Exception:
        pass
    try:
        prlimit(resource.RLIMIT_NPROC, (64, 64))
    except Exception:
        pass


def _find_rscript() -> str:
    """Find Rscript executable cross-platform (Linux case-sensitive, Windows)."""
    path = shutil.which("Rscript")
    if path:
        return path
    fallback = "/usr/local/bin/Rscript"
    if os.path.isfile(fallback):
        return fallback
    return fallback


class RProcessHandle:
    """One R subprocess (elabrmcp stdio mode) per registered user."""

    def __init__(self, token: str, base_url: str, api_key: str):
        self.token = token
        self.base_url = base_url
        self.api_key = api_key
        self.process: Optional[asyncio.subprocess.Process] = None
        self.last_active = time.time()
        self._lock = asyncio.Lock()
        self._stdout_reader: Optional[asyncio.Task] = None
        self._stderr_reader: Optional[asyncio.Task] = None
        self._subscribers: list[asyncio.Queue] = []
        self._r_http_port: Optional[int] = None

    def touch(self):
        self.last_active = time.time()

    async def ensure_running(self):
        async with self._lock:
            if self.process is not None and self.process.returncode is None:
                return
            slot_ok = await acquire_session_slot()
            if not slot_ok:
                raise RuntimeError(
                    f"Server at capacity ({MAX_CONCURRENT_SESSIONS} sessions). "
                    "Please try again later."
                )
            env = os.environ.copy()
            env["ELABFTW_BASE_URL"] = self.base_url
            env["ELABFTW_API_KEY"] = self.api_key

            if R_TRANSPORT == "http":
                # Spawn R MCP server as HTTP endpoint on a dynamic port
                port = _pick_http_port()
                self._r_http_port = port
                env["MCPTOOLS_PORT"] = str(port)
                cmd_args = [
                    _find_rscript(), "-e",
                    f"elabrmcp::elabr_mcp_server(type='http', port={port})",
                ]
                logger.info(
                    "Spawning R HTTP subprocess for token=%s on port %d (running=%d/%d)",
                    self.token[:8], port, _total_running, MAX_CONCURRENT_SESSIONS,
                )
            else:
                # Spawn R MCP server in stdio mode (for local/agent use)
                cmd_args = [
                    _find_rscript(), "-e",
                    "elabrmcp::elabr_mcp_server(type='stdio')",
                ]
                logger.info(
                    "Spawning R stdio subprocess for token=%s (running=%d/%d)",
                    self.token[:8], _total_running, MAX_CONCURRENT_SESSIONS,
                )

            try:
                self.process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except Exception:
                await release_session_slot()
                raise

            if R_TRANSPORT == "stdio":
                self._stdout_reader = asyncio.create_task(self._pipe_stdout())
                self._stderr_reader = asyncio.create_task(self._pipe_stderr())

    async def write_stdin(self, data: bytes):
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("R subprocess not running")
        self.touch()
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers = [s for s in self._subscribers if s is not q]

    async def _pipe_stdout(self):
        try:
            async for line in self.process.stdout:
                self.touch()
                dead: list[asyncio.Queue] = []
                for q in self._subscribers:
                    try:
                        q.put_nowait(line)
                    except asyncio.QueueFull:
                        dead.append(q)
                for q in dead:
                    self.unsubscribe(q)
        except Exception:
            logger.exception("stdout pipe error for token=%s", self.token[:8])

    async def _pipe_stderr(self):
        try:
            async for line in self.process.stderr:
                logger.warning(
                    "[R stderr %s] %s",
                    self.token[:8],
                    line.decode(errors="replace").rstrip(),
                )
        except Exception:
            pass

    async def shutdown(self):
        # Release the HTTP port if using http transport
        if R_TRANSPORT == "http" and self._r_http_port is not None:
            async with _http_port_lock:
                _http_ports_used.discard(self._r_http_port)

        if self.process is not None and self.process.returncode is None:
            logger.info("Terminating R subprocess token=%s", self.token[:8])
            try:
                self.process.send_signal(signal.SIGTERM)
                await asyncio.wait_for(self.process.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.process.kill()
                    await self.process.wait()
                except ProcessLookupError:
                    pass
        elif self.process is not None:
            await self.process.wait()
        if self._stdout_reader is not None:
            self._stdout_reader.cancel()
        if self._stderr_reader is not None:
            self._stderr_reader.cancel()
        self.process = None
        await release_session_slot()

    async def proxy_request(self, data: bytes, timeout: float = 30.0) -> bytes:
        """Proxy an MCP request to the R subprocess via HTTP.

        Sends the request to the R subprocess's HTTP server and returns the
        raw response bytes.  Retries up to 5 times with exponential backoff
        to handle the race condition where the R HTTP server hasn't started
        listening yet (1-2s window after SSE endpoint is opened).
        """
        if R_TRANSPORT != "http" or self._r_http_port is None:
            raise RuntimeError(
                "proxy_request is only available when R_TRANSPORT=http"
            )

        async with self._lock:
            url = f"http://localhost:{self._r_http_port}/mcp"
            last_exc = None
            for attempt in range(5):
                try:
                    import aiohttp
                    connector = aiohttp.TCPConnector(
                        limit=1,
                        enable_cleanup_closed=True,
                    )
                    async with aiohttp.ClientSession(
                        connector=connector,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as session:
                        async with session.post(
                            url, data=data, headers={"Content-Type": "application/json"}
                        ) as resp:
                            body = await resp.read()
                            if resp.status != 200:
                                raise RuntimeError(
                                    f"R subprocess returned status {resp.status}: {body.decode(errors='replace')}"
                                )
                            return body
                except aiohttp.ClientConnectionError as e:
                    last_exc = e
                    if attempt < 4:
                        wait = 0.5 * (2 ** attempt)
                        logger.info(
                            "R subprocess not ready yet (attempt %d/5), retrying in %.1fs",
                            attempt + 1, wait,
                        )
                        await asyncio.sleep(wait)
                    continue
                except asyncio.TimeoutError:
                    raise RuntimeError(f"R subprocess request timed out after {timeout}s")

            raise RuntimeError(
                f"Failed to connect to R subprocess after 5 attempts: {last_exc}"
            )

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TIMEOUT
