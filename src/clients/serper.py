"""
Serper API client for Google search.

Serper provides a simple API for Google search results.
https://serper.dev/
"""

from typing import Any, Dict, List, Optional, Type

from src.clients.base import BaseClient
from src.config.settings import settings
from src.core.exceptions import ExternalAPIError, SerperAPIError
from src.core.logging import get_logger

logger = get_logger("serper-client")


class SerperClient(BaseClient):
    """
    Async client for Serper Google Search API.

    Usage:
        client = SerperClient()
        results = await client.search("John Smith Real Estate Austin TX")
        await client.close()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        """
        Initialize Serper client.

        Args:
            api_key: Serper API key (defaults to settings)
            timeout: Request timeout in seconds (defaults to settings)
            max_retries: Maximum retry attempts (defaults to settings)
        """
        if api_key:
            self.api_key = api_key
        elif settings.serper_api_key:
            self.api_key = settings.serper_api_key.get_secret_value()
        else:
            raise ValueError("Serper API key is required")

        super().__init__(
            timeout=timeout or settings.serper_timeout,
            max_retries=max_retries or settings.serper_max_retries,
        )

        logger.info("Serper client initialized")

    def _get_base_url(self) -> str:
        return "https://google.serper.dev"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    def _get_service_name(self) -> str:
        return "serper"

    def _get_error_class(self) -> Type[ExternalAPIError]:
        return SerperAPIError

    async def search(
        self,
        query: str,
        location: str = "us",
        num_results: int = 10,
    ) -> Dict[str, Any]:
        """
        Perform a Google search via Serper API.

        Args:
            query: Search query string
            location: Geographic location code (default: "us")
            num_results: Number of results to return (default: 10)

        Returns:
            Dict containing search results with 'organic' key

        Raises:
            SerperAPIError: If the search fails
        """
        logger.debug(
            "Performing search",
            query=query[:50],
            location=location,
        )

        payload = {
            "q": query,
            "gl": location,
            "num": num_results,
        }

        response = await self.post("/search", json=payload)

        try:
            data = response.json()
        except Exception as e:
            raise SerperAPIError(
                message=f"Failed to parse Serper response: {e}",
                details={"response_text": response.text[:500]},
            )

        organic_count = len(data.get("organic", []))
        logger.debug(
            "Search completed",
            query=query[:50],
            results_count=organic_count,
        )

        return data

    async def search_places(
        self,
        query: str,
        location: str = "us",
    ) -> Dict[str, Any]:
        """
        Search for places/businesses via Serper API.

        This is an alias for search() to maintain compatibility
        with the original implementation.

        Args:
            query: Search query string
            location: Geographic location code (default: "us")

        Returns:
            Dict containing search results
        """
        return await self.search(query, location)

    def extract_organic_results(
        self,
        search_results: Dict[str, Any],
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Extract organic search results from Serper response.

        Args:
            search_results: Raw Serper API response
            max_results: Maximum number of results to return

        Returns:
            List of organic search result dictionaries
        """
        organic = search_results.get("organic", [])
        return organic[:max_results]

    def has_results(self, search_results: Dict[str, Any]) -> bool:
        """Check if search results contain any organic results."""
        return bool(search_results.get("organic"))
