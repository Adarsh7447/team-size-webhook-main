"""
Custom exceptions for the Team Size Webhook API.

Exception hierarchy:
- TeamSizeAPIError (base)
  - ValidationError
  - ExternalAPIError
    - SerperAPIError
    - OxylabsAPIError
    - GrokAPIError
  - RateLimitExceededError
  - EnrichmentError
    - NoWebsiteFoundError
    - ScrapingFailedError
    - AnalysisFailedError
"""

from typing import Any, Dict, Optional


class TeamSizeAPIError(Exception):
    """Base exception for all Team Size API errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API response."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# Validation Errors
# =============================================================================


class RequestValidationError(TeamSizeAPIError):
    """Raised when request validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details=details,
        )


# =============================================================================
# Rate Limiting Errors
# =============================================================================


class RateLimitExceededError(TeamSizeAPIError):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
    ):
        details = {}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            details=details,
        )
        self.retry_after = retry_after


# =============================================================================
# External API Errors
# =============================================================================


class ExternalAPIError(TeamSizeAPIError):
    """Base exception for external API errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "EXTERNAL_API_ERROR",
        service: str = "unknown",
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        details["service"] = service
        if status_code:
            details["status_code"] = status_code
        super().__init__(
            message=message,
            error_code=error_code,
            details=details,
        )
        self.service = service
        self.status_code = status_code


class SerperAPIError(ExternalAPIError):
    """Raised when Serper API call fails."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="SERPER_API_ERROR",
            service="serper",
            status_code=status_code,
            details=details,
        )


class OxylabsAPIError(ExternalAPIError):
    """Raised when Oxylabs API call fails."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="OXYLABS_API_ERROR",
            service="oxylabs",
            status_code=status_code,
            details=details,
        )


class GrokAPIError(ExternalAPIError):
    """Raised when Grok AI API call fails."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="GROK_API_ERROR",
            service="grok",
            status_code=status_code,
            details=details,
        )


class GrokCreditExhaustedError(GrokAPIError):
    """Raised when Grok API credits are exhausted."""

    def __init__(self, message: str = "Grok API credits exhausted"):
        super().__init__(
            message=message,
            status_code=402,
            details={"reason": "credit_exhausted"},
        )
        self.error_code = "GROK_CREDIT_EXHAUSTED"


# =============================================================================
# Enrichment Process Errors
# =============================================================================


class EnrichmentError(TeamSizeAPIError):
    """Base exception for enrichment process errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "ENRICHMENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            details=details,
        )


class NoWebsiteFoundError(EnrichmentError):
    """Raised when no website can be found for the agent."""

    def __init__(
        self,
        message: str = "Could not find a valid website for this agent",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="NO_WEBSITE_FOUND",
            details=details,
        )


class NoSearchQueryError(EnrichmentError):
    """Raised when no search query can be built from agent data."""

    def __init__(
        self,
        message: str = "Insufficient data to build search query",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="NO_SEARCH_QUERY",
            details=details,
        )


class BlockedDomainError(EnrichmentError):
    """Raised when the selected URL is from a blocked domain."""

    def __init__(
        self,
        domain: str,
        message: Optional[str] = None,
    ):
        super().__init__(
            message=message or f"Domain is blocked: {domain}",
            error_code="BLOCKED_DOMAIN",
            details={"domain": domain},
        )


class ScrapingFailedError(EnrichmentError):
    """Raised when web scraping fails."""

    def __init__(
        self,
        url: str,
        reason: str = "Unknown error",
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        details["url"] = url
        details["reason"] = reason
        super().__init__(
            message=f"Failed to scrape URL: {reason}",
            error_code="SCRAPE_FAILED",
            details=details,
        )


class LowQualityContentError(EnrichmentError):
    """Raised when scraped content is low quality (404, too small, etc.)."""

    def __init__(
        self,
        url: str,
        reason: str = "Content did not meet quality threshold",
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        details["url"] = url
        details["reason"] = reason
        super().__init__(
            message=f"Low quality content: {reason}",
            error_code="LOW_QUALITY_CONTENT",
            details=details,
        )


class AnalysisFailedError(EnrichmentError):
    """Raised when AI analysis fails."""

    def __init__(
        self,
        message: str = "AI analysis failed to determine team size",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code="ANALYSIS_FAILED",
            details=details,
        )


# =============================================================================
# Timeout Errors
# =============================================================================


class TimeoutError(TeamSizeAPIError):
    """Raised when an operation times out."""

    def __init__(
        self,
        message: str = "Operation timed out",
        operation: str = "unknown",
        timeout_seconds: Optional[int] = None,
    ):
        details = {"operation": operation}
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds
        super().__init__(
            message=message,
            error_code="TIMEOUT",
            details=details,
        )
