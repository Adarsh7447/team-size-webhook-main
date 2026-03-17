"""
Request schemas for the API endpoints.

These Pydantic models define and validate incoming request data.
Simplified schema matching database fields:
- list_name, list_email, list_phone, list_team_name,
- list_brokerage, list_website, list_location
"""

import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class EnrichmentRequest(BaseModel):
    """
    Request body for the /api/v1/enrich endpoint.

    Simplified schema matching database fields for easier integration.
    """

    agent_id: Optional[str] = Field(
        default=None,
        description="Optional unique identifier (auto-generated if not provided)",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )

    @model_validator(mode="after")
    def ensure_agent_id(self):
        """Auto-generate agent_id if not provided."""
        if not self.agent_id or not self.agent_id.strip():
            self.agent_id = str(uuid.uuid4())
        return self

    list_name: Optional[str] = Field(
        default=None,
        description="Full name of the agent",
        examples=["Ryan Young"],
    )

    list_email: Optional[str] = Field(
        default=None,
        description="Email address of the agent",
        examples=["ryan@theyoungteam.com"],
    )

    list_phone: Optional[str] = Field(
        default=None,
        description="Phone number of the agent",
        examples=["+1-555-123-4567"],
    )

    list_team_name: Optional[str] = Field(
        default=None,
        description="Team or organization name",
        examples=["The Young Team", "Keller Williams"],
    )

    list_brokerage: Optional[str] = Field(
        default=None,
        description="Brokerage name",
        examples=["Keller Williams", "RE/MAX"],
    )

    list_website: Optional[str] = Field(
        default=None,
        description="Known website URL for the agent",
        examples=["https://theyoungteam.com"],
    )

    list_location: Optional[str] = Field(
        default=None,
        description="Location (city, state, or full address)",
        examples=["Columbus, OH", "Austin, TX"],
    )

    @field_validator("list_name", "list_email", "list_phone", "list_team_name",
                     "list_brokerage", "list_location", mode="before")
    @classmethod
    def strip_strings(cls, v):
        """Strip whitespace from string fields and convert empty to None."""
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @field_validator("list_website", mode="before")
    @classmethod
    def validate_url(cls, v):
        """Basic URL validation and normalization."""
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            # Add https:// if no protocol specified
            if v and not v.startswith(("http://", "https://")):
                v = f"https://{v}"
            return v
        return None

    def get_full_name(self) -> str:
        """Get full name."""
        return self.list_name or ""

    def has_minimum_data(self) -> bool:
        """Check if request has minimum data required for enrichment."""
        has_name = bool(self.list_name)
        has_identifier = bool(
            self.list_team_name
            or self.list_email
            or self.list_website
            or self.list_brokerage
        )
        return has_name or has_identifier

    class Config:
        json_schema_extra = {
            "example": {
                "list_name": "Ryan Young",
                "list_email": "ryan@theyoungteam.com",
                "list_phone": "+1-555-123-4567",
                "list_team_name": "The Young Team",
                "list_brokerage": "Keller Williams",
                "list_website": "https://theyoungteam.com",
                "list_location": "Columbus, OH",
            }
        }
