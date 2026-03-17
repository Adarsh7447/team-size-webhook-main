"""
Response schemas for the API endpoints.

These Pydantic models define the structure of API responses.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TeamMemberResponse(BaseModel):
    """Team member in the response."""

    name: str = Field(description="Full name of the team member")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number")
    designation: str = Field(default="", description="Role/title")


class EnrichmentResponse(BaseModel):
    """
    Response body for the /api/v1/enrich endpoint.

    This is the enriched data returned to n8n.
    """

    # Status
    status: Literal["success", "partial", "failed"] = Field(
        description="Overall status of the enrichment",
    )

    # Agent identification
    agent_id: str = Field(
        description="The agent ID from the request",
    )

    # Team size information
    team_size_count: int = Field(
        description="Number of team members found (-2 for error, -1 for unknown, 0+ for count)",
    )

    team_size_category: str = Field(
        description="Category: Unknown, Individual, Small, Medium, Large, Mega",
    )

    # Team members
    team_members: List[TeamMemberResponse] = Field(
        default_factory=list,
        description="List of team members found",
    )

    # URLs
    team_page_url: Optional[str] = Field(
        default=None,
        description="URL of the team page analyzed",
    )

    homepage_url: Optional[str] = Field(
        default=None,
        description="URL of the homepage",
    )

    # Team and brokerage names
    team_name: Optional[str] = Field(
        default=None,
        description="Name of the real estate team",
    )

    brokerage_name: Optional[str] = Field(
        default=None,
        description="Name of the brokerage",
    )

    # Agent designation (from team members list)
    agent_designation: List[str] = Field(
        default_factory=list,
        description="Designations/roles found for the agent",
    )

    # Technology detection
    detected_crms: List[str] = Field(
        default_factory=list,
        description="CRM systems detected on the website",
    )

    # Analysis metadata
    confidence: str = Field(
        default="LOW",
        description="Confidence level of the analysis: LOW, MEDIUM, HIGH",
    )

    reasoning: str = Field(
        default="",
        description="Explanation of how team size was determined",
    )

    # Performance
    processing_time_ms: int = Field(
        description="Total processing time in milliseconds",
    )

    # Error information (for failed/partial status)
    error_code: Optional[str] = Field(
        default=None,
        description="Error code if status is failed or partial",
    )

    error_message: Optional[str] = Field(
        default=None,
        description="Error message if status is failed or partial",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "agent_id": "550e8400-e29b-41d4-a716-446655440000",
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
                "team_page_url": "https://smithrealty.com/our-team",
                "homepage_url": "https://smithrealty.com",
                "team_name": "Smith Realty Group",
                "brokerage_name": "Keller Williams",
                "agent_designation": ["Team Lead"],
                "detected_crms": ["Follow Up Boss"],
                "confidence": "HIGH",
                "reasoning": "Found 5 team members listed on the team page with profile cards",
                "processing_time_ms": 4523,
                "error_code": None,
                "error_message": None,
            }
        }


class HealthResponse(BaseModel):
    """Response for health check endpoints."""

    status: Literal["healthy", "unhealthy"] = Field(
        description="Health status",
    )

    service: str = Field(
        default="team-size-api",
        description="Service name",
    )

    version: str = Field(
        description="API version",
    )

    timestamp: str = Field(
        description="Current timestamp in ISO format",
    )


class ReadinessResponse(BaseModel):
    """Response for readiness check endpoint."""

    status: Literal["ready", "not_ready"] = Field(
        description="Readiness status",
    )

    service: str = Field(
        default="team-size-api",
        description="Service name",
    )

    checks: Dict[str, bool] = Field(
        description="Individual check results",
    )

    errors: List[str] = Field(
        default_factory=list,
        description="List of error messages for failed checks",
    )


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error_code: str = Field(
        description="Machine-readable error code",
    )

    message: str = Field(
        description="Human-readable error message",
    )

    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details",
    )

    request_id: Optional[str] = Field(
        default=None,
        description="Request ID for tracking",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error_code": "VALIDATION_ERROR",
                "message": "Invalid request data",
                "details": {"field": "agent_id", "issue": "Field is required"},
                "request_id": "req_abc123",
            }
        }


class RateLimitResponse(BaseModel):
    """Response when rate limit is exceeded."""

    error_code: str = Field(
        default="RATE_LIMIT_EXCEEDED",
        description="Error code",
    )

    message: str = Field(
        default="Rate limit exceeded",
        description="Error message",
    )

    retry_after_seconds: int = Field(
        description="Seconds to wait before retrying",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": "Rate limit exceeded. Please try again later.",
                "retry_after_seconds": 60,
            }
        }


# =============================================================================
# Async Task Response Models
# =============================================================================


class AsyncEnrichmentResponse(BaseModel):
    """Response for async enrichment request."""

    task_id: str = Field(
        description="Celery task ID for tracking",
    )

    status: Literal["queued", "processing", "completed", "failed"] = Field(
        default="queued",
        description="Current task status",
    )

    status_url: str = Field(
        description="URL to check task status",
    )

    agent_id: str = Field(
        description="Agent ID from the request",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "abc123-def456-ghi789",
                "status": "queued",
                "status_url": "/api/v1/enrich/tasks/abc123-def456-ghi789",
                "agent_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        }


class TaskStatusResponse(BaseModel):
    """Response for task status query."""

    task_id: str = Field(
        description="Celery task ID",
    )

    status: Literal["pending", "started", "success", "failure", "revoked", "progress"] = Field(
        description="Current Celery task status",
    )

    ready: bool = Field(
        description="Whether the task has completed (success or failure)",
    )

    result: Optional[EnrichmentResponse] = Field(
        default=None,
        description="Enrichment result (only present when ready=True and successful)",
    )

    progress: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Progress information for batch tasks",
    )

    error: Optional[str] = Field(
        default=None,
        description="Error message if task failed",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "abc123-def456-ghi789",
                "status": "success",
                "ready": True,
                "result": {
                    "status": "success",
                    "agent_id": "550e8400",
                    "team_size_count": 5,
                    "team_size_category": "Small",
                    "team_members": [],
                    "processing_time_ms": 4500,
                },
                "progress": None,
                "error": None,
            }
        }
