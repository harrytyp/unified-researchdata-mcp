"""Session management — per-user credential store and R subprocess lifecycle."""

import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("elabmcp-proxy.session")

SESSION_TIMEOUT = 1800  # 30 minutes


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
            env = os.environ.copy()
            env["ELABFTW_BASE_URL"] = self.base_url
            env["ELABFTW_API_KEY"] = self.api_key
            logger.info("Spawning R subprocess for token=%s", self.token[:8])
            self.process = await asyncio.create_subprocess_exec(
                "Rscript",
                "-e", "elabrmcp::elabr_mcp_server(type='stdio')",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
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
        """Read R stdout lines and fan-out to SSE subscribers."""
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
                logger.debug(
                    "[R stderr %s] %s",
                    self.token[:8],
                    line.decode(errors="replace").rstrip(),
                )
        except Exception:
            pass

    async def shutdown(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        if self._stdout_reader is not None:
            self._stdout_reader.cancel()
        if self._stderr_reader is not None:
            self._stderr_reader.cancel()
        self.process = None

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TIMEOUT
