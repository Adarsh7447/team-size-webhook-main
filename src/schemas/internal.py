"""
Internal data models used within the application.

These models are for internal processing and are not exposed in the API.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Team Member Model (shared)
# =============================================================================


class TeamMemberSchema(BaseModel):
    """Team member information."""

    name: str = Field(description="Full name of the team member")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number")
    designation: str = Field(default="", description="Role/title")

    class Config:
        frozen = True


# =============================================================================
# Processing State Models
# =============================================================================


@dataclass
class WebsiteCandidate:
    """A candidate website found during search."""

    url: str
    reason: str
    html_content: Optional[str] = None
    final_url: Optional[str] = None
    is_valid: bool = True
    failure_reason: Optional[str] = None


@dataclass
class ScrapedPage:
    """Result of scraping a web page."""

    url: str
    final_url: str
    html_content: str
    status_code: int
    content_length: int

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass
class TeamAnalysisResult:
    """Result of team size analysis."""

    team_size: int
    team_members: List[TeamMemberSchema]
    confidence: str
    reasoning: str
    team_page_url: Optional[str] = None
    homepage_url: Optional[str] = None

    @property
    def team_size_category(self) -> str:
        """Convert team size to category."""
        if self.team_size in (0, -1, -2):
            return "Unknown"
        elif self.team_size == 1:
            return "Individual"
        elif self.team_size <= 5:
            return "Small"
        elif self.team_size <= 10:
            return "Medium"
        elif self.team_size <= 20:
            return "Large"
        else:
            return "Mega"


@dataclass
class BrokerageInfo:
    """Team and brokerage name information."""

    team_name: Optional[str] = None
    brokerage_name: Optional[str] = None


@dataclass
class TechnologyInfo:
    """Detected technology/CRM information."""

    detected_crms: List[str] = field(default_factory=list)
    detected_email_tools: List[str] = field(default_factory=list)


# =============================================================================
# Agent Data Model (for internal processing)
# =============================================================================


@dataclass
class AgentData:
    """
    Internal representation of agent data for processing.

    This normalizes the incoming request data for easier processing.
    Maps from simplified input fields:
    - list_name → full_name
    - list_email → email
    - list_phone → phone
    - list_team_name → team_name (organization)
    - list_brokerage → brokerage
    - list_website → website_url
    - list_location → location
    """

    agent_id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    team_name: Optional[str]
    brokerage: Optional[str]
    website_url: Optional[str]
    location: Optional[str]

    @classmethod
    def from_request(cls, request_data: Dict[str, Any]) -> "AgentData":
        """Create AgentData from a request dictionary."""
        # Map new field names to internal fields
        full_name = (request_data.get("list_name") or "").strip()
        email = request_data.get("list_email")
        phone = request_data.get("list_phone")
        team_name = request_data.get("list_team_name")
        brokerage = request_data.get("list_brokerage")
        website_url = request_data.get("list_website")
        location = request_data.get("list_location")

        # Strip strings if present
        if isinstance(email, str):
            email = email.strip() or None
        if isinstance(phone, str):
            phone = phone.strip() or None
        if isinstance(team_name, str):
            team_name = team_name.strip() or None
        if isinstance(brokerage, str):
            brokerage = brokerage.strip() or None
        if isinstance(website_url, str):
            website_url = website_url.strip() or None
        if isinstance(location, str):
            location = location.strip() or None

        return cls(
            agent_id=str(request_data.get("agent_id", "")),
            full_name=full_name,
            email=email,
            phone=phone,
            team_name=team_name,
            brokerage=brokerage,
            website_url=website_url,
            location=location,
        )

    @property
    def primary_email(self) -> Optional[str]:
        """Get the email."""
        return self.email

    @property
    def primary_phone(self) -> Optional[str]:
        """Get the phone."""
        return self.phone

    @property
    def primary_organization(self) -> Optional[str]:
        """Get the team name or brokerage as organization."""
        return self.team_name or self.brokerage

    def has_search_data(self) -> bool:
        """Check if we have enough data to perform a search."""
        return bool(self.full_name and (self.team_name or self.brokerage or self.email))


# =============================================================================
# Enrichment Context (carries state through the pipeline)
# =============================================================================


@dataclass
class EnrichmentContext:
    """
    Context object that carries state through the enrichment pipeline.

    This is passed between services and accumulates results.
    """

    agent: AgentData
    start_time: float = 0.0

    # Search results
    search_results: Optional[Dict[str, Any]] = None

    # Website selection
    selected_website: Optional[WebsiteCandidate] = None
    homepage_content: Optional[ScrapedPage] = None

    # Team page
    team_page_url: Optional[str] = None
    team_page_content: Optional[ScrapedPage] = None

    # Analysis results
    team_analysis: Optional[TeamAnalysisResult] = None
    brokerage_info: Optional[BrokerageInfo] = None
    technology_info: Optional[TechnologyInfo] = None

    # Error tracking
    error: Optional[str] = None
    error_code: Optional[str] = None

    @property
    def final_url(self) -> Optional[str]:
        """Get the final URL used for analysis (team page or homepage)."""
        if self.team_page_url:
            return self.team_page_url
        if self.selected_website:
            return self.selected_website.final_url or self.selected_website.url
        return None

    @property
    def homepage_url(self) -> Optional[str]:
        """Get the homepage URL."""
        if self.selected_website:
            return self.selected_website.final_url or self.selected_website.url
        return None

    @property
    def is_success(self) -> bool:
        """Check if enrichment was successful."""
        return (
            self.team_analysis is not None
            and self.team_analysis.team_size > 0
            and self.error is None
        )
