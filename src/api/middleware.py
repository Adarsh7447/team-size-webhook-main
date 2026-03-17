"""
FastAPI middleware for request processing.

Provides:
- Redis-based distributed rate limiting
- Global error handling
- Request ID tracking
"""

import time
import uuid
from typing import Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.settings import settings
from src.core.exceptions import TeamSizeAPIError
from src.core.logging import get_logger, set_request_id
from src.core.redis import RedisClient

logger = get_logger("middleware")


# ==========================================================================
# Rate Limiter Middleware
# ==========================================================================


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Redis-based distributed rate limiting middleware.

    Features:
    - Sliding window rate limiting
    - Per-IP tracking
    - Configurable limits
    - Returns standard rate limit headers
    """

    def __init__(
        self,
        app: FastAPI,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
        enabled: Optional[bool] = None,
        exclude_paths: Optional[list[str]] = None,
    ):
        """
        Initialize rate limiter.

        Args:
            app: FastAPI application
            max_requests: Maximum requests per window (defaults to settings)
            window_seconds: Time window in seconds (defaults to settings)
            enabled: Whether rate limiting is enabled (defaults to settings)
            exclude_paths: Paths to exclude from rate limiting
        """
        super().__init__(app)
        self.max_requests = max_requests or settings.rate_limit_requests
        self.window_seconds = window_seconds or settings.rate_limit_window_seconds
        self.enabled = enabled if enabled is not None else settings.rate_limit_enabled
        self.exclude_paths = exclude_paths or ["/health", "/ready", "/docs", "/openapi.json"]
        self._redis: Optional[RedisClient] = None

    async def _get_redis(self) -> RedisClient:
        """Get Redis client instance (lazy initialization)."""
        if self._redis is None:
            self._redis = await RedisClient.get_instance()
        return self._redis

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request."""
        # Check for forwarded headers (for proxy/load balancer)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client
        if request.client:
            return request.client.host

        return "unknown"

    def _should_skip(self, request: Request) -> bool:
        """Check if request should skip rate limiting."""
        return request.url.path in self.exclude_paths

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through rate limiter."""
        # Skip if disabled or excluded path
        if not self.enabled or self._should_skip(request):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        rate_limit_key = f"ratelimit:ip:{client_ip}"

        try:
            redis = await self._get_redis()

            # Check rate limit
            allowed, current, remaining, reset = await redis.rate_limit_sliding_window(
                key=rate_limit_key,
                max_requests=self.max_requests,
                window_seconds=self.window_seconds,
            )

            # Add rate limit headers to response
            response = await call_next(request) if allowed else None

            if response is None:
                # Rate limit exceeded
                logger.warning(
                    "Rate limit exceeded",
                    client_ip=client_ip,
                    current=current,
                    limit=self.max_requests,
                )

                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": f"Too many requests. Limit: {self.max_requests} per {self.window_seconds}s",
                        "retry_after": reset,
                    },
                )

            # Add rate limit headers
            response.headers["X-RateLimit-Limit"] = str(self.max_requests)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset)

            return response

        except Exception as e:
            # On Redis failure, allow request to proceed
            logger.error("Rate limiter error, allowing request", error=str(e))
            return await call_next(request)


# ==========================================================================
# Error Handler Middleware
# ==========================================================================


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Global error handling middleware.

    Catches all exceptions and returns consistent JSON error responses.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with error handling."""
        try:
            return await call_next(request)

        except TeamSizeAPIError as e:
            logger.error(
                "API error",
                error_code=e.error_code,
                message=e.message,
                path=request.url.path,
            )

            # Map error codes to HTTP status codes
            status_codes = {
                "VALIDATION_ERROR": 400,
                "NOT_FOUND": 404,
                "RATE_LIMIT_EXCEEDED": 429,
                "INTERNAL_ERROR": 500,
                "GROK_API_ERROR": 502,
                "SERPER_API_ERROR": 502,
                "OXYLABS_API_ERROR": 502,
            }

            status_code = status_codes.get(e.error_code, 500)

            return JSONResponse(
                status_code=status_code,
                content={
                    "error": e.error_code,
                    "message": e.message,
                    "details": e.details,
                },
            )

        except Exception as e:
            logger.exception("Unhandled exception", path=request.url.path)

            return JSONResponse(
                status_code=500,
                content={
                    "error": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "details": {"error": str(e)} if settings.debug else {},
                },
            )


# ==========================================================================
# Request ID Middleware
# ==========================================================================


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track requests with unique IDs.

    Adds X-Request-ID header to all responses and sets it in logging context.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with ID tracking."""
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Set in logging context
        set_request_id(request_id)

        # Store in request state
        request.state.request_id = request_id

        # Log request
        start_time = time.time()

        response = await call_next(request)

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        # Log response
        logger.info(
            "Request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return response


# ==========================================================================
# Middleware Setup Function
# ==========================================================================


def setup_middleware(app: FastAPI) -> None:
    """
    Configure all middleware for the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    # Order matters: first added = outermost (processed first on request, last on response)

    # 1. Request ID tracking (outermost - runs first)
    app.add_middleware(RequestIDMiddleware)

    # 2. Error handling (catches errors from downstream middleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # 3. Rate limiting (innermost - runs last before route)
    app.add_middleware(RateLimiterMiddleware)

    logger.info(
        "Middleware configured",
        rate_limit_enabled=settings.rate_limit_enabled,
        rate_limit_requests=settings.rate_limit_requests,
        rate_limit_window=settings.rate_limit_window_seconds,
    )
