"""
FastAPI dependency injection for services and clients.

Provides singleton instances of services for use in API endpoints.
"""

from typing import AsyncGenerator, Optional

from fastapi import Depends

from src.clients.grok import GrokClient
from src.clients.oxylabs import OxylabsClient
from src.clients.serper import SerperClient
from src.core.logging import get_logger
from src.core.redis import RedisClient
from src.services.ai_analyzer import AIAnalyzerService
from src.services.enrichment import EnrichmentService
from src.services.scraper import ScraperService
from src.services.search import SearchService

logger = get_logger("dependencies")


# ==========================================================================
# Singleton instances (initialized on app startup)
# ==========================================================================

_serper_client: Optional[SerperClient] = None
_oxylabs_client: Optional[OxylabsClient] = None
_grok_client: Optional[GrokClient] = None
_enrichment_service: Optional[EnrichmentService] = None


# ==========================================================================
# Initialization and Cleanup
# ==========================================================================


async def init_services() -> None:
    """
    Initialize all services on application startup.

    Should be called from FastAPI lifespan event.
    """
    global _serper_client, _oxylabs_client, _grok_client, _enrichment_service

    logger.info("Initializing services")

    # Create API clients
    _serper_client = SerperClient()
    _oxylabs_client = OxylabsClient()
    _grok_client = GrokClient()

    # Create services
    search_service = SearchService(_serper_client)
    scraper_service = ScraperService(_oxylabs_client)
    ai_analyzer = AIAnalyzerService(_grok_client)

    # Create enrichment orchestrator
    _enrichment_service = EnrichmentService(
        search_service=search_service,
        scraper_service=scraper_service,
        ai_analyzer=ai_analyzer,
    )

    # Initialize Redis connection
    await RedisClient.get_instance()

    logger.info("Services initialized successfully")


async def cleanup_services() -> None:
    """
    Cleanup all services on application shutdown.

    Should be called from FastAPI lifespan event.
    """
    global _serper_client, _oxylabs_client, _grok_client, _enrichment_service

    logger.info("Cleaning up services")

    # Close enrichment service (which closes underlying services)
    if _enrichment_service:
        await _enrichment_service.close()
        _enrichment_service = None

    # Close remaining clients
    if _serper_client:
        await _serper_client.close()
        _serper_client = None

    if _oxylabs_client:
        await _oxylabs_client.close()
        _oxylabs_client = None

    if _grok_client:
        await _grok_client.close()
        _grok_client = None

    # Close Redis
    await RedisClient.close_instance()

    logger.info("Services cleaned up")


# ==========================================================================
# Dependency Providers
# ==========================================================================


async def get_enrichment_service() -> EnrichmentService:
    """
    Get the enrichment service instance.

    Raises:
        RuntimeError: If services are not initialized
    """
    if _enrichment_service is None:
        raise RuntimeError("Enrichment service not initialized. Call init_services() first.")
    return _enrichment_service


async def get_redis() -> RedisClient:
    """Get Redis client instance."""
    return await RedisClient.get_instance()


async def get_serper_client() -> SerperClient:
    """Get Serper client instance."""
    if _serper_client is None:
        raise RuntimeError("Serper client not initialized")
    return _serper_client


async def get_oxylabs_client() -> OxylabsClient:
    """Get Oxylabs client instance."""
    if _oxylabs_client is None:
        raise RuntimeError("Oxylabs client not initialized")
    return _oxylabs_client


async def get_grok_client() -> GrokClient:
    """Get Grok client instance."""
    if _grok_client is None:
        raise RuntimeError("Grok client not initialized")
    return _grok_client


# ==========================================================================
# Type aliases for FastAPI Depends
# ==========================================================================

# Use these in endpoint function signatures:
# async def enrich(service: EnrichmentServiceDep) -> EnrichmentResponse:
#     ...

EnrichmentServiceDep = EnrichmentService
RedisDep = RedisClient
