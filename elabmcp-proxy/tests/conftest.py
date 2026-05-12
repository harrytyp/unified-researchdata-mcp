"""pytest fixtures for elabmcp-proxy tests."""

import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.util import get_remote_address


# Set high rate limit for all tests to avoid slowapi cross-test interference
os.environ["ELABMCP_RATE_LIMIT"] = "100000/minute"


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level globals before each test to avoid cross-test pollution."""
    import elabmcp_proxy.session as s_mod
    import elabmcp_proxy.app as a_mod

    s_mod._total_running = 0
    a_mod.token_store.clear()


@pytest.fixture
def app():
    """Create a fresh FastAPI app instance with a fresh limiter for testing."""
    from elabmcp_proxy.app import create_app

    return create_app()


@pytest.fixture
def client(app):
    """TestClient bound to the test app with a fresh rate-limiter."""
    import elabmcp_proxy.app as a_mod

    # Replace the module-level limiter with a fresh one so cross-test
    # state (accumulated rate-limit items) is eliminated.
    a_mod.limiter = Limiter(key_func=get_remote_address, default_limits=[])
    app.state.limiter = a_mod.limiter

    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_subprocess():
    """Mock asyncio.create_subprocess_exec so tests never actually spawn R."""

    class AsyncIterableMock:
        """Mocks an async iterable (stdout/stderr streams)."""

        def __init__(self):
            self._aiter_called = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncIterableMock()
    mock_proc.stderr = AsyncIterableMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        yield mock_proc


@pytest.fixture
def small_capacity():
    """Temporarily lower MAX_CONCURRENT_SESSIONS for capacity testing."""
    import elabmcp_proxy.session as s_mod

    original = s_mod.MAX_CONCURRENT_SESSIONS
    s_mod.MAX_CONCURRENT_SESSIONS = 2
    yield
    s_mod.MAX_CONCURRENT_SESSIONS = original