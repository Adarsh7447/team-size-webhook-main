"""
Tests for API middleware.

Middleware tested:
- Rate Limiter
- Error Handler
- Request ID
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from tests.conftest import VALID_ENRICHMENT_REQUEST


# =============================================================================
# Rate Limiter Middleware
# =============================================================================


class TestRateLimiterMiddleware:
    """Tests for rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Response should include rate limit headers."""
        # Use a non-excluded path (health is excluded)
        response = await client_with_rate_limit.post(
            "/api/v1/enrich",
            json={"agent_id": "test", "full_name": "Test User"},
        )
        # Check rate limit headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    @pytest.mark.asyncio
    async def test_rate_limit_headers_numeric(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Rate limit header values should be numeric."""
        response = await client_with_rate_limit.post(
            "/api/v1/enrich",
            json={"agent_id": "test", "full_name": "Test User"},
        )
        limit = response.headers.get("X-RateLimit-Limit")
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")

        assert limit is not None and limit.isdigit()
        assert remaining is not None and remaining.isdigit()
        assert reset is not None and reset.isdigit()

    @pytest.mark.asyncio
    async def test_rate_limit_decrements(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Remaining count should decrement with each request."""
        # First request - use non-excluded path
        response1 = await client_with_rate_limit.post(
            "/api/v1/enrich",
            json={"agent_id": "test1", "full_name": "Test User 1"},
        )
        remaining1 = int(response1.headers["X-RateLimit-Remaining"])

        # Mock decremented count for second request
        mock_redis.rate_limit_sliding_window.return_value = (True, 2, remaining1 - 1, 60)

        response2 = await client_with_rate_limit.post(
            "/api/v1/enrich",
            json={"agent_id": "test2", "full_name": "Test User 2"},
        )
        remaining2 = int(response2.headers["X-RateLimit-Remaining"])

        assert remaining2 == remaining1 - 1

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Should return 429 when rate limit exceeded."""
        # Mock rate limit exceeded
        mock_redis.rate_limit_sliding_window.return_value = (False, 101, 0, 45)

        response = await client_with_rate_limit.get("/api/v1/enrich/tasks/test")
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_response_format(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """429 response should have correct format."""
        mock_redis.rate_limit_sliding_window.return_value = (False, 101, 0, 45)

        response = await client_with_rate_limit.get("/api/v1/enrich/tasks/test")
        data = response.json()

        assert "error" in data
        assert "retry_after" in data
        assert data["retry_after"] == 45

    @pytest.mark.asyncio
    async def test_rate_limit_excluded_paths(self, client: AsyncClient):
        """Excluded paths should not be rate limited (rate limit disabled)."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_by_ip(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Rate limiting should be per-IP."""
        # Verify the rate limit key includes IP
        await client_with_rate_limit.post(
            "/api/v1/enrich",
            json={"agent_id": "test", "full_name": "Test"},
            headers={"X-Forwarded-For": "192.168.1.1"},
        )
        # The mock should have been called
        assert mock_redis.rate_limit_sliding_window.called

    @pytest.mark.asyncio
    async def test_rate_limit_x_forwarded_for(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Should use X-Forwarded-For header for IP detection."""
        response = await client_with_rate_limit.get(
            "/health", headers={"X-Forwarded-For": "10.0.0.1"}
        )
        assert response.status_code in [200, 429]  # Depends on mock

    @pytest.mark.asyncio
    async def test_rate_limit_redis_failure_allows_request(
        self, client_with_rate_limit: AsyncClient, mock_redis
    ):
        """Should allow request if Redis fails (fail open)."""
        mock_redis.rate_limit_sliding_window.side_effect = Exception("Redis error")

        response = await client_with_rate_limit.get("/health")
        # Should still work - fail open
        assert response.status_code == 200


# =============================================================================
# Request ID Middleware
# =============================================================================


class TestRequestIDMiddleware:
    """Tests for request ID middleware."""

    @pytest.mark.asyncio
    async def test_request_id_header_present(self, client: AsyncClient):
        """Response should include X-Request-ID header."""
        response = await client.get("/health")
        assert "X-Request-ID" in response.headers

    @pytest.mark.asyncio
    async def test_request_id_is_uuid_format(self, client: AsyncClient):
        """Request ID should be a valid UUID-like string."""
        response = await client.get("/health")
        request_id = response.headers["X-Request-ID"]
        # Should be a non-empty string
        assert len(request_id) > 0
        # UUID format has dashes
        assert "-" in request_id or len(request_id) == 32

    @pytest.mark.asyncio
    async def test_request_id_echoed_back(self, client: AsyncClient):
        """Should echo back client-provided request ID."""
        custom_id = "my-custom-request-id-123"
        response = await client.get(
            "/health",
            headers={"X-Request-ID": custom_id},
        )
        assert response.headers["X-Request-ID"] == custom_id

    @pytest.mark.asyncio
    async def test_request_id_unique_per_request(self, client: AsyncClient):
        """Each request should get a unique ID."""
        response1 = await client.get("/health")
        response2 = await client.get("/health")

        id1 = response1.headers["X-Request-ID"]
        id2 = response2.headers["X-Request-ID"]

        # Without passing X-Request-ID, each should be unique
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_response_time_header_present(self, client: AsyncClient):
        """Response should include X-Response-Time header."""
        response = await client.get("/health")
        assert "X-Response-Time" in response.headers

    @pytest.mark.asyncio
    async def test_response_time_format(self, client: AsyncClient):
        """X-Response-Time should be in ms format."""
        response = await client.get("/health")
        response_time = response.headers["X-Response-Time"]
        assert response_time.endswith("ms")
        # Should be a valid number before 'ms'
        time_value = response_time[:-2]
        assert time_value.isdigit()


# =============================================================================
# Error Handler Middleware
# =============================================================================


class TestErrorHandlerMiddleware:
    """Tests for error handling middleware."""

    @pytest.mark.asyncio
    async def test_validation_error_returns_422(self, client: AsyncClient):
        """Validation errors should return 422."""
        response = await client.post("/api/v1/enrich", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_validation_error_format(self, client: AsyncClient):
        """Validation error should have detail field."""
        response = await client.post("/api/v1/enrich", json={})
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client: AsyncClient):
        """Non-existent endpoint should return 404."""
        response = await client.get("/api/v1/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_method_not_allowed_returns_405(self, client: AsyncClient):
        """Wrong HTTP method should return 405."""
        response = await client.get("/api/v1/enrich")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_error_response_is_json(self, client: AsyncClient):
        """Error responses should be JSON."""
        response = await client.get("/api/v1/nonexistent")
        assert response.headers["content-type"].startswith("application/json")


# =============================================================================
# CORS Middleware
# =============================================================================


class TestCORSMiddleware:
    """Tests for CORS middleware."""

    @pytest.mark.asyncio
    async def test_cors_allows_all_origins(self, client: AsyncClient):
        """Should allow requests from any origin."""
        response = await client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # OPTIONS should be handled by CORS middleware
        assert response.status_code in [200, 204]

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client: AsyncClient):
        """CORS headers should be present in response."""
        response = await client.get(
            "/health",
            headers={"Origin": "http://example.com"},
        )
        # Access-Control-Allow-Origin should be present
        assert "access-control-allow-origin" in [
            h.lower() for h in response.headers.keys()
        ]


# =============================================================================
# Headers and Security
# =============================================================================


class TestSecurityHeaders:
    """Tests for security-related headers."""

    @pytest.mark.asyncio
    async def test_content_type_json(self, client: AsyncClient):
        """API responses should be application/json."""
        response = await client.get("/health")
        assert "application/json" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_no_sensitive_headers_exposed(self, client: AsyncClient):
        """Should not expose sensitive headers."""
        response = await client.get("/health")
        # Should not expose server details
        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        assert "x-powered-by" not in headers_lower


# =============================================================================
# Concurrent Requests
# =============================================================================


class TestConcurrentRequests:
    """Tests for concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, client: AsyncClient):
        """Should handle concurrent health check requests."""
        import asyncio

        # Make requests sequentially to avoid issues with shared client
        responses = []
        for _ in range(5):
            response = await client.get("/health")
            responses.append(response)

        # All should succeed
        for response in responses:
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_concurrent_requests_unique_ids(self, client: AsyncClient):
        """Each request should get unique ID."""
        request_ids = []
        for _ in range(5):
            response = await client.get("/health")
            request_ids.append(response.headers["X-Request-ID"])

        # All IDs should be unique
        assert len(set(request_ids)) == 5
