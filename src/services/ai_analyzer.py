"""
AI analyzer service for Grok-powered analysis.

Provides high-level methods for website assessment, team page selection,
team size analysis, and brokerage extraction.
"""

import json
import re
from typing import Any, Dict, List, Optional

from src.clients.grok import GrokClient
from src.core.exceptions import AnalysisFailedError, GrokAPIError
from src.core.logging import get_logger
from src.prompts import (
    TeamBrokerageExtraction,
    TeamPageSelection,
    TeamSizeAnalysis,
    WebsiteAssessment,
    format_team_brokerage_extraction_prompt,
    format_team_page_selection_prompt,
    format_team_size_analysis_prompt,
    format_website_assessment_prompt,
)
from src.schemas.internal import (
    AgentData,
    BrokerageInfo,
    TeamAnalysisResult,
    TeamMemberSchema,
)

logger = get_logger("ai-analyzer")


class AIAnalyzerService:
    """
    Service for AI-powered analysis using Grok.

    Provides methods for:
    - Website assessment (selecting best website from search results)
    - Team page selection (finding team/agent listing pages)
    - Team size analysis (counting and extracting team members)
    - Team/brokerage extraction (extracting names from content)

    Usage:
        service = AIAnalyzerService(grok_client)
        assessment = await service.assess_website(agent, search_results)
    """

    def __init__(self, grok_client: GrokClient):
        """
        Initialize AI analyzer service.

        Args:
            grok_client: Configured Grok AI client
        """
        self.grok = grok_client

    async def assess_website(
        self,
        agent: AgentData,
        search_results: Dict[str, Any],
        exclude_url: Optional[str] = None,
    ) -> WebsiteAssessment:
        """
        Assess search results to find the best website for an agent.

        Args:
            agent: Agent data for context
            search_results: Serper API search results
            exclude_url: URL to exclude from consideration

        Returns:
            WebsiteAssessment with selected URL and reasoning

        Raises:
            GrokAPIError: If AI analysis fails
        """
        # Format agent data for prompt
        org = agent.primary_organization or "N/A"
        phone = agent.primary_phone or "N/A"
        email = agent.primary_email or "N/A"
        location = agent.location or "N/A"
        website = agent.website_url or "N/A"
        brokerage = agent.brokerage or "N/A"

        # Get organic results
        organic = search_results.get("organic", [])[:8]

        prompt = format_website_assessment_prompt(
            organization_name=org,
            full_name=agent.full_name,
            phone=phone,
            email=email,
            location=location,
            brokerage=brokerage,
            website_clean=website,
            serper_results=json.dumps(organic, indent=2),
            exclude_url=exclude_url,
        )

        try:
            result = await self.grok.analyze_with_schema(
                prompt=prompt,
                response_schema=WebsiteAssessment,
                operation_name="website_assessment",
            )

            logger.debug(
                "Website assessment complete",
                selected_url=result.url[:50] if result.url else "none",
                agent_id=agent.agent_id,
            )

            return result

        except GrokAPIError:
            raise
        except Exception as e:
            logger.error(
                "Website assessment failed",
                error=str(e),
                agent_id=agent.agent_id,
            )
            return WebsiteAssessment(url="", reason=f"Analysis failed: {str(e)[:100]}")

    async def select_team_page(
        self,
        urls: List[str],
    ) -> TeamPageSelection:
        """
        Select the best team/agent page from a list of URLs.

        Args:
            urls: List of candidate URLs from a website

        Returns:
            TeamPageSelection with selected URL and reasoning

        Raises:
            GrokAPIError: If AI analysis fails
        """
        if not urls:
            return TeamPageSelection(
                selectedUrl="",
                reasoning="No URLs provided",
            )

        # Limit URLs to avoid huge prompts
        urls = urls[:100]

        prompt = format_team_page_selection_prompt(urls=urls)

        try:
            result = await self.grok.analyze_with_schema(
                prompt=prompt,
                response_schema=TeamPageSelection,
                operation_name="team_page_selection",
            )

            logger.debug(
                "Team page selection complete",
                selected_url=result.selectedUrl[:50] if result.selectedUrl else "none",
                url_count=len(urls),
            )

            return result

        except GrokAPIError:
            raise
        except Exception as e:
            logger.error(
                "Team page selection failed",
                error=str(e),
            )
            return TeamPageSelection(
                selectedUrl="",
                reasoning=f"Selection failed: {str(e)[:100]}",
            )

    async def analyze_team_size(
        self,
        markdown_content: str,
        agent_full_name: str = "",
    ) -> TeamAnalysisResult:
        """
        Analyze page content to determine team size and extract members.

        Args:
            markdown_content: Page content in markdown/text format
            agent_full_name: Agent's name for designation matching

        Returns:
            TeamAnalysisResult with team size and member details

        Raises:
            GrokAPIError: If AI analysis fails
            AnalysisFailedError: If analysis returns invalid results
        """
        if not markdown_content:
            raise AnalysisFailedError(
                message="No content provided for analysis",
            )

        prompt = format_team_size_analysis_prompt(
            markdown_content=markdown_content,
            agent_full_name=agent_full_name,
        )

        try:
            result = await self.grok.analyze_with_schema(
                prompt=prompt,
                response_schema=TeamSizeAnalysis,
                operation_name="team_size_analysis",
            )

            # Convert to internal model
            team_members = [
                TeamMemberSchema(
                    name=m.name,
                    email=m.email or "",
                    phone=m.phone or "",
                    designation=m.designation or "",
                )
                for m in result.teamMembers[:50]  # Limit to 50 members
            ]

            analysis_result = TeamAnalysisResult(
                team_size=int(result.teamSize),
                team_members=team_members,
                confidence=result.confidence,
                reasoning=result.reasoning,
            )

            logger.debug(
                "Team size analysis complete",
                team_size=analysis_result.team_size,
                member_count=len(team_members),
                confidence=analysis_result.confidence,
            )

            return analysis_result

        except GrokAPIError:
            raise
        except Exception as e:
            logger.error(
                "Team size analysis failed",
                error=str(e),
            )
            raise AnalysisFailedError(
                message=f"Analysis failed: {str(e)[:100]}",
                details={"error": str(e)},
            )

    async def extract_team_brokerage(
        self,
        markdown_content: str,
        homepage_url: str,
    ) -> BrokerageInfo:
        """
        Extract team and brokerage names from page content.

        Args:
            markdown_content: Page content in markdown/text format
            homepage_url: URL of the homepage for context

        Returns:
            BrokerageInfo with team and brokerage names
        """
        if not markdown_content:
            return BrokerageInfo()

        # Use first ~5000 chars to keep prompt reasonable
        content = markdown_content[:5000]

        prompt = format_team_brokerage_extraction_prompt(
            content=content,
            homepage_url=homepage_url,
        )

        try:
            result = await self.grok.analyze_with_schema(
                prompt=prompt,
                response_schema=TeamBrokerageExtraction,
                operation_name="brokerage_extraction",
            )

            # Clean up results
            team_name = self._clean_name(result.team_name)
            brokerage_name = self._clean_name(result.brokerage_name)

            logger.debug(
                "Brokerage extraction complete",
                team_name=team_name[:30] if team_name else "none",
                brokerage_name=brokerage_name[:30] if brokerage_name else "none",
            )

            return BrokerageInfo(
                team_name=team_name,
                brokerage_name=brokerage_name,
            )

        except Exception as e:
            logger.warning(
                "Brokerage extraction failed",
                error=str(e),
            )
            return BrokerageInfo()

    def extract_agent_designation(
        self,
        agent_full_name: str,
        team_members: List[TeamMemberSchema],
    ) -> List[str]:
        """
        Extract designations for a specific agent from team members list.

        Args:
            agent_full_name: Agent's full name to match
            team_members: List of team members with designations

        Returns:
            List of designations found for the agent
        """
        if not agent_full_name or not team_members:
            return []

        agent_name_lower = agent_full_name.strip().lower()
        agent_name_parts = set(agent_name_lower.split())

        designations = []

        for member in team_members:
            if not member.name:
                continue

            member_name_lower = member.name.strip().lower()

            # Exact match
            if agent_name_lower == member_name_lower:
                if member.designation:
                    designations.append(member.designation)
                continue

            # Partial match (at least 2 name parts match)
            member_parts = set(member_name_lower.split())
            common_parts = agent_name_parts.intersection(member_parts)

            if len(common_parts) >= 2 and member.designation:
                designations.append(member.designation)

        # Return unique designations
        return list(dict.fromkeys(designations))

    def _clean_name(self, name: Optional[str]) -> Optional[str]:
        """Clean and validate a name value."""
        if not name:
            return None

        name = str(name).strip()

        # Check for null-like values
        if name.lower() in ("null", "none", "n/a", "na", ""):
            return None

        return name

    async def close(self):
        """Close the underlying client."""
        await self.grok.close()
