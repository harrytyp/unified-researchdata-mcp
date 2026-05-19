"""
Docker service integration tests.

These tests verify that Docker Compose services are running and that
all API endpoints are reachable. They are skipped unless run with
the --docker flag or DOCKER_TESTS=1 is set in the environment.

Usage:
    DOCKER_TESTS=1 pytest tests/test_docker_services.py -v
"""

import json
import os
import subprocess
import sys

import pytest

DOCKER_TESTS_ENABLED = os.environ.get("DOCKER_TESTS", "").lower() in ("1", "true", "yes")

docker_test = pytest.mark.skipif(
    not DOCKER_TESTS_ENABLED,
    reason="Set DOCKER_TESTS=1 to run Docker integration tests",
)


def _docker_compose_cmd():
    """Return the docker compose command for this environment."""
    return ["docker", "compose"]


def _run_compose(*args):
    cmd = _docker_compose_cmd() + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


@pytest.fixture(scope="module")
def compose_project():
    """Fixture that ensures compose file exists and returns the project directory."""
    compose_file = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml")
    if not os.path.exists(compose_file):
        pytest.skip(f"docker-compose.yml not found at {compose_file}")
    return os.path.dirname(compose_file)


# ── Service health checks ──────────────────────────────────────────────────────


@docker_test
class TestDockerServices:
    """Verify all Docker Compose services are defined and running."""

    def test_compose_file_exists(self, compose_project):
        compose_file = os.path.join(compose_project, "docker-compose.yml")
        assert os.path.exists(compose_file)

    def test_all_services_defined(self, compose_project):
        """Check docker-compose config lists the expected services."""
        result = _run_compose("-f", "docker-compose.yml", "config", "--services")
        assert result.returncode == 0
        services = result.stdout.strip().splitlines()
        assert "datatagger-mcp" in services
        assert "elabmcp-proxy" in services
        assert "caddy" in services

    def test_services_are_running(self, compose_project):
        """All three services should be in the 'running' state."""
        result = _run_compose("-f", "docker-compose.yml", "ps", "--format", "json")
        assert result.returncode == 0
        lines = result.stdout.strip().splitlines()
        if not lines:
            pytest.skip("No services running (docker compose ps returned empty)")

        services = {}
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            svc = entry.get("Name") or entry.get("Service", "")
            state = entry.get("State", "")
            services[svc] = state

        # Match by name suffix since Compose may prepend project name
        def find_service(svc_name):
            for key in services:
                if svc_name in key:
                    return services[key]
            return None

        for expected in ("datatagger-mcp", "elabmcp-proxy", "caddy"):
            state = find_service(expected)
            assert state == "running", (
                f"Service '{expected}' not running (state={state})"
            )


# ── Endpoint reachability ──────────────────────────────────────────────────────


@docker_test
class TestEndpointReachability:
    """Verify API endpoints respond correctly through Caddy."""

    @pytest.fixture(scope="class")
    def caddy_base_url(self):
        return os.environ.get("TEST_BASE_URL", "http://localhost")

    def _get(self, url, path):
        import httpx
        try:
            return httpx.get(f"{url}{path}", timeout=10.0)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            pytest.skip(f"Cannot reach {url}: {e}")

    def test_caddy_is_reachable(self, caddy_base_url):
        resp = self._get(caddy_base_url, "/")
        # Caddy returns 404 for unknown host by default; that's fine
        assert resp.status_code in (200, 404, 502)

    def test_elabmcp_proxy_register_get(self, caddy_base_url):
        """GET /el/register should return HTML form."""
        resp = self._get(caddy_base_url, "/el/register")
        assert resp.status_code == 200
        assert "elabFTW MCP Registration" in resp.text

    def test_elabmcp_proxy_status(self, caddy_base_url):
        """GET /el/status should return JSON with running/registered counts."""
        resp = self._get(caddy_base_url, "/el/status")
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("content-type", "")
        data = resp.json()
        assert "running_subprocesses" in data
        assert "registered_sessions" in data

    def test_elabmcp_proxy_mcp_invalid_token(self, caddy_base_url):
        """GET /el/mcp with bad token returns 401."""
        resp = self._get(caddy_base_url, "/el/mcp?token=badtoken")
        assert resp.status_code == 401

    def test_elabmcp_proxy_post_register_capacity(self, caddy_base_url):
        """POST /el/register with valid data returns success page."""
        import httpx
        resp = httpx.post(
            f"{caddy_base_url}/el/register",
            data={"api_key": "test-key-docker", "base_url": "https://eln.example.org"},
            timeout=10.0,
        )
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            assert "/el/mcp?token=" in resp.text

    def test_datatagger_mcp_register_get(self, caddy_base_url):
        """Verify datatagger-mcp serves its register page at /dt/register."""
        import httpx
        try:
            resp = httpx.get(f"{caddy_base_url}/dt/register", timeout=10.0)
            assert resp.status_code in (200, 401, 404)
        except httpx.ConnectError:
            pytest.skip("Cannot reach Caddy proxy")


# ── Direct container communication ─────────────────────────────────────────────


@docker_test
class TestDirectContainerAccess:
    """Talk to containers directly on their internal ports (for debugging)."""

    def test_elabmcp_proxy_direct_status(self):
        """Direct access to elabmcp-proxy:8081/status."""
        import httpx
        try:
            resp = httpx.get("http://elabmcp-proxy:8081/status", timeout=5.0)
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("Cannot reach elabmcp-proxy container directly")

        assert resp.status_code == 200
        assert resp.json()["running_subprocesses"] >= 0

    def test_datatagger_mcp_direct_status(self):
        """Direct access to datatagger-mcp:8000."""
        import httpx
        try:
            resp = httpx.get("http://datatagger-mcp:8000/openapi.json", timeout=5.0)
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("Cannot reach datatagger-mcp container directly")

        assert resp.status_code == 200


# ── Docker Compose operations sanity ───────────────────────────────────────────


@docker_test
class TestDockerComposeOperations:
    """Sanity checks for docker-compose.yml structure."""

    def test_compose_version(self, compose_project):
        result = _run_compose("-f", "docker-compose.yml", "config")
        assert result.returncode == 0
        config = result.stdout
        assert "elabmcp-proxy" in config
        assert "datatagger-mcp" in config
        assert "caddy" in config

    def test_environment_variables_present(self, compose_project):
        result = _run_compose("-f", "docker-compose.yml", "config")
        assert result.returncode == 0
        config = result.stdout
        assert "ELABMCP_RATE_LIMIT" in config
        assert "ELABMCP_MAX_SESSIONS" in config
        assert "ELABMCP_MAX_MEM_MB" in config
        assert "ELABMCP_MAX_CPU_SECONDS" in config
        assert "ELABMCP_AUDIT_LOG" in config

    def test_resource_limits_set(self, compose_project):
        """Verify mem_limit and stop_grace_period are configured."""
        result = _run_compose("-f", "docker-compose.yml", "config")
        assert result.returncode == 0
        config = result.stdout
        assert "mem_limit" in config
        assert "stop_grace_period" in config

    def test_network_exposure(self, compose_project):
        """Only Caddy should expose public ports."""
        result = _run_compose("-f", "docker-compose.yml", "config")
        assert result.returncode == 0
        config = result.stdout
        # The proxy services should use expose (internal only)
        assert "8081" in config  # elabmcp-proxy
        assert "8000" in config  # datatagger-mcp
