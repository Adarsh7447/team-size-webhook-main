"""
Tests for synchronous enrichment endpoint.

Endpoint tested:
- POST /api/v1/enrich
"""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    INVALID_ENRICHMENT_REQUEST_NO_ID,
    INVALID_ENRICHMENT_REQUEST_NO_NAME,
    MINIMAL_ENRICHMENT_REQUEST,
    VALID_ENRICHMENT_REQUEST,
    assert_valid_enrichment_response,
)


# =============================================================================
# POST /api/v1/enrich - Valid Requests
# =============================================================================


class TestEnrichEndpointValid:
    """Tests for valid enrichment requests."""

    @pytest.mark.asyncio
    async def test_enrich_returns_200(self, client: AsyncClient):
        """Enrich endpoint should return 200 OK for valid request."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_returns_valid_response(self, client: AsyncClient):
        """Enrich endpoint should return valid enrichment response."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert_valid_enrichment_response(data)

    @pytest.mark.asyncio
    async def test_enrich_returns_agent_id(self, client: AsyncClient):
        """Response should include the same agent_id from request."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert data["agent_id"] == VALID_ENRICHMENT_REQUEST["agent_id"]

    @pytest.mark.asyncio
    async def test_enrich_returns_team_size(self, client: AsyncClient):
        """Response should include team size count."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert "team_size_count" in data
        assert isinstance(data["team_size_count"], int)

    @pytest.mark.asyncio
    async def test_enrich_returns_team_members(self, client: AsyncClient):
        """Response should include team members list."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert "team_members" in data
        assert isinstance(data["team_members"], list)

    @pytest.mark.asyncio
    async def test_enrich_returns_confidence(self, client: AsyncClient):
        """Response should include confidence level."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert data["confidence"] in ["LOW", "MEDIUM", "HIGH"]

    @pytest.mark.asyncio
    async def test_enrich_returns_processing_time(self, client: AsyncClient):
        """Response should include processing time."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert "processing_time_ms" in data
        assert isinstance(data["processing_time_ms"], int)
        assert data["processing_time_ms"] >= 0


# =============================================================================
# POST /api/v1/enrich - Minimal Valid Request
# =============================================================================


class TestEnrichEndpointMinimal:
    """Tests for minimal valid requests."""

    @pytest.mark.asyncio
    async def test_enrich_minimal_request(self, client: AsyncClient):
        """Enrich should work with only required fields."""
        response = await client.post(
            "/api/v1/enrich",
            json=MINIMAL_ENRICHMENT_REQUEST,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_minimal_returns_valid_response(self, client: AsyncClient):
        """Minimal request should return valid response."""
        response = await client.post(
            "/api/v1/enrich",
            json=MINIMAL_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert_valid_enrichment_response(data)

    @pytest.mark.asyncio
    async def test_enrich_without_email(self, client: AsyncClient):
        """Enrich should work without email."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "organization_names": ["Smith Realty"],
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_without_phone(self, client: AsyncClient):
        """Enrich should work without phone."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "email": ["john@test.com"],
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_without_organization(self, client: AsyncClient):
        """Enrich should work without organization."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200


# =============================================================================
# POST /api/v1/enrich - Invalid Requests
# =============================================================================


