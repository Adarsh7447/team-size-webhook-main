"""
Oxylabs API client for web scraping.

Oxylabs provides a web scraping API with JavaScript rendering support.
https://oxylabs.io/
"""

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional, Type

from src.clients.base import BaseClient
from src.config.settings import settings
from src.core.exceptions import ExternalAPIError, OxylabsAPIError
from src.core.logging import get_logger

logger = get_logger("oxylabs-client")


@dataclass
class ScrapeResult:
    """Result of a web scraping operation."""

    content: str
    status_code: int
    final_url: str

    @property
    def is_success(self) -> bool:
        """Check if the scrape was successful (2xx status code)."""
        return 200 <= self.status_code < 300


class OxylabsClient(BaseClient):
    """
    Async client for Oxylabs Web Scraping API.

    Usage:
        client = OxylabsClient()
        result = await client.scrape_url("https://example.com")
        if result:
            print(result.content)
        await client.close()
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        """
        Initialize Oxylabs client.

        Args:
            username: Oxylabs username (defaults to settings)
            password: Oxylabs password (defaults to settings)
            timeout: Request timeout in seconds (defaults to settings)
            max_retries: Maximum retry attempts (defaults to settings)
        """
        self.username = username or settings.oxylabs_username
        if not self.username:
            raise ValueError("Oxylabs username is required")

        if password:
            self.password = password
        elif settings.oxylabs_password:
            self.password = settings.oxylabs_password.get_secret_value()
        else:
            raise ValueError("Oxylabs password is required")

        # Create Basic Auth header
        credentials = f"{self.username}:{self.password}"
        self.auth_header = base64.b64encode(credentials.encode()).decode()

        super().__init__(
            timeout=timeout or settings.oxylabs_timeout,
            max_retries=max_retries or settings.oxylabs_max_retries,
        )

        logger.info("Oxylabs client initialized")

    def _get_base_url(self) -> str:
        return "https://realtime.oxylabs.io/v1"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Basic {self.auth_header}",
            "Content-Type": "application/json",
        }

    def _get_service_name(self) -> str:
        return "oxylabs"

    def _get_error_class(self) -> Type[ExternalAPIError]:
        return OxylabsAPIError

    async def scrape_url(
        self,
        url: str,
        geo_location: str = "United States",
        render_js: bool = True,
    ) -> Optional[ScrapeResult]:
        """
        Scrape a URL using Oxylabs API.

        Args:
            url: URL to scrape
            geo_location: Geographic location for the request
            render_js: Whether to render JavaScript (default: True)

        Returns:
            ScrapeResult with content, status_code, and final_url
            Returns None if scraping fails

        Raises:
            OxylabsAPIError: If the API request fails critically
        """
        logger.debug(
            "Scraping URL",
            url=url[:100],
            geo_location=geo_location,
        )

        payload: Dict[str, Any] = {
            "source": "universal",
            "url": url,
            "geo_location": geo_location,
        }

        if render_js:
            payload["render"] = "html"

        try:
            response = await self.post("/queries", json=payload)
            data = response.json()

            results = data.get("results", [])
            if not results:
                logger.warning(
                    "No results in Oxylabs response",
                    url=url[:100],
                )
                return None

            result = results[0]
            content = result.get("content", "")
            status_code = result.get("status_code", 0)
            final_url = result.get("url") or url

            logger.debug(
                "Scrape completed",
                url=url[:100],
                final_url=final_url[:100] if final_url != url else "same",
                status_code=status_code,
                content_length=len(content) if content else 0,
            )

            return ScrapeResult(
                content=content,
                status_code=status_code,
                final_url=final_url,
            )

        except OxylabsAPIError:
            # Re-raise API errors
            raise
        except Exception as e:
            logger.warning(
                "Scrape failed",
                url=url[:100],
                error=str(e),
            )
            return None

    async def scrape_with_validation(
        self,
        url: str,
        min_content_length: int = 3500,
        geo_location: str = "United States",
    ) -> Optional[ScrapeResult]:
        """
        Scrape a URL and validate the content meets minimum requirements.

        Args:
            url: URL to scrape
            min_content_length: Minimum content length in bytes
            geo_location: Geographic location for the request

        Returns:
            ScrapeResult if successful and content meets requirements
            None otherwise
        """
        result = await self.scrape_url(url, geo_location)

        if not result:
            return None

        if not result.is_success:
            logger.debug(
                "Scrape returned non-success status",
                url=url[:100],
                status_code=result.status_code,
            )
            return None

        if len(result.content) < min_content_length:
            logger.debug(
                "Scraped content below minimum length",
                url=url[:100],
                content_length=len(result.content),
                min_required=min_content_length,
            )
            return None

        return result
