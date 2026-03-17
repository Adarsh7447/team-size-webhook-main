"""
Link extractor service for parsing HTML and extracting URLs.

Extracts and normalizes all links from HTML content.
"""

from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.core.logging import get_logger

logger = get_logger("link-extractor")


class LinkExtractor:
    """
    Service for extracting and filtering links from HTML content.

    Usage:
        extractor = LinkExtractor()
        links = extractor.extract_all_links(html, "https://example.com")
    """

    # Prefixes to skip
    SKIP_PREFIXES = (
        "#",
        "mailto:",
        "tel:",
        "javascript:",
        "data:",
        "ftp:",
    )

    # File extensions to skip
    SKIP_EXTENSIONS = (
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
        ".rar",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".svg",
        ".webp",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
    )

    def extract_all_links(
        self,
        html: str,
        base_url: str,
        include_external: bool = True,
    ) -> List[str]:
        """
        Extract all valid links from HTML content.

        Args:
            html: HTML content to parse
            base_url: Base URL for resolving relative links
            include_external: Whether to include external domain links

        Returns:
            List of unique, normalized URLs
        """
        if not html:
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
            base_domain = self._extract_domain(base_url)

            links: List[str] = []
            seen: Set[str] = set()

            for tag in soup.find_all("a", href=True):
                href = tag.get("href", "").strip()

                if not href:
                    continue

                # Skip non-http links
                if any(href.startswith(prefix) for prefix in self.SKIP_PREFIXES):
                    continue

                # Resolve relative URLs
                full_url = urljoin(base_url, href)

                # Skip file downloads
                if any(full_url.lower().endswith(ext) for ext in self.SKIP_EXTENSIONS):
                    continue

                # Check external links
                if not include_external:
                    link_domain = self._extract_domain(full_url)
                    if link_domain and base_domain and link_domain != base_domain:
                        continue

                # Normalize and deduplicate
                normalized = self._normalize_url(full_url)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    links.append(normalized)

            logger.debug(
                "Extracted links",
                base_url=base_url[:50],
                total_links=len(links),
            )

            return links

        except Exception as e:
            logger.warning(
                "Failed to extract links",
                error=str(e),
                base_url=base_url[:50],
            )
            return []

    def extract_internal_links(
        self,
        html: str,
        base_url: str,
    ) -> List[str]:
        """
        Extract only internal (same-domain) links.

        Args:
            html: HTML content to parse
            base_url: Base URL for resolving relative links

        Returns:
            List of internal URLs only
        """
        return self.extract_all_links(html, base_url, include_external=False)

    def filter_team_page_candidates(
        self,
        links: List[str],
        max_links: int = 100,
    ) -> List[str]:
        """
        Filter links to those most likely to be team pages.

        Prioritizes URLs containing team-related keywords.

        Args:
            links: List of URLs to filter
            max_links: Maximum number of links to return

        Returns:
            Filtered and prioritized list of URLs
        """
        # Keywords that indicate team pages (in priority order)
        team_keywords = [
            "/team",
            "/our-team",
            "/meet-the-team",
            "/meet-our-team",
            "/agents",
            "/our-agents",
            "/staff",
            "/people",
            "/about",
            "/about-us",
            "/contact",
        ]

        # Score each link
        scored_links = []
        for link in links:
            link_lower = link.lower()
            score = 0

            for i, keyword in enumerate(team_keywords):
                if keyword in link_lower:
                    # Higher score for earlier keywords (more specific)
                    score = len(team_keywords) - i
                    break

            scored_links.append((score, link))

        # Sort by score (descending), then by URL length (shorter first)
        scored_links.sort(key=lambda x: (-x[0], len(x[1])))

        # Return just the URLs, limited to max_links
        return [link for _, link in scored_links[:max_links]]

    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract the domain from a URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix for consistency
            if domain.startswith("www."):
                domain = domain[4:]
            return domain or None
        except Exception:
            return None

    def _normalize_url(self, url: str) -> Optional[str]:
        """
        Normalize a URL for comparison.

        - Removes trailing slashes
        - Removes fragments
        - Lowercases the domain
        """
        try:
            parsed = urlparse(url)

            # Rebuild URL without fragment
            normalized = f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path}"

            # Add query string if present
            if parsed.query:
                normalized += f"?{parsed.query}"

            # Remove trailing slash (except for root)
            if normalized.endswith("/") and len(parsed.path) > 1:
                normalized = normalized[:-1]

            return normalized
        except Exception:
            return None


# Global instance for convenience
link_extractor = LinkExtractor()
