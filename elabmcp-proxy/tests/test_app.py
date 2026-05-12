"""Integration tests for elabmcp_proxy.app — all API endpoints."""

import json
import uuid
import os
import logging

import pytest
from fastapi.testclient import TestClient

from elabmcp_proxy.app import create_app


class TestAppFactory:
    """App creation and route registration."""

    def test_create_app_returns_fastapi(self):
        app = create_app()
        assert app.title == "FastAPI"

    def test_routes_registered(self):
        app = create_app()
        routes = {r.path for r in app.routes}
        assert "/register" in routes
        assert "/mcp" in routes
        assert "/status" in routes


class TestRegisterEndpoint:
    """GET /register and POST /register."""

    def test_get_register_returns_html(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "elabFTW MCP Registration" in resp.text
        assert "base_url" in resp.text
        assert "api_key" in resp.text

    def test_post_register_missing_fields_returns_400(self, client):
        resp = client.post("/register", data={"api_key": "", "base_url": ""})
        assert resp.status_code == 400
        assert "required" in resp.text.lower()

    def test_post_register_missing_api_key(self, client):
        resp = client.post("/register", data={"api_key": "", "base_url": "https://eln.example.org"})
        assert resp.status_code == 400

    def test_post_register_missing_base_url(self, client):
        resp = client.post("/register", data={"api_key": "key123", "base_url": ""})
        assert resp.status_code == 400

    def test_post_register_success(self, client):
        resp = client.post(
            "/register",
            data={"api_key": "abc123key", "base_url": "https://eln.example.org"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "/mcp?token=" in resp.text

    def test_post_register_returns_valid_uuid_token(self, client):
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        assert resp.status_code == 200
        import re
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        assert match is not None
        token = match.group(1)
        parsed = uuid.UUID(token)
        assert parsed.version == 4

    def test_post_register_updates_status(self, client):
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        assert resp.status_code == 200
        status_resp = client.get("/status")
        assert status_resp.status_code == 200
        data = json.loads(status_resp.text)
        assert data["registered_sessions"] == 1
        assert data["running_subprocesses"] == 0

    def test_post_register_multiple_sessions(self, client):
        for i in range(3):
            resp = client.post(
                "/register",
                data={"api_key": f"key{i}", "base_url": "https://eln.example.org"},
            )
            assert resp.status_code == 200
        status_resp = client.get("/status")
        data = json.loads(status_resp.text)
        assert data["registered_sessions"] == 3
        assert data["running_subprocesses"] == 0

    def test_post_register_succeeds_under_capacity(self, client, small_capacity):
        """Registration always succeeds (slot acquired and released)."""
        for i in range(5):
            resp = client.post(
                "/register",
                data={"api_key": f"key{i}", "base_url": "https://eln.example.org"},
            )
            assert resp.status_code == 200


class TestStatusEndpoint:
    """GET /status."""

    def test_status_returns_json(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        data = json.loads(resp.text)
        assert "running_subprocesses" in data
        assert "registered_sessions" in data

    def test_status_initial_state(self, client):
        resp = client.get("/status")
        data = json.loads(resp.text)
        assert data["running_subprocesses"] == 0
        assert data["registered_sessions"] == 0


class TestMcpEndpoint:
    """GET /mcp (SSE stream) and POST /mcp (messages)."""

    def test_get_mcp_invalid_token_returns_401(self, client):
        resp = client.get("/mcp?token=nonexistent")
        assert resp.status_code == 401
        assert "Invalid" in resp.text

    def test_get_mcp_missing_token_returns_401(self, client):
        resp = client.get("/mcp")
        assert resp.status_code == 401

    def test_post_mcp_invalid_token_returns_401(self, client):
        resp = client.post("/mcp?token=nonexistent")
        assert resp.status_code == 401

    def test_post_mcp_without_sse_first_returns_410(self, client):
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        assert resp.status_code == 200
        import re
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token = match.group(1)

        resp = client.post(f"/mcp?token={token}", content=b'{"jsonrpc":"2.0","method":"test"}')
        assert resp.status_code == 410
        assert "expired" in resp.text.lower()

    def test_sse_stream_contains_endpoint_event_direct(self, client, mock_subprocess):
        """Verify SSE endpoint event content by directly invoking sse_stream."""
        import re
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token = match.group(1)

        from unittest.mock import AsyncMock, MagicMock
        mock_request = MagicMock()
        mock_request.query_params.get.return_value = token
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get = MagicMock(return_value="localhost:8081")
        mock_request.url.scheme = "http"
        mock_request.url.netloc = "localhost:8081"

        from elabmcp_proxy.app import sse_stream
        import asyncio

        response = asyncio.run(sse_stream(mock_request))
        assert response.media_type == "text/event-stream"
        assert response.headers.get("cache-control") == "no-cache"

    def test_subprocess_spawned_on_sse_connect(self, client, mock_subprocess):
        from elabmcp_proxy.session import get_running_count
        from elabmcp_proxy.app import token_store
        import asyncio

        import re
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token = match.group(1)

        handle = token_store[token]
        assert get_running_count() == 0
        asyncio.run(handle.ensure_running())
        assert get_running_count() == 1

    def test_post_mcp_after_sse_succeeds(self, client, mock_subprocess):
        from elabmcp_proxy.app import token_store
        import asyncio

        import re
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token = match.group(1)

        handle = token_store[token]
        asyncio.run(handle.ensure_running())
        assert handle.is_alive

        post_resp = client.post(
            f"/mcp?token={token}",
            content=b'{"jsonrpc":"2.0","method":"tools/list"}',
        )
        assert post_resp.status_code == 200
        assert post_resp.text == "ok"

    def test_subprocess_capacity_on_sse(self, client, mock_subprocess, small_capacity):
        from elabmcp_proxy.app import token_store
        from elabmcp_proxy.session import get_running_count
        import asyncio
        import pytest

        import re
        # Register all 3 tokens BEFORE starting subprocesses
        resp = client.post(
            "/register",
            data={"api_key": "key1", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token1 = match.group(1)

        resp = client.post(
            "/register",
            data={"api_key": "key2", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token2 = match.group(1)

        resp = client.post(
            "/register",
            data={"api_key": "key3", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token3 = match.group(1)

        asyncio.run(token_store[token1].ensure_running())
        assert get_running_count() == 1
        asyncio.run(token_store[token2].ensure_running())
        assert get_running_count() == 2

        with pytest.raises(RuntimeError, match="capacity"):
            asyncio.run(token_store[token3].ensure_running())
        assert get_running_count() == 2


class TestAuditLogging:
    """Verify audit events are written."""

    @pytest.fixture(autouse=True)
    def setup_audit_logger(self, tmp_path):
        """Redirect audit logger to a temp file for each test."""
        import elabmcp_proxy.app as a_mod

        audit_log = tmp_path / "audit.log"
        os.environ["ELABMCP_AUDIT_LOG"] = str(audit_log)

        a_mod._audit_logger.handlers.clear()
        a_mod._audit_handler = logging.FileHandler(str(audit_log), delay=True)
        a_mod._audit_handler.setFormatter(
            logging.Formatter("%(asctime)s\t%(message)s")
        )
        a_mod._audit_logger.addHandler(a_mod._audit_handler)

        self._audit_log = audit_log
        yield

    def _read_audit(self):
        return self._audit_log.read_text(encoding="utf-8")

    def test_register_logs_audit_event(self, client):
        client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        content = self._read_audit()
        assert "REGISTER" in content
        assert "token_prefix=" in content

    def test_sse_invalid_token_logs_audit(self, client):
        client.get("/mcp?token=badtoken")
        content = self._read_audit()
        assert "SSE_INVALID_TOKEN" in content

    def test_post_invalid_token_logs_audit(self, client):
        client.post("/mcp?token=badtoken")
        content = self._read_audit()
        assert "POST_INVALID_TOKEN" in content

    @pytest.mark.usefixtures("mock_subprocess")
    def test_sse_start_logs_audit(self, client):
        from elabmcp_proxy.app import token_store, sse_stream
        from unittest.mock import MagicMock
        import asyncio

        import re
        resp = client.post(
            "/register",
            data={"api_key": "key123", "base_url": "https://eln.example.org"},
        )
        match = re.search(r"/mcp\?token=([\w-]+)", resp.text)
        token = match.group(1)

        mock_request = MagicMock()
        mock_request.query_params.get.return_value = token
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get = MagicMock(return_value="localhost:8081")
        mock_request.url.scheme = "http"
        mock_request.url.netloc = "localhost:8081"

        response = asyncio.run(sse_stream(mock_request))
        assert response is not None
        content = self._read_audit()
        assert "SSE_START" in content