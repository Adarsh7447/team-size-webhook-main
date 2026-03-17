"""
Health check endpoints for monitoring and load balancer probes.

Provides liveness and readiness checks for Kubernetes/Docker deployments.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.dependencies import get_redis
from src.config.settings import settings
from src.core.logging import get_logger
from src.core.redis import RedisClient

logger = get_logger("health-endpoints")

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Health check",
    description="Basic health check endpoint for load balancer probes",
    response_description="Health status",
)
async def health_check() -> Dict[str, str]:
    """
    Basic health check - returns OK if the service is running.

    This is a lightweight check that doesn't verify dependencies.
    Use /ready for a full readiness check.
    """
    return {"status": "healthy"}


@router.get(
    "/ready",
    summary="Readiness check",
    description="Full readiness check including all dependencies",
    response_description="Detailed readiness status",
)
async def readiness_check(
    redis: RedisClient = Depends(get_redis),
) -> Dict[str, Any]:
    """
    Comprehensive readiness check that verifies all dependencies.

    Returns detailed status for:
    - Redis connection
    - API configuration validity
    """
    checks = {}
    all_healthy = True

    # Check Redis
    try:
        redis_health = await redis.health_check()
        checks["redis"] = redis_health
        if redis_health.get("status") != "healthy":
            all_healthy = False
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check API key configuration
    api_key_errors = settings.validate_api_keys()
    if api_key_errors:
        checks["api_keys"] = {
            "status": "unhealthy",
            "missing": list(api_key_errors.keys()),
        }
        all_healthy = False
    else:
        checks["api_keys"] = {"status": "healthy", "configured": True}

    # Overall status
    overall_status = "healthy" if all_healthy else "unhealthy"

    return {
        "status": overall_status,
        "checks": checks,
        "version": "1.0.0",
        "environment": "production" if not settings.debug else "development",
    }


@router.get(
    "/info",
    summary="Service information",
    description="Get service configuration and version info",
    response_description="Service information",
)
async def service_info() -> Dict[str, Any]:
    """
    Return service information and configuration.

    Does not expose sensitive data like API keys.
    """
    return {
        "service": "team-size-webhook",
        "version": "1.0.0",
        "environment": "production" if not settings.debug else "development",
        "config": {
            "rate_limit_enabled": settings.rate_limit_enabled,
            "rate_limit_requests": settings.rate_limit_requests,
            "rate_limit_window_seconds": settings.rate_limit_window_seconds,
            "async_processing_enabled": settings.async_processing_enabled,
            "max_concurrent_requests": settings.max_concurrent_requests,
            "grok_model": settings.grok_model_name,
        },
    }
