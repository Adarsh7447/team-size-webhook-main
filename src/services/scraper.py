"""
Scraper service for fetching and processing web pages.

Wraps the Oxylabs client with content validation and HTML processing.
"""

from typing import List, Optional, Set
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.clients.oxylabs import OxylabsClient, ScrapeResult
from src.config.settings import settings
from src.core.exceptions import (
    BlockedDomainError,
    LowQualityContentError,
    ScrapingFailedError,
)
from src.core.logging import get_logger
from src.schemas.internal import ScrapedPage

logger = get_logger("scraper-service")


class ScraperService:
    """
    Service for scraping and processing web pages.

    Handles content validation, blocked domain filtering, and HTML processing.

    Usage:
        service = ScraperService(oxylabs_client)
        page = await service.scrape_url("https://example.com")
    """

    def __init__(
        self,
        oxylabs_client: OxylabsClient,
        blocked_domains: Optional[Set[str]] = None,
        min_content_length: Optional[int] = None,
        dead_content_snippets: Optional[List[str]] = None,
    ):
        """
        Initialize scraper service.

        Args:
            oxylabs_client: Configured Oxylabs API client
            blocked_domains: Set of domains to block (defaults to settings)
            min_content_length: Minimum HTML length in bytes (defaults to settings)
            dead_content_snippets: Patterns indicating dead pages (defaults to settings)
        """
        self.oxylabs = oxylabs_client
        self.blocked_domains = blocked_domains or settings.blocked_domains_set
        self.min_content_length = min_content_length or settings.min_html_bytes
        self.dead_content_snippets = (
            dead_content_snippets or settings.dead_content_snippets_list
        )

        # Track failed URLs to avoid retrying
        self._failed_urls: Set[str] = set()
        self._failed_domains: Set[str] = set()

    def is_blocked_domain(self, url: str) -> bool:
        """
        Check if a URL is from a blocked domain.

        Args:
            url: URL to check

        Returns:
            True if the domain is blocked
        """
        domain = self._extract_domain(url)
        if not domain:
            return False

        # Check exact match
        if domain in self.blocked_domains:
            return True

        # Check if it's a subdomain of a blocked domain
        for blocked in self.blocked_domains:
            if domain == blocked or domain.endswith(f".{blocked}"):
                return True

        # Check if domain has failed before
        if domain in self._failed_domains:
            return True

        return False

    def is_failed_url(self, url: str) -> bool:
        """Check if a URL has failed before."""
        return url in self._failed_urls

    def mark_url_failed(self, url: str) -> None:
        """Mark a URL as failed to avoid retrying."""
        self._failed_urls.add(url)

    def mark_domain_failed(self, url: str) -> None:
        """Mark a domain as failed to avoid retrying any URLs from it."""
        domain = self._extract_domain(url)
        if domain:
            self._failed_domains.add(domain)

    async def scrape_url(
        self,
        url: str,
        validate_content: bool = True,
    ) -> ScrapedPage:
        """
        Scrape a URL and return the page content.

        Args:
            url: URL to scrape
            validate_content: Whether to validate content quality

        Returns:
            ScrapedPage with content and metadata

        Raises:
            BlockedDomainError: If the domain is blocked
            ScrapingFailedError: If scraping fails
            LowQualityContentError: If content doesn't meet quality threshold
        """
        # Check if domain is blocked
        if self.is_blocked_domain(url):
            raise BlockedDomainError(
                domain=self._extract_domain(url) or url,
            )

        # Check if URL has failed before
        if self.is_failed_url(url):
            raise ScrapingFailedError(
                url=url,
                reason="URL previously failed",
            )

        logger.debug(
            "Scraping URL",
            url=url[:100],
        )

        # Perform the scrape
        result = await self.oxylabs.scrape_url(url)

        if not result:
            self.mark_url_failed(url)
            raise ScrapingFailedError(
                url=url,
                reason="Scraping returned no result",
            )

        # Check status code
        if not result.is_success:
            self.mark_url_failed(url)
            raise ScrapingFailedError(
                url=url,
                reason=f"HTTP status {result.status_code}",
                details={"status_code": result.status_code},
            )

        # Validate content if requested
        if validate_content:
            self._validate_content(url, result)

        page = ScrapedPage(
            url=url,
            final_url=result.final_url,
            html_content=result.content,
            status_code=result.status_code,
            content_length=len(result.content),
        )

        logger.debug(
            "Scrape successful",
            url=url[:100],
            final_url=result.final_url[:100] if result.final_url != url else "same",
            content_length=page.content_length,
        )

        return page

    async def scrape_url_safe(
        self,
        url: str,
        validate_content: bool = True,
    ) -> Optional[ScrapedPage]:
        """
        Scrape a URL, returning None on failure instead of raising.

        Args:
            url: URL to scrape
            validate_content: Whether to validate content quality

        Returns:
            ScrapedPage or None if scraping fails
        """
        try:
            return await self.scrape_url(url, validate_content)
        except (BlockedDomainError, ScrapingFailedError, LowQualityContentError) as e:
            logger.debug(
                "Scrape failed (safe mode)",
                url=url[:100],
                error=str(e),
            )
            return None

    def _validate_content(self, url: str, result: ScrapeResult) -> None:
        """
        Validate that scraped content meets quality thresholds.

        Raises:
            LowQualityContentError: If content is low quality
        """
        content = result.content

        # Check minimum length
        if len(content) < self.min_content_length:
            self.mark_url_failed(url)
            raise LowQualityContentError(
                url=url,
                reason=f"Content too short ({len(content)} < {self.min_content_length} bytes)",
                details={"content_length": len(content)},
            )

        # Check for dead content patterns
        content_lower = content[:8000].lower()
        for snippet in self.dead_content_snippets:
            if snippet in content_lower:
                self.mark_url_failed(url)
                raise LowQualityContentError(
                    url=url,
                    reason=f"Dead content detected: '{snippet}'",
                    details={"pattern": snippet},
                )

    def html_to_markdown(self, html: str) -> str:
        """
        Convert HTML content to clean markdown/text.

        Args:
            html: HTML content

        Returns:
            Cleaned text content
        """
        if not html:
            return ""

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Remove script, style, and other non-content tags
            for tag in soup(["script", "style", "noscript", "meta", "link", "header", "footer", "nav"]):
                tag.decompose()

            # Get text with newlines as separator
            text = soup.get_text(separator="\n", strip=True)

            # Clean up multiple newlines
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            return "\n\n".join(lines)

        except Exception as e:
            logger.warning(
                "HTML to markdown conversion failed",
                error=str(e),
            )
            return ""

    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL, removing www prefix."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain or None
        except Exception:
            return None

    async def close(self):
        """Close the underlying client."""
        await self.oxylabs.close()
