"""Single shared R worker process for all elabFTW users."""

import asyncio
import logging
import os
import shutil
import signal
import time
from typing import Optional

import httpx

logger = logging.getLogger("elabmcp-proxy.r_worker")

R_PORT = int(os.environ.get("ELABMCP_R_PORT", "18080"))
R_HOST = os.environ.get("ELABMCP_R_HOST", "127.0.0.1")
R_URL = f"http://{R_HOST}:{R_PORT}/mcp"

R_START_TIMEOUT = 60  # max seconds for R to start (cold start can be slow)
R_REQUEST_TIMEOUT = 60
_RESTART_DELAY = 2

# Path to shared worker R script
_SHARED_WORKER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "shared_worker.R",
)
if not os.path.exists(_SHARED_WORKER_SCRIPT):
    _SHARED_WORKER_SCRIPT = "/app/shared_worker.R"


def _find_rscript() -> str:
    path = shutil.which("Rscript")
    if path:
        return path
    fallback = "/usr/local/bin/Rscript"
    return fallback if os.path.isfile(fallback) else fallback


class SharedRWorker:
    """One shared R process serving all users."""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
        self._ready = False

    async def start(self):
        async with self._lock:
            if self._ready:
                return
            await self._start_process()
            await self._wait_ready()
            self._ready = True
            logger.info("Shared R worker ready on %s", R_URL)

    async def _start_process(self):
        rscript = _find_rscript()
        logger.info("Starting shared R worker: %s %s", rscript, _SHARED_WORKER_SCRIPT)
        self.process = await asyncio.create_subprocess_exec(
            rscript,
            _SHARED_WORKER_SCRIPT,
            stdin=None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(R_REQUEST_TIMEOUT),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        )
        self._stderr_task = asyncio.create_task(self._pipe_stderr())

    async def _wait_ready(self):
        """Poll R's HTTP endpoint until it responds with 200/202."""
        deadline = time.time() + R_START_TIMEOUT
        attempt = 0
        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    r = await c.post(
                        R_URL,
                        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2024-11-05",
                                         "capabilities": {},
                                         "clientInfo": {"name": "elabmcp-proxy", "version": "1.0"}}},
                        headers={
                            "Content-Type": "application/json",
                            "x-elabftw-api-key": "dummy",
                            "x-elabftw-base-url": "http://dummy",
                        },
                    )
                    logger.debug("R worker poll attempt %d: HTTP %d", attempt, r.status_code)
                    if r.status_code in (200, 202):
                        return
            except httpx.ConnectError:
                logger.debug("R worker not ready yet (attempt %d)", attempt)
            except Exception as e:
                logger.debug("R worker poll error: %s", e)
            attempt += 1
            await asyncio.sleep(0.5)

        raise RuntimeError(f"Shared R worker failed to start within {R_START_TIMEOUT}s")

    async def proxy_request(self, api_key: str, base_url: str, body: bytes) -> tuple[int, str]:
        if not self._ready or self.process is None or self.process.returncode is not None:
            await self._restart()

        headers = {
            "Content-Type": "application/json",
            "x-elabftw-api-key": api_key,
            "x-elabftw-base-url": base_url,
        }

        try:
            resp = await self._client.post(R_URL, content=body, headers=headers)
            status = resp.status_code
            text = resp.text

            if status == 202:
                return 202, ""
            if status == 200:
                return 200, text

            logger.warning("R worker HTTP %d: %.200s", status, text)
            return status, text

        except httpx.TimeoutException:
            logger.warning("R worker request timed out")
            return 504, "R worker request timed out"
        except httpx.RequestError as e:
            logger.warning("R worker connection error: %s", e)
            await self._restart()
            return 502, f"R worker unavailable: {e}"

    async def _pipe_stderr(self):
        try:
            async for line in self.process.stderr:
                logger.warning("[R stderr] %s", line.decode(errors="replace").rstrip())
        except Exception:
            pass

    async def _restart(self):
        logger.info("Restarting shared R worker")
        await self.shutdown()
        await self.start()

    async def shutdown(self):
        async with self._lock:
            self._ready = False
            if self._client:
                await self._client.aclose()
                self._client = None
            if self.process is not None and self.process.returncode is None:
                logger.info("Terminating shared R worker")
                try:
                    self.process.send_signal(signal.SIGTERM)
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        self.process.kill()
                        await self.process.wait()
                    except ProcessLookupError:
                        pass
            self.process = None

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def is_ready(self) -> bool:
        return self._ready and self.is_alive
