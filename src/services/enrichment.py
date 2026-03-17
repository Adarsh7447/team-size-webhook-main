"""
Enrichment orchestrator service.

Main service that coordinates all other services to perform
the complete agent enrichment workflow.
"""

import time
from typing import Optional

from src.core.exceptions import (
    AnalysisFailedError,
    BlockedDomainError,
    EnrichmentError,
    GrokAPIError,
    LowQualityContentError,
    NoSearchQueryError,
    NoWebsiteFoundError,
    ScrapingFailedError,
)
from src.core.logging import get_logger, set_agent_id
from src.schemas.internal import (
    AgentData,
    EnrichmentContext,
    TeamAnalysisResult,
    TeamMemberSchema,
    WebsiteCandidate,
)
from src.schemas.requests import EnrichmentRequest
from src.schemas.responses import EnrichmentResponse, TeamMemberResponse
from src.services.ai_analyzer import AIAnalyzerService
from src.services.link_extractor import LinkExtractor
from src.services.scraper import ScraperService
from src.services.search import SearchService
from src.services.tech_detector import TechnologyDetector

logger = get_logger("enrichment")


class EnrichmentService:
    """
    Main orchestrator for agent enrichment.

    Coordinates search, scraping, AI analysis, and technology detection
    to enrich agent data with team information.

    Usage:
        service = EnrichmentService(search, scraper, analyzer, ...)
        response = await service.enrich(request)
    """

    def __init__(
        self,
        search_service: SearchService,
        scraper_service: ScraperService,
        ai_analyzer: AIAnalyzerService,
        link_extractor: Optional[LinkExtractor] = None,
        tech_detector: Optional[TechnologyDetector] = None,
    ):
        """
        Initialize enrichment service.

        Args:
            search_service: Service for searching agent websites
            scraper_service: Service for scraping web pages
            ai_analyzer: Service for AI-powered analysis
            link_extractor: Service for extracting links (optional)
            tech_detector: Service for detecting technologies (optional)
        """
        self.search = search_service
        self.scraper = scraper_service
        self.analyzer = ai_analyzer
        self.link_extractor = link_extractor or LinkExtractor()
        self.tech_detector = tech_detector or TechnologyDetector()

    async def enrich(self, request: EnrichmentRequest) -> EnrichmentResponse:
        """
        Perform complete enrichment for an agent.

        This is the main entry point that orchestrates the entire workflow:
        1. Search for agent's website
        2. Select best website from results
        3. Scrape homepage
        4. Find and scrape team page
        5. Analyze team size
        6. Extract team/brokerage names
        7. Detect technologies

        Args:
            request: Enrichment request with agent data

        Returns:
            EnrichmentResponse with all enriched data
        """
        start_time = time.perf_counter()

        # Set agent ID in logging context
        set_agent_id(request.agent_id)

        # Convert request to internal model
        agent = AgentData.from_request(request.model_dump())

        # Create context to track state
        ctx = EnrichmentContext(agent=agent, start_time=start_time)

        logger.info(
            "Starting enrichment",
            agent_id=agent.agent_id,
            full_name=agent.full_name,
        )

        try:
            # If a website URL is provided, try scraping it directly first
            if ctx.agent.website_url:
                if await self._try_direct_website(ctx):
                    await self._extract_brokerage_info(ctx)
                    await self._detect_technologies(ctx)
                    return self._build_response(ctx, start_time)

            # Fallback (or primary if no website_url): search-based flow
            await self._search_for_website(ctx)
            await self._scrape_homepage(ctx)
            await self._find_team_page(ctx)
            await self._analyze_team_size(ctx)
            await self._extract_brokerage_info(ctx)
            await self._detect_technologies(ctx)
            return self._build_response(ctx, start_time)

        except NoSearchQueryError as e:
            logger.warning("No search query possible", error=str(e))
            ctx.error = str(e)
            ctx.error_code = "NO_SEARCH_QUERY"
            return self._build_error_response(ctx, start_time)

        except NoWebsiteFoundError as e:
            logger.warning("No website found", error=str(e))
            ctx.error = str(e)
            ctx.error_code = "NO_WEBSITE_FOUND"
            return self._build_error_response(ctx, start_time)

        except (ScrapingFailedError, LowQualityContentError, BlockedDomainError) as e:
            logger.warning("Scraping failed", error=str(e))
            ctx.error = str(e)
            ctx.error_code = "SCRAPE_FAILED"
            return self._build_error_response(ctx, start_time)

        except AnalysisFailedError as e:
            logger.warning("Analysis failed", error=str(e))
            ctx.error = str(e)
            ctx.error_code = "ANALYSIS_FAILED"
            return self._build_error_response(ctx, start_time)

        except GrokAPIError as e:
            logger.error("Grok API error", error=str(e))
            ctx.error = str(e)
            ctx.error_code = "GROK_API_ERROR"
            return self._build_error_response(ctx, start_time)

        except EnrichmentError as e:
            logger.error("Enrichment error", error=str(e))
            ctx.error = str(e)
            ctx.error_code = e.error_code
            return self._build_error_response(ctx, start_time)

        except Exception as e:
            logger.exception("Unexpected error during enrichment")
            ctx.error = str(e)
            ctx.error_code = "INTERNAL_ERROR"
            return self._build_error_response(ctx, start_time)

    async def _try_direct_website(self, ctx: EnrichmentContext) -> bool:
        """
        Try scraping the provided website URL directly.

        Returns True if scraping + team analysis succeeded with team_size > 0.
        On any failure or team_size <= 0, resets context so the search fallback
        starts with a clean slate.
        """
        url = ctx.agent.website_url
        logger.info("Trying provided website directly", url=url)

        try:
            page = await self.scraper.scrape_url(url)

            ctx.selected_website = WebsiteCandidate(
                url=url,
                reason="Provided website URL",
                html_content=page.html_content,
                final_url=page.final_url,
            )
            ctx.homepage_content = page

            await self._find_team_page(ctx)
            await self._analyze_team_size(ctx)

            if ctx.team_analysis and ctx.team_analysis.team_size > 0:
                logger.info(
                    "Direct website succeeded",
                    url=url,
                    team_size=ctx.team_analysis.team_size,
                )
                return True

            logger.info("Direct website returned team_size <= 0, falling back to search", url=url)

        except (BlockedDomainError, ScrapingFailedError, LowQualityContentError) as e:
            logger.info("Direct website scrape failed, falling back to search", url=url, error=str(e))
        except Exception as e:
            logger.warning("Unexpected error scraping provided website, falling back to search", url=url, error=str(e))

        # Reset context so the search-based fallback starts clean
        ctx.selected_website = None
        ctx.homepage_content = None
        ctx.team_page_url = None
        ctx.team_page_content = None
        ctx.team_analysis = None
        return False

    async def _search_for_website(self, ctx: EnrichmentContext) -> None:
        """Search for agent's website using Serper."""
        logger.debug("Searching for website")

        results = await self.search.search_for_agent(ctx.agent)

        if not results or not results.get("organic"):
            raise NoWebsiteFoundError(
                message="Search returned no results",
                details={"queries_tried": self.search.build_search_queries(ctx.agent)},
            )

        ctx.search_results = results

    async def _scrape_homepage(self, ctx: EnrichmentContext) -> None:
        """Select best website and scrape homepage."""
        logger.debug("Selecting and scraping homepage")

        max_attempts = 3
        exclude_url = None

        for attempt in range(max_attempts):
            # Ask AI to select best website
            assessment = await self.analyzer.assess_website(
                agent=ctx.agent,
                search_results=ctx.search_results,
                exclude_url=exclude_url,
            )

            if not assessment.url:
                if attempt == max_attempts - 1:
                    raise NoWebsiteFoundError(
                        message="AI could not select a valid website",
                        details={"reason": assessment.reason},
                    )
                continue

            # Try to scrape the selected URL
            try:
                page = await self.scraper.scrape_url(assessment.url)

                ctx.selected_website = WebsiteCandidate(
                    url=assessment.url,
                    reason=assessment.reason,
                    html_content=page.html_content,
                    final_url=page.final_url,
                )
                ctx.homepage_content = page

                logger.debug(
                    "Homepage scraped successfully",
                    url=assessment.url[:50],
                )
                return

            except (BlockedDomainError, ScrapingFailedError, LowQualityContentError) as e:
                logger.debug(
                    "Selected website failed, trying next",
                    url=assessment.url[:50],
                    error=str(e),
                    attempt=attempt + 1,
                )
                exclude_url = assessment.url
                self.scraper.mark_url_failed(assessment.url)

                if attempt == max_attempts - 1:
                    raise

        raise NoWebsiteFoundError(message="Could not scrape any selected website")

    async def _find_team_page(self, ctx: EnrichmentContext) -> None:
        """Find and scrape team page if available."""
        logger.debug("Looking for team page")

        if not ctx.homepage_content:
            return

        # Extract links from homepage
        links = self.link_extractor.extract_internal_links(
            html=ctx.homepage_content.html_content,
            base_url=ctx.homepage_content.final_url,
        )

        if not links:
            logger.debug("No internal links found on homepage")
            return

        # Filter to team page candidates
        candidate_links = self.link_extractor.filter_team_page_candidates(links)

        if not candidate_links:
            logger.debug("No team page candidates found")
            return

        # Ask AI to select best team page
        selection = await self.analyzer.select_team_page(candidate_links)

        if not selection.selectedUrl:
            logger.debug("AI did not select a team page")
            return

        # Check if it's a blocked domain
        if self.scraper.is_blocked_domain(selection.selectedUrl):
            logger.debug("Selected team page is blocked domain")
            return

        # Scrape team page
        try:
            page = await self.scraper.scrape_url_safe(selection.selectedUrl)

            if page:
                ctx.team_page_url = selection.selectedUrl
                ctx.team_page_content = page
                logger.debug(
                    "Team page scraped successfully",
                    url=selection.selectedUrl[:50],
                )

        except Exception as e:
            logger.debug(
                "Team page scrape failed",
                url=selection.selectedUrl[:50],
                error=str(e),
            )

    async def _analyze_team_size(self, ctx: EnrichmentContext) -> None:
        """Analyze team size from page content."""
        logger.debug("Analyzing team size")

        # Determine which content to analyze
        content_page = ctx.team_page_content or ctx.homepage_content

        if not content_page:
            raise AnalysisFailedError(message="No page content to analyze")

        # Convert HTML to markdown
        markdown = self.scraper.html_to_markdown(content_page.html_content)

        if not markdown:
            raise AnalysisFailedError(message="Could not extract text from page")

        # Analyze team size
        analysis = await self.analyzer.analyze_team_size(
            markdown_content=markdown,
            agent_full_name=ctx.agent.full_name,
        )

        # If team page returned 0, try homepage
        if analysis.team_size == 0 and ctx.team_page_content and ctx.homepage_content:
            logger.debug("Team page returned 0, trying homepage")

            homepage_markdown = self.scraper.html_to_markdown(
                ctx.homepage_content.html_content
            )

            if homepage_markdown:
                homepage_analysis = await self.analyzer.analyze_team_size(
                    markdown_content=homepage_markdown,
                    agent_full_name=ctx.agent.full_name,
                )

                if homepage_analysis.team_size > 0:
                    analysis = homepage_analysis
                    ctx.team_page_url = None  # Use homepage instead
                    ctx.team_page_content = None

        # Set URLs on analysis result
        analysis.team_page_url = ctx.team_page_url
        analysis.homepage_url = ctx.homepage_url

        ctx.team_analysis = analysis

        logger.debug(
            "Team size analysis complete",
            team_size=analysis.team_size,
            confidence=analysis.confidence,
        )

    async def _extract_brokerage_info(self, ctx: EnrichmentContext) -> None:
        """Extract team and brokerage names."""
        logger.debug("Extracting brokerage info")

        content_page = ctx.team_page_content or ctx.homepage_content

        if not content_page or not ctx.homepage_url:
            return

        markdown = self.scraper.html_to_markdown(content_page.html_content)

        if not markdown:
            return

        ctx.brokerage_info = await self.analyzer.extract_team_brokerage(
            markdown_content=markdown,
            homepage_url=ctx.homepage_url,
        )

    async def _detect_technologies(self, ctx: EnrichmentContext) -> None:
        """Detect CRM and other technologies."""
        logger.debug("Detecting technologies")

        content_page = ctx.homepage_content or ctx.team_page_content

        if not content_page:
            return

        ctx.technology_info = self.tech_detector.detect(content_page.html_content)

    def _build_response(
        self,
        ctx: EnrichmentContext,
        start_time: float,
    ) -> EnrichmentResponse:
        """Build successful enrichment response."""
        processing_time = int((time.perf_counter() - start_time) * 1000)

        analysis = ctx.team_analysis
        if not analysis:
            return self._build_error_response(ctx, start_time)

        # Extract agent designation
        agent_designation = self.analyzer.extract_agent_designation(
            agent_full_name=ctx.agent.full_name,
            team_members=analysis.team_members,
        )

        # Convert team members to response format
        team_members = [
            TeamMemberResponse(
                name=m.name,
                email=m.email,
                phone=m.phone,
                designation=m.designation,
            )
            for m in analysis.team_members
        ]

        # Determine status
        if analysis.team_size > 0:
            status = "success"
        elif analysis.team_size == 0:
            status = "partial"
        else:
            status = "failed"

        # Get technology info
        detected_crms = []
        if ctx.technology_info:
            detected_crms = ctx.technology_info.detected_crms

        # Get brokerage info
        team_name = None
        brokerage_name = None
        if ctx.brokerage_info:
            team_name = ctx.brokerage_info.team_name
            brokerage_name = ctx.brokerage_info.brokerage_name

        logger.info(
            "Enrichment complete",
            agent_id=ctx.agent.agent_id,
            status=status,
            team_size=analysis.team_size,
            processing_time_ms=processing_time,
        )

        return EnrichmentResponse(
            status=status,
            agent_id=ctx.agent.agent_id,
            team_size_count=analysis.team_size,
            team_size_category=analysis.team_size_category,
            team_members=team_members,
            team_page_url=ctx.team_page_url,
            homepage_url=ctx.homepage_url,
            team_name=team_name,
            brokerage_name=brokerage_name,
            agent_designation=agent_designation,
            detected_crms=detected_crms,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            processing_time_ms=processing_time,
        )

    def _build_error_response(
        self,
        ctx: EnrichmentContext,
        start_time: float,
    ) -> EnrichmentResponse:
        """Build error enrichment response."""
        processing_time = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "Enrichment failed",
            agent_id=ctx.agent.agent_id,
            error_code=ctx.error_code,
            error=ctx.error,
            processing_time_ms=processing_time,
        )

        return EnrichmentResponse(
            status="failed",
            agent_id=ctx.agent.agent_id,
            team_size_count=-2,
            team_size_category="Unknown",
            team_members=[],
            team_page_url=ctx.team_page_url,
            homepage_url=ctx.homepage_url,
            team_name=None,
            brokerage_name=None,
            agent_designation=[],
            detected_crms=[],
            confidence="LOW",
            reasoning=ctx.error or "Enrichment failed",
            processing_time_ms=processing_time,
            error_code=ctx.error_code,
            error_message=ctx.error,
        )

    async def close(self):
        """Close all underlying services."""
        await self.search.close()
        await self.scraper.close()
        await self.analyzer.close()
