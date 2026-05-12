"""Unit tests for elabmcp_proxy.session module."""

import time
import asyncio

import pytest

from elabmcp_proxy.session import (
    RProcessHandle,
    SESSION_TIMEOUT,
    MAX_CONCURRENT_SESSIONS,
    acquire_session_slot,
    get_running_count,
    release_session_slot,
)


class TestSessionSlotCounter:
    """Global concurrent-session slot counter."""

    async def test_acquire_and_release(self):
        assert await acquire_session_slot() is True
        assert get_running_count() == 1
        await release_session_slot()
        assert get_running_count() == 0

    async def test_acquire_twice(self):
        assert await acquire_session_slot() is True
        assert await acquire_session_slot() is True
        assert get_running_count() == 2
        await release_session_slot()
        await release_session_slot()
        assert get_running_count() == 0

    async def test_release_never_negative(self):
        await release_session_slot()
        assert get_running_count() == 0
        await release_session_slot()
        assert get_running_count() == 0

    async def test_capacity_exhaustion(self, small_capacity):
        assert await acquire_session_slot() is True
        assert await acquire_session_slot() is True
        assert await acquire_session_slot() is False
        await release_session_slot()
        assert await acquire_session_slot() is True
        assert await acquire_session_slot() is False

    async def test_acquire_release_stress(self):
        limit = MAX_CONCURRENT_SESSIONS
        for _ in range(limit):
            assert await acquire_session_slot() is True
        assert get_running_count() == limit
        assert await acquire_session_slot() is False
        for _ in range(limit):
            await release_session_slot()
        assert get_running_count() == 0


class TestRProcessHandleConstruction:
    """RProcessHandle basic construction and property access."""

    def test_constructor(self):
        handle = RProcessHandle("abc123", "https://eln.example.org", "key_xxx")
        assert handle.token == "abc123"
        assert handle.base_url == "https://eln.example.org"
        assert handle.api_key == "key_xxx"
        assert handle.process is None
        assert handle.is_alive is False

    def test_touch_updates_last_active(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        t0 = handle.last_active
        time.sleep(0.01)
        handle.touch()
        assert handle.last_active > t0

    def test_expired_true_when_inactive(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        handle.last_active = 0
        assert handle.expired is True

    def test_expired_false_when_active(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        handle.last_active = time.time()
        assert handle.expired is False

    def test_expired_boundary(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        handle.last_active = time.time() - SESSION_TIMEOUT
        assert handle.expired is True
        handle.last_active = time.time() - SESSION_TIMEOUT + 1
        assert handle.expired is False

    def test_is_alive_no_process(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        assert handle.is_alive is False

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        q = await handle.subscribe()
        assert len(handle._subscribers) == 1
        handle.unsubscribe(q)
        assert len(handle._subscribers) == 0

    @pytest.mark.asyncio
    async def test_subscribe_maxsize(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        q = await handle.subscribe()
        assert q.maxsize == 256

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        await handle.shutdown()
        assert handle.process is None
        await handle.shutdown()
        assert handle.process is None

    @pytest.mark.asyncio
    async def test_write_stdin_raises_when_not_running(self):
        handle = RProcessHandle("t1", "https://eln.example.org", "key")
        with pytest.raises(RuntimeError, match="not running"):
            await handle.write_stdin(b'{"jsonrpc":"2.0"}')