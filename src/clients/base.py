"""
Base HTTP client with retry logic, circuit breaker, and structured logging.

Features:
- Automatic retries with exponential backoff
- Circuit breaker pattern for failing services
- Structured logging for all requests
- Timeout handling
- Rate limiting support
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Type

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.exceptions import ExternalAPIError, TimeoutError
from src.core.logging import get_logger

logger = get_logger("http-client")


@dataclass
class CircuitBreakerState:
    """Tracks circuit breaker state for a service."""

    failure_count: int = 0
    last_failure_time: float = 0.0
    failure_times: list = field(default_factory=list)
    is_open: bool = False

    # Configuration
    failure_threshold: int = 10
    recovery_timeout: float = 60.0  # seconds
    failure_window: float = 60.0  # seconds - only count failures within this window

    def record_failure(self) -> bool:
        """
        Record a failure and check if circuit should open.

        Returns:
            True if circuit breaker is now open
        """
        now = time.time()

        # Remove old failures outside the window
        self.failure_times = [
            t for t in self.failure_times if now - t < self.failure_window
        ]

        # Add new failure
        self.failure_times.append(now)
        self.failure_count = len(self.failure_times)
        self.last_failure_time = now

        # Check if we should open the circuit
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(
                "Circuit breaker opened",
                failure_count=self.failure_count,
                threshold=self.failure_threshold,
            )
            return True

        return False

    def record_success(self) -> None:
        """Record a success and potentially close the circuit."""
        if self.failure_count > 0:
            logger.debug(
                "Success recorded, resetting failure count",
                previous_failures=self.failure_count,
            )
        self.failure_count = 0
        self.failure_times = []
        self.is_open = False

    def can_attempt(self) -> bool:
        """Check if we can attempt a request (circuit is closed or in half-open state)."""
        if not self.is_open:
            return True

        # Check if recovery timeout has passed (half-open state)
        now = time.time()
        if now - self.last_failure_time >= self.recovery_timeout:
            logger.info("Circuit breaker entering half-open state")
            return True

        return False


class BaseClient(ABC):
    """
    Base class for HTTP API clients with retry and circuit breaker support.

    Subclasses should implement:
    - _get_base_url() -> str
    - _get_headers() -> Dict[str, str]
    - _get_service_name() -> str
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff_multiplier: float = 2.0,
        circuit_breaker_threshold: int = 10,
        circuit_breaker_recovery: float = 60.0,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_multiplier = retry_backoff_multiplier

        # Circuit breaker
        self.circuit_breaker = CircuitBreakerState(
            failure_threshold=circuit_breaker_threshold,
            recovery_timeout=circuit_breaker_recovery,
        )

        # HTTP client (lazy initialization)
        self._client: Optional[httpx.AsyncClient] = None

        # Rate limiting
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time: float = 0.0
        self._min_request_interval: float = 0.0  # Set by subclasses if needed

    @abstractmethod
    def _get_base_url(self) -> str:
        """Return the base URL for this API."""
        pass

    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """Return headers for API requests."""
        pass

    @abstractmethod
    def _get_service_name(self) -> str:
        """Return the service name for logging."""
        pass

    @abstractmethod
    def _get_error_class(self) -> Type[ExternalAPIError]:
        """Return the exception class to use for errors."""
        pass

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _apply_rate_limit(self) -> None:
        """Apply rate limiting if configured."""
        if self._min_request_interval <= 0:
            return

        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self._min_request_interval:
                sleep_time = self._min_request_interval - elapsed
                await asyncio.sleep(sleep_time)
            self._last_request_time = time.time()

    def _should_retry(self, exception: Exception) -> bool:
        """Determine if an exception should trigger a retry."""
        if isinstance(exception, httpx.TimeoutException):
            return True
        if isinstance(exception, httpx.HTTPStatusError):
            # Retry on 429 (rate limit) and 5xx (server errors)
            return exception.response.status_code in (429, 500, 502, 503, 504)
        return False

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make an HTTP request with retry logic and circuit breaker.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL or path (will be joined with base URL)
            **kwargs: Additional arguments for httpx request

        Returns:
            httpx.Response

        Raises:
            ExternalAPIError: If request fails after retries
            TimeoutError: If request times out
        """
        service_name = self._get_service_name()

        # Check circuit breaker
        if not self.circuit_breaker.can_attempt():
            raise self._get_error_class()(
                message=f"{service_name} circuit breaker is open",
                status_code=503,
                details={"circuit_breaker": "open"},
            )

        # Build full URL if needed
        if not url.startswith("http"):
            url = f"{self._get_base_url().rstrip('/')}/{url.lstrip('/')}"

        # Apply rate limiting
        await self._apply_rate_limit()

        client = await self._get_client()

        # Add headers
        headers = {**self._get_headers(), **kwargs.pop("headers", {})}

        last_exception: Optional[Exception] = None

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
                reraise=True,
            ):
                with attempt:
                    try:
                        logger.debug(
                            "Making HTTP request",
                            service=service_name,
                            method=method,
                            url=url[:100],
                            attempt=attempt.retry_state.attempt_number,
                        )

                        response = await client.request(
                            method=method,
                            url=url,
                            headers=headers,
                            **kwargs,
                        )

                        # Check for error status codes
                        if response.status_code >= 400:
                            if response.status_code == 429:
                                # Rate limited - will retry
                                logger.warning(
                                    "Rate limited by API",
                                    service=service_name,
                                    status_code=429,
                                )
                                raise httpx.HTTPStatusError(
                                    message="Rate limited",
                                    request=response.request,
                                    response=response,
                                )
                            elif response.status_code >= 500:
                                # Server error - will retry
                                raise httpx.HTTPStatusError(
                                    message=f"Server error: {response.status_code}",
                                    request=response.request,
                                    response=response,
                                )

                        # Success - record it
                        self.circuit_breaker.record_success()

                        logger.debug(
                            "HTTP request successful",
                            service=service_name,
                            status_code=response.status_code,
                        )

                        return response

                    except httpx.TimeoutException as e:
                        last_exception = e
                        logger.warning(
                            "Request timeout",
                            service=service_name,
                            url=url[:100],
                            attempt=attempt.retry_state.attempt_number,
                        )
                        raise

                    except httpx.HTTPStatusError as e:
                        last_exception = e
                        if e.response.status_code not in (429, 500, 502, 503, 504):
                            # Non-retryable error
                            raise
                        raise

        except RetryError:
            # All retries exhausted
            self.circuit_breaker.record_failure()

            if isinstance(last_exception, httpx.TimeoutException):
                raise TimeoutError(
                    message=f"{service_name} request timed out after {self.max_retries} attempts",
                    operation=f"{method} {url[:50]}",
                    timeout_seconds=self.timeout,
                )

            raise self._get_error_class()(
                message=f"{service_name} request failed after {self.max_retries} attempts",
                status_code=getattr(
                    getattr(last_exception, "response", None), "status_code", None
                ),
                details={"last_error": str(last_exception)},
            )

        except httpx.HTTPStatusError as e:
            # Non-retryable HTTP error
            self.circuit_breaker.record_failure()
            raise self._get_error_class()(
                message=f"{service_name} request failed with status {e.response.status_code}",
                status_code=e.response.status_code,
                details={"response_text": e.response.text[:500]},
            )

        except Exception as e:
            # Unexpected error
            self.circuit_breaker.record_failure()
            logger.error(
                "Unexpected error in HTTP request",
                service=service_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise self._get_error_class()(
                message=f"{service_name} request failed: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request."""
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request."""
        return await self._request("POST", url, **kwargs)

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status."""
        return {
            "is_open": self.circuit_breaker.is_open,
            "failure_count": self.circuit_breaker.failure_count,
            "threshold": self.circuit_breaker.failure_threshold,
            "can_attempt": self.circuit_breaker.can_attempt(),
        }