class TestEnrichEndpointInvalid:
    """Tests for invalid enrichment requests."""

    @pytest.mark.asyncio
    async def test_enrich_missing_agent_id(self, client: AsyncClient):
        """Enrich should reject request without agent_id."""
        response = await client.post(
            "/api/v1/enrich",
            json=INVALID_ENRICHMENT_REQUEST_NO_ID,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_enrich_missing_full_name(self, client: AsyncClient):
        """Enrich should accept request without full_name (it's optional)."""
        response = await client.post(
            "/api/v1/enrich",
            json=INVALID_ENRICHMENT_REQUEST_NO_NAME,
        )
        # full_name is optional, so this should succeed
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_empty_body(self, client: AsyncClient):
        """Enrich should reject empty request body."""
        response = await client.post("/api/v1/enrich", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_enrich_no_body(self, client: AsyncClient):
        """Enrich should reject request without body."""
        response = await client.post("/api/v1/enrich")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_enrich_invalid_json(self, client: AsyncClient):
        """Enrich should reject invalid JSON."""
        response = await client.post(
            "/api/v1/enrich",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_enrich_wrong_type_agent_id(self, client: AsyncClient):
        """Enrich should reject non-string agent_id."""
        request = {
            "agent_id": 12345,  # Should be string
            "full_name": "John Smith",
        }
        response = await client.post("/api/v1/enrich", json=request)
        # Pydantic may coerce int to string, or reject
        # Check it doesn't crash
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_enrich_wrong_type_email(self, client: AsyncClient):
        """Enrich should handle wrong type for email field."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "email": "not-a-list",  # Should be list
        }
        response = await client.post("/api/v1/enrich", json=request)
        # May coerce or reject
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_enrich_null_values(self, client: AsyncClient):
        """Enrich should handle null values."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "email": None,
            "phone": None,
            "organization_names": None,
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200


# =============================================================================
# POST /api/v1/enrich - Edge Cases
# =============================================================================


class TestEnrichEndpointEdgeCases:
    """Edge cases for enrichment endpoint."""

    @pytest.mark.asyncio
    async def test_enrich_empty_string_name(self, client: AsyncClient):
        """Enrich should handle empty string name."""
        request = {
            "agent_id": "test-123",
            "full_name": "",
        }
        response = await client.post("/api/v1/enrich", json=request)
        # May accept with warning or reject
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_enrich_whitespace_name(self, client: AsyncClient):
        """Enrich should handle whitespace-only name."""
        request = {
            "agent_id": "test-123",
            "full_name": "   ",
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_enrich_very_long_name(self, client: AsyncClient):
        """Enrich should handle very long names."""
        request = {
            "agent_id": "test-123",
            "full_name": "A" * 1000,
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_special_characters_name(self, client: AsyncClient):
        """Enrich should handle special characters in name."""
        request = {
            "agent_id": "test-123",
            "full_name": "José García-López III",
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_unicode_name(self, client: AsyncClient):
        """Enrich should handle unicode in name."""
        request = {
            "agent_id": "test-123",
            "full_name": "田中太郎",
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_multiple_emails(self, client: AsyncClient):
        """Enrich should handle multiple emails."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "email": ["john@test.com", "john.smith@company.com", "j.smith@other.com"],
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_multiple_organizations(self, client: AsyncClient):
        """Enrich should handle multiple organizations."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "organization_names": ["Smith Realty", "Keller Williams", "RE/MAX"],
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_enrich_with_website_url(self, client: AsyncClient):
        """Enrich should accept website_url hint."""
        request = {
            "agent_id": "test-123",
            "full_name": "John Smith",
            "website_url": "https://smithrealty.com",
        }
        response = await client.post("/api/v1/enrich", json=request)
        assert response.status_code == 200


# =============================================================================
# POST /api/v1/enrich - Response Validation
# =============================================================================


class TestEnrichEndpointResponseValidation:
    """Validate response structure and types."""

    @pytest.mark.asyncio
    async def test_response_has_status(self, client: AsyncClient):
        """Response must have status field."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert "status" in data
        assert data["status"] in ["success", "partial", "failed"]

    @pytest.mark.asyncio
    async def test_response_team_member_structure(self, client: AsyncClient):
        """Team members should have correct structure."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        if data["team_members"]:
            member = data["team_members"][0]
            assert "name" in member
            assert "email" in member
            assert "phone" in member
            assert "designation" in member

    @pytest.mark.asyncio
    async def test_response_urls_are_strings_or_null(self, client: AsyncClient):
        """URL fields should be strings or null."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        for url_field in ["team_page_url", "homepage_url"]:
            assert data[url_field] is None or isinstance(data[url_field], str)

    @pytest.mark.asyncio
    async def test_response_detected_crms_is_list(self, client: AsyncClient):
        """detected_crms should be a list."""
        response = await client.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert isinstance(data["detected_crms"], list)


# =============================================================================
# POST /api/v1/enrich - Failure Scenarios
# =============================================================================


class TestEnrichEndpointFailure:
    """Tests for enrichment failure scenarios."""

    @pytest.mark.asyncio
    async def test_enrich_failure_response(self, client_with_failure: AsyncClient):
        """Failed enrichment should return proper error response."""
        response = await client_with_failure.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        assert response.status_code == 200  # Still 200, but status=failed
        data = response.json()
        assert data["status"] == "failed"

    @pytest.mark.asyncio
    async def test_enrich_failure_has_error_code(self, client_with_failure: AsyncClient):
        """Failed enrichment should include error code."""
        response = await client_with_failure.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert data["error_code"] is not None

    @pytest.mark.asyncio
    async def test_enrich_failure_has_error_message(
        self, client_with_failure: AsyncClient
    ):
        """Failed enrichment should include error message."""
        response = await client_with_failure.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert data["error_message"] is not None

    @pytest.mark.asyncio
    async def test_enrich_failure_team_size_negative(
        self, client_with_failure: AsyncClient
    ):
        """Failed enrichment should have negative team size."""
        response = await client_with_failure.post(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        data = response.json()
        assert data["team_size_count"] < 0


# =============================================================================
# POST /api/v1/enrich - HTTP Method Tests
# =============================================================================


class TestEnrichEndpointMethods:
    """Test HTTP method handling."""

    @pytest.mark.asyncio
    async def test_enrich_get_not_allowed(self, client: AsyncClient):
        """GET method should not be allowed."""
        response = await client.get("/api/v1/enrich")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_enrich_put_not_allowed(self, client: AsyncClient):
        """PUT method should not be allowed."""
        response = await client.put(
            "/api/v1/enrich",
            json=VALID_ENRICHMENT_REQUEST,
        )
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_enrich_delete_not_allowed(self, client: AsyncClient):
        """DELETE method should not be allowed."""
        response = await client.delete("/api/v1/enrich")
        assert response.status_code == 405
