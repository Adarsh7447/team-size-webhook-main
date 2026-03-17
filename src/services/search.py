"""
Search service for finding agent websites.

Wraps the Serper client with business logic for building search queries
and processing results.
"""

import re
from typing import Any, Dict, List, Optional

from src.clients.serper import SerperClient
from src.core.exceptions import NoSearchQueryError, SerperAPIError
from src.core.logging import get_logger
from src.schemas.internal import AgentData

logger = get_logger("search-service")


class SearchService:
    """
    Service for searching for agent websites.

    Handles query building, search execution, and result processing.

    Usage:
        service = SearchService(serper_client)
        results = await service.search_for_agent(agent_data)
    """

    def __init__(self, serper_client: SerperClient):
        """
        Initialize search service.

        Args:
            serper_client: Configured Serper API client
        """
        self.serper = serper_client

    async def search_for_agent(
        self,
        agent: AgentData,
    ) -> Optional[Dict[str, Any]]:
        """
        Search for an agent's website using multiple query strategies.

        Tries different query combinations until results are found.

        Args:
            agent: Agent data to search for

        Returns:
            Search results dict with 'organic' key, or None if no results

        Raises:
            NoSearchQueryError: If no valid query can be built
            SerperAPIError: If all searches fail
        """
        queries = self.build_search_queries(agent)

        if not queries:
            raise NoSearchQueryError(
                message="Cannot build search query - missing required data",
                details={
                    "has_name": bool(agent.full_name),
                    "has_org": bool(agent.primary_organization),
                    "has_email": bool(agent.primary_email),
                },
            )

        last_error: Optional[Exception] = None

        for query in queries:
            try:
                logger.debug(
                    "Executing search query",
                    query=query[:50],
                    agent_id=agent.agent_id,
                )

                results = await self.serper.search(query)

                if self.serper.has_results(results):
                    logger.debug(
                        "Search returned results",
                        query=query[:50],
                        result_count=len(results.get("organic", [])),
                    )
                    return results

                logger.debug(
                    "Search returned no results",
                    query=query[:50],
                )

            except SerperAPIError as e:
                last_error = e
                logger.warning(
                    "Search query failed",
                    query=query[:50],
                    error=str(e),
                )
                continue

        # If we got here, no queries returned results
        if last_error:
            raise last_error

        return None

    def build_search_queries(self, agent: AgentData) -> List[str]:
        """
        Build a list of search queries to try for an agent.

        Queries are ordered by likelihood of finding good results.

        Args:
            agent: Agent data to build queries from

        Returns:
            List of search query strings
        """
        queries = []

        full_name = agent.full_name
        org = self._clean_organization_name(agent.primary_organization)
        email = agent.primary_email

        # Strategy 1: Name + Organization (most specific)
        if full_name and org:
            query = self._normalize_query(f"{full_name} {org}")
            if query:
                queries.append(query)

        # Strategy 2: Name + Email
        if full_name and email:
            query = self._normalize_query(f"{full_name} {email}")
            if query:
                queries.append(query)

        # Deduplicate while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)

        return unique_queries

    def _clean_organization_name(self, org: Optional[str]) -> Optional[str]:
        """
        Clean an organization name for search.

        Removes common suffixes and normalizes formatting.
        """
        if not org:
            return None

        org = str(org).strip()

        # Remove common patterns that might confuse search
        patterns_to_remove = [
            r"\s*\(.*?\)",  # Parenthetical content
            r"\s*-\s*Team\s*$",
            r"\s*-\s*Group\s*$",
            r"\s*\|\s*.*$",  # Pipe and everything after
        ]

        for pattern in patterns_to_remove:
            org = re.sub(pattern, "", org, flags=re.IGNORECASE)

        # Normalize whitespace
        org = re.sub(r"\s+", " ", org).strip()

        return org if org else None

    def _normalize_query(self, query: str) -> Optional[str]:
        """
        Normalize a search query string.

        Removes extra whitespace and validates minimum length.
        """
        if not query:
            return None

        # Normalize whitespace
        query = re.sub(r"\s+", " ", query).strip()

        # Require minimum length
        if len(query) < 5:
            return None

        return query

    def extract_urls_from_results(
        self,
        results: Dict[str, Any],
        max_results: int = 10,
    ) -> List[str]:
        """
        Extract URLs from search results.

        Args:
            results: Serper API response
            max_results: Maximum number of URLs to return

        Returns:
            List of URLs from organic results
        """
        urls = []
        organic = results.get("organic", [])

        for result in organic[:max_results]:
            url = result.get("link") or result.get("url")
            if url:
                urls.append(url)

        return urls

    async def close(self):
        """Close the underlying client."""
        await self.serper.close()
