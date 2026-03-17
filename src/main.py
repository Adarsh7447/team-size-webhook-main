"""
Team Size Webhook API - FastAPI Application Entry Point.

High-throughput webhook API for enriching real estate agent data
with team size information using AI-powered analysis.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import cleanup_services, init_services
from src.api.middleware import setup_middleware
from src.api.v1.router import router as v1_router
from src.api.v1.endpoints.health import router as health_router
from src.config.settings import settings
from src.core.logging import get_logger

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler for startup and shutdown events.

    Initializes and cleans up services, connections, and resources.
    """
    # Startup
    logger.info(
        "Starting Team Size Webhook API",
        host=settings.host,
        port=settings.port,
        debug=settings.debug,
    )

    # Validate API keys
    api_key_errors = settings.validate_api_keys()
    if api_key_errors:
        for key, msg in api_key_errors.items():
            logger.warning(f"Missing API key: {key} - {msg}")
    else:
        logger.info("All API keys configured")

    # Initialize services
    await init_services()

    logger.info("Application startup complete")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down Team Size Webhook API")
    await cleanup_services()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title="Team Size Webhook API",
        description="""
        High-throughput webhook API for enriching real estate agent data
        with team size information using AI-powered analysis.

        ## Features

        - **Synchronous Mode**: Direct enrichment for immediate results (default)
        - **Asynchronous Mode**: Task queue for high-throughput processing (4000+ req/min)
        - **Rate Limiting**: Redis-based distributed rate limiting
        - **AI Analysis**: Grok AI for intelligent team size estimation

        ## Endpoints

        - `POST /api/v1/enrich` - Synchronous enrichment (for n8n)
        - `POST /api/v1/enrich/async` - Asynchronous enrichment
        - `GET /api/v1/enrich/tasks/{task_id}` - Check async task status
        - `GET /health` - Basic health check
        - `GET /ready` - Full readiness check

        ## Rate Limits

        Default: 100 requests per 60 seconds per IP.
        Configure via RATE_LIMIT_REQUESTS and RATE_LIMIT_WINDOW_SECONDS environment variables.
        """,
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Setup custom middleware (rate limiting, error handling, request ID)
    setup_middleware(app)

    # Include API routers
    app.include_router(v1_router)

    # Include health endpoints at root level
    app.include_router(health_router)

    # Root endpoint
    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint with API information."""
        return {
            "service": "team-size-webhook",
            "version": "1.0.0",
            "docs": "/docs" if settings.debug else "disabled",
            "health": "/health",
        }

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=1 if settings.debug else settings.workers,
        log_level=settings.log_level.lower(),
    )
