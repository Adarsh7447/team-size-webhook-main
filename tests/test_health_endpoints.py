"""
Tests for health check endpoints.

Endpoints tested:
- GET /health
- GET /ready
- GET /info
- GET /
"""

import pytest
from httpx import AsyncClient


# =============================================================================
# GET /health - Basic Health Check
# =============================================================================


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient):
        """Health endpoint should return 200 OK."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_healthy_status(self, client: AsyncClient):
        """Health endpoint should return healthy status."""
        response = await client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_response_format(self, client: AsyncClient):
        """Health response should have correct format."""
        response = await client.get("/health")
        data = response.json()
        assert "status" in data
        assert isinstance(data["status"], str)


# =============================================================================
# GET /ready - Readiness Check
# =============================================================================


class TestReadyEndpoint:
    """Tests for GET /ready endpoint."""

    @pytest.mark.asyncio
    async def test_ready_returns_200(self, client: AsyncClient):
        """Ready endpoint should return 200 OK when all checks pass."""
        response = await client.get("/ready")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ready_returns_checks(self, client: AsyncClient):
        """Ready endpoint should include check details."""
        response = await client.get("/ready")
        data = response.json()
        assert "status" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    @pytest.mark.asyncio
    async def test_ready_includes_redis_check(self, client: AsyncClient):
        """Ready endpoint should check Redis connection."""
        response = await client.get("/ready")
        data = response.json()
        assert "redis" in data["checks"]

    @pytest.mark.asyncio
    async def test_ready_includes_api_keys_check(self, client: AsyncClient):
        """Ready endpoint should check API key configuration."""
        response = await client.get("/ready")
        data = response.json()
        assert "api_keys" in data["checks"]

    @pytest.mark.asyncio
    async def test_ready_includes_version(self, client: AsyncClient):
        """Ready endpoint should include version info."""
        response = await client.get("/ready")
        data = response.json()
        assert "version" in data

    @pytest.mark.asyncio
    async def test_ready_healthy_redis(self, client: AsyncClient, mock_redis):
        """Ready should show healthy when Redis is connected."""
        mock_redis.health_check.return_value = {
            "status": "healthy",
            "connected": True,
        }
        response = await client.get("/ready")
        data = response.json()
        assert data["checks"]["redis"]["status"] == "healthy"


# =============================================================================
# GET /info - Service Information
# =============================================================================


class TestInfoEndpoint:
    """Tests for GET /info endpoint."""

    @pytest.mark.asyncio
    async def test_info_returns_200(self, client: AsyncClient):
        """Info endpoint should return 200 OK."""
        response = await client.get("/info")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_info_returns_service_name(self, client: AsyncClient):
        """Info endpoint should return service name."""
        response = await client.get("/info")
        data = response.json()
        assert "service" in data
        assert data["service"] == "team-size-webhook"

    @pytest.mark.asyncio
    async def test_info_returns_version(self, client: AsyncClient):
        """Info endpoint should return version."""
        response = await client.get("/info")
        data = response.json()
        assert "version" in data
        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_info_returns_config(self, client: AsyncClient):
        """Info endpoint should return config (non-sensitive)."""
        response = await client.get("/info")
        data = response.json()
        assert "config" in data
        config = data["config"]
        assert "rate_limit_enabled" in config
        assert "rate_limit_requests" in config
        assert "grok_model" in config

    @pytest.mark.asyncio
    async def test_info_does_not_expose_secrets(self, client: AsyncClient):
        """Info endpoint should not expose API keys or passwords."""
        response = await client.get("/info")
        data = response.json()
        text = str(data).lower()
        assert "api_key" not in text
        assert "password" not in text
        assert "secret" not in text


# =============================================================================
# GET / - Root Endpoint
# =============================================================================


class TestRootEndpoint:
    """Tests for GET / root endpoint."""

    @pytest.mark.asyncio
    async def test_root_returns_200(self, client: AsyncClient):
        """Root endpoint should return 200 OK."""
        response = await client.get("/")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_root_returns_service_info(self, client: AsyncClient):
        """Root endpoint should return service info."""
        response = await client.get("/")
        data = response.json()
        assert "service" in data
        assert "version" in data
        assert "health" in data

    @pytest.mark.asyncio
    async def test_root_health_link(self, client: AsyncClient):
        """Root endpoint should provide health check link."""
        response = await client.get("/")
        data = response.json()
        assert data["health"] == "/health"


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestHealthEndpointEdgeCases:
    """Edge cases for health endpoints."""

    @pytest.mark.asyncio
    async def test_health_with_trailing_slash(self, client: AsyncClient):
        """Health endpoint should work with trailing slash."""
        response = await client.get("/health/")
        # FastAPI redirects or handles trailing slash
        assert response.status_code in [200, 307]

    @pytest.mark.asyncio
    async def test_health_wrong_method(self, client: AsyncClient):
        """Health endpoint should reject POST method."""
        response = await client.post("/health")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_ready_wrong_method(self, client: AsyncClient):
        """Ready endpoint should reject POST method."""
        response = await client.post("/ready")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_nonexistent_endpoint(self, client: AsyncClient):
        """Non-existent endpoint should return 404."""
        response = await client.get("/nonexistent")
        assert response.status_code == 404
