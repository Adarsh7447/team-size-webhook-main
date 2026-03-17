"""
Pytest configuration and shared fixtures for API testing.

Provides mocked services and test client setup.
"""

import sys
from typing import Any, AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Mock xai_sdk before any imports
mock_xai = MagicMock()
mock_xai.Client = MagicMock
mock_xai.chat = MagicMock()
mock_xai.chat.user = MagicMock(return_value="user message")
sys.modules["xai_sdk"] = mock_xai
sys.modules["xai_sdk.chat"] = mock_xai.chat


# =============================================================================
# Sample Test Data
# =============================================================================

VALID_ENRICHMENT_REQUEST = {
    "agent_id": "test-agent-123",
    "list_name": "John Smith",
    "list_email": "john@smithrealty.com",
    "list_phone": "+1-555-123-4567",
    "list_team_name": "Smith Realty Group",
    "list_brokerage": "Keller Williams",
    "list_website": "https://smithrealty.com",
    "list_location": "Austin, TX",
}

MINIMAL_ENRICHMENT_REQUEST = {
    "agent_id": "minimal-agent",
    "list_name": "Jane Doe",
}

INVALID_ENRICHMENT_REQUEST_NO_ID = {
    "list_name": "John Smith",
}

INVALID_ENRICHMENT_REQUEST_NO_NAME = {
    "agent_id": "test-123",
}

MOCK_ENRICHMENT_RESPONSE = {
    "status": "success",
    "agent_id": "test-agent-123",
    "team_size_count": 5,
    "team_size_category": "Small",
    "team_members": [
        {
            "name": "John Smith",
            "email": "john@smithrealty.com",
            "phone": "+1-555-123-4567",
            "designation": "Team Lead",
        },
        {
            "name": "Jane Doe",
            "email": "jane@smithrealty.com",
            "phone": "",
            "designation": "Agent",
        },
    ],
    "team_page_url": "https://smithrealty.com/team",
    "homepage_url": "https://smithrealty.com",
    "team_name": "Smith Realty Group",
    "brokerage_name": "Keller Williams",
    "agent_designation": ["Team Lead"],
    "detected_crms": ["Follow Up Boss"],
    "confidence": "HIGH",
    "reasoning": "Found 5 team members on team page",
    "processing_time_ms": 4500,
    "error_code": None,
    "error_message": None,
}

MOCK_FAILED_RESPONSE = {
    "status": "failed",
    "agent_id": "test-agent-123",
    "team_size_count": -2,
    "team_size_category": "Unknown",
    "team_members": [],
    "team_page_url": None,
    "homepage_url": None,
    "team_name": None,
    "brokerage_name": None,
    "agent_designation": [],
    "detected_crms": [],
    "confidence": "LOW",
    "reasoning": "No website found",
    "processing_time_ms": 1500,
    "error_code": "NO_WEBSITE_FOUND",
    "error_message": "Could not find agent website",
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    mock = AsyncMock()
    mock.health_check = AsyncMock(
        return_value={
            "status": "healthy",
            "connected": True,
            "latency_ms": 1.5,
            "redis_version": "7.0.0",
        }
    )
    mock.rate_limit_sliding_window = AsyncMock(
        return_value=(True, 1, 99, 60)  # allowed, current, remaining, reset
    )
    mock.is_connected = True
    return mock


@pytest.fixture
def mock_enrichment_service():
    """Mock EnrichmentService."""
    from src.schemas.responses import EnrichmentResponse

    mock = AsyncMock()
    mock.enrich = AsyncMock(
        return_value=EnrichmentResponse(**MOCK_ENRICHMENT_RESPONSE)
    )
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_enrichment_service_failure():
    """Mock EnrichmentService that returns failure."""
    from src.schemas.responses import EnrichmentResponse

    mock = AsyncMock()
    mock.enrich = AsyncMock(return_value=EnrichmentResponse(**MOCK_FAILED_RESPONSE))
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_celery_task():
    """Mock Celery task."""
    mock = MagicMock()
    mock.id = "mock-task-id-12345"
    mock.delay = MagicMock(return_value=mock)
    return mock


@pytest_asyncio.fixture
async def app(mock_redis, mock_enrichment_service):
    """Create test FastAPI application with mocked dependencies."""
    from src.api.dependencies import (
        get_enrichment_service,
        get_redis,
    )

    # Disable rate limiting for tests
    with patch("src.config.settings.settings.rate_limit_enabled", False):
        from src.main import create_app

        app = create_app()

        # Override dependencies
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_enrichment_service] = lambda: mock_enrichment_service

        yield app

        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def client_with_failure(mock_redis, mock_enrichment_service_failure):
    """Create test client with failing enrichment service."""
    from src.api.dependencies import (
        get_enrichment_service,
        get_redis,
    )

    # Disable rate limiting for tests
    with patch("src.config.settings.settings.rate_limit_enabled", False):
        from src.main import create_app

        app = create_app()
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_enrichment_service] = (
            lambda: mock_enrichment_service_failure
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_with_rate_limit(mock_redis, mock_enrichment_service):
    """Create test client with rate limiting enabled for testing rate limiter."""
    from src.api.dependencies import (
        get_enrichment_service,
        get_redis,
    )
    from src.core.redis import RedisClient

    # Enable rate limiting and patch Redis singleton
    with patch("src.config.settings.settings.rate_limit_enabled", True):
        with patch.object(RedisClient, "get_instance", return_value=mock_redis):
            from src.main import create_app

            app = create_app()
            app.dependency_overrides[get_redis] = lambda: mock_redis
            app.dependency_overrides[get_enrichment_service] = lambda: mock_enrichment_service

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client

            app.dependency_overrides.clear()


# =============================================================================
# Helper Functions
# =============================================================================


def assert_valid_enrichment_response(data: Dict[str, Any]) -> None:
    """Assert response has required enrichment fields."""
    required_fields = [
        "status",
        "agent_id",
        "team_size_count",
        "team_size_category",
        "team_members",
        "confidence",
        "processing_time_ms",
    ]
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"

    assert data["status"] in ["success", "partial", "failed"]
    assert isinstance(data["team_size_count"], int)
    assert isinstance(data["team_members"], list)


def assert_valid_async_response(data: Dict[str, Any]) -> None:
    """Assert response has required async fields."""
    required_fields = ["task_id", "status", "status_url", "agent_id"]
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"

    assert data["status"] in ["queued", "processing", "completed", "failed"]


def assert_valid_task_status(data: Dict[str, Any]) -> None:
    """Assert response has required task status fields."""
    required_fields = ["task_id", "status", "ready"]
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"

    assert data["status"] in [
        "pending",
        "started",
        "success",
        "failure",
        "revoked",
        "progress",
    ]
    assert isinstance(data["ready"], bool)
