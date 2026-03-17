"""
API v1 router that combines all endpoint routers.
"""

from fastapi import APIRouter

from src.api.v1.endpoints.enrichment import router as enrichment_router

# Create the main v1 router
router = APIRouter(prefix="/api/v1")

# Include endpoint routers
router.include_router(enrichment_router)
# Note: Health endpoints are included at root level in main.py
