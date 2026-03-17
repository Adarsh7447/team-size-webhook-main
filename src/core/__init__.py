"""Core utilities and infrastructure."""

from src.core.exceptions import (
    AnalysisFailedError,
    BlockedDomainError,
    EnrichmentError,
    ExternalAPIError,
    GrokAPIError,
    GrokCreditExhaustedError,
    LowQualityContentError,
    NoSearchQueryError,
    NoWebsiteFoundError,
    OxylabsAPIError,
    RateLimitExceededError,
    RequestValidationError,
    ScrapingFailedError,
    SerperAPIError,
    TeamSizeAPIError,
    TimeoutError,
)
from src.core.logging import (
    LogContext,
    get_agent_id,
    get_logger,
    get_request_id,
    set_agent_id,
    set_request_id,
    setup_logging,
)

__all__ = [
    # Exceptions
    "TeamSizeAPIError",
    "RequestValidationError",
    "RateLimitExceededError",
    "ExternalAPIError",
    "SerperAPIError",
    "OxylabsAPIError",
    "GrokAPIError",
    "GrokCreditExhaustedError",
    "EnrichmentError",
    "NoWebsiteFoundError",
    "NoSearchQueryError",
    "BlockedDomainError",
    "ScrapingFailedError",
    "LowQualityContentError",
    "AnalysisFailedError",
    "TimeoutError",
    # Logging
    "setup_logging",
    "get_logger",
    "LogContext",
    "get_request_id",
    "set_request_id",
    "get_agent_id",
    "set_agent_id",
]
