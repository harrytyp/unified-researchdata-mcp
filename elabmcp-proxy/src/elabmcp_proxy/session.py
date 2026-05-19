"""Session management — per-user credential store and R subprocess lifecycle."""

import asyncio
import logging
import os
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

# ── Global counter (not a cap per se, enforced on spawn) ──────────────────────
_total_running = 0
_total_running_lock = asyncio.Lock()


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
            logger.info(
                "Spawning R subprocess for token=%s (running=%d/%d)",
                self.token[:8], _total_running, MAX_CONCURRENT_SESSIONS,
            )
            try:
                rscript = _find_rscript()
                self.process = await asyncio.create_subprocess_exec(
                    rscript,
                    "-e", "elabrmcp::elabr_mcp_server(type='stdio')",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except Exception:
                await release_session_slot()
                raise
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

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TIMEOUT
