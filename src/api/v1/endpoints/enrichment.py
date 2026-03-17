"""
Enrichment API endpoints.

Provides synchronous and asynchronous enrichment endpoints for agent data.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_enrichment_service
from src.config.settings import settings
from src.core.logging import get_logger
from src.schemas.requests import EnrichmentRequest
from src.schemas.responses import (
    AsyncEnrichmentResponse,
    EnrichmentResponse,
    TaskStatusResponse,
)
from src.services.enrichment import EnrichmentService
from src.worker.tasks import (
    enrich_agent_priority,
    enrich_agent_task,
    get_task_result,
    get_task_status,
    revoke_task,
)

logger = get_logger("enrichment-endpoints")

router = APIRouter(prefix="/enrich", tags=["Enrichment"])


@router.post(
    "",
    response_model=EnrichmentResponse,
    summary="Enrich agent data (synchronous)",
    description="""
    Synchronously enrich agent data with team information.

    This endpoint waits for the full enrichment process to complete before
    returning. Typical processing time is 30-60 seconds.

    **Use this endpoint for:**
    - n8n webhooks that need immediate results
    - Single agent enrichments
    - Testing and debugging

    **For high throughput**, use POST /api/v1/enrich/async instead.
    """,
    response_description="Enriched agent data with team information",
)
async def enrich_agent(
    request: EnrichmentRequest,
    service: EnrichmentService = Depends(get_enrichment_service),
) -> EnrichmentResponse:
    """
    Synchronously enrich agent data.

    Performs the full enrichment workflow:
    1. Search for agent's website
    2. Select and scrape homepage
    3. Find and scrape team page
    4. Analyze team size with AI
    5. Extract team/brokerage names
    6. Detect technologies/CRMs

    Args:
        request: Agent data to enrich

    Returns:
        Complete enrichment response with team data
    """
    logger.info(
        "Received sync enrichment request",
        agent_id=request.agent_id,
        list_name=request.list_name,
    )

    response = await service.enrich(request)

    return response


@router.post(
    "/async",
    response_model=AsyncEnrichmentResponse,
    summary="Enrich agent data (asynchronous)",
    description="""
    Asynchronously enrich agent data via Celery task queue.

    Returns immediately with a task ID. Use GET /api/v1/enrich/tasks/{task_id}
    to check status and retrieve results.

    **Use this endpoint for:**
    - High throughput scenarios (4000+ requests/minute)
    - Batch processing
    - Non-blocking operations

    **Note:** Requires Redis and Celery workers to be running.
    """,
    response_description="Task ID for tracking the enrichment request",
)
async def enrich_agent_async(
    request: EnrichmentRequest,
    priority: bool = Query(
        default=False,
        description="Use priority queue for faster processing",
    ),
) -> AsyncEnrichmentResponse:
    """
    Asynchronously enrich agent data via Celery.

    Queues the enrichment task and returns immediately with a task ID.
    Poll the /tasks/{task_id} endpoint to get results.

    Args:
        request: Agent data to enrich
        priority: Whether to use priority queue

    Returns:
        Task ID and status URL for tracking
    """
    if not settings.async_processing_enabled:
        raise HTTPException(
            status_code=400,
            detail="Async processing is not enabled. Set ASYNC_PROCESSING_ENABLED=true",
        )

    logger.info(
        "Received async enrichment request",
        agent_id=request.agent_id,
        priority=priority,
    )

    # Convert request to dict for Celery serialization
    request_data = request.model_dump()

    # Submit task to appropriate queue
    if priority:
        task = enrich_agent_priority.delay(request_data)
    else:
        task = enrich_agent_task.delay(request_data)

    logger.info(
        "Enrichment task queued",
        task_id=task.id,
        agent_id=request.agent_id,
        priority=priority,
    )

    return AsyncEnrichmentResponse(
        task_id=task.id,
        status="queued",
        status_url=f"/api/v1/enrich/tasks/{task.id}",
        agent_id=request.agent_id,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get task status",
    description="""
    Get the status and result of an async enrichment task.

    Returns current status and, if complete, the full enrichment result.
    """,
    response_description="Task status and optional result",
)
async def get_enrichment_task(
    task_id: str,
) -> TaskStatusResponse:
    """
    Get the status of an async enrichment task.

    Args:
        task_id: Celery task ID from async enrichment request

    Returns:
        Task status and result if complete

    Raises:
        HTTPException: If task ID is invalid or not found
    """
    status_info = get_task_status(task_id)

    # Check if task exists: If status is PENDING and no metadata exists,
    # the task was likely never created
    if status_info["status"] == "PENDING" and not status_info.get("task_exists"):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "TASK_NOT_FOUND",
                "message": f"Task with ID '{task_id}' does not exist or has expired",
                "task_id": task_id,
            },
        )

    response = TaskStatusResponse(
        task_id=task_id,
        status=status_info["status"].lower(),
        ready=status_info["ready"],
    )

    # If task is complete, include result
    if status_info["ready"]:
        result = get_task_result(task_id)
        if result:
            response.result = EnrichmentResponse.model_validate(result)

    # If task is in progress, include progress info
    if status_info.get("info"):
        response.progress = status_info["info"]

    return response


@router.delete(
    "/tasks/{task_id}",
    summary="Cancel task",
    description="Cancel a pending or running enrichment task",
    response_description="Cancellation confirmation",
)
async def cancel_enrichment_task(
    task_id: str,
    terminate: bool = Query(
        default=False,
        description="Terminate task if already running (use with caution)",
    ),
) -> Dict[str, Any]:
    """
    Cancel an async enrichment task.

    Args:
        task_id: Celery task ID to cancel
        terminate: Whether to forcefully terminate if running

    Returns:
        Confirmation of cancellation
    """
    logger.info(
        "Cancelling enrichment task",
        task_id=task_id,
        terminate=terminate,
    )

    revoke_task(task_id, terminate=terminate)

    return {
        "task_id": task_id,
        "status": "cancelled",
        "terminated": terminate,
    }


@router.post(
    "/batch",
    summary="Batch enrich agents (async)",
    description="""
    Submit a batch of agents for enrichment.

    All agents are processed in the background. Returns a batch task ID
    for tracking overall progress.
    """,
    response_description="Batch task ID and status",
)
async def enrich_batch(
    requests: list[EnrichmentRequest],
    callback_url: Optional[str] = Query(
        default=None,
        description="URL to POST results when batch is complete",
    ),
) -> Dict[str, Any]:
    """
    Submit a batch of agents for enrichment.

    Args:
        requests: List of enrichment requests
        callback_url: Optional webhook URL for results

    Returns:
        Batch task ID and individual task IDs
    """
    if not settings.async_processing_enabled:
        raise HTTPException(
            status_code=400,
            detail="Async processing is not enabled",
        )

    if len(requests) > 100:
        raise HTTPException(
            status_code=400,
            detail="Batch size cannot exceed 100 agents",
        )

    logger.info(
        "Received batch enrichment request",
        batch_size=len(requests),
        callback_url=callback_url[:50] if callback_url else None,
    )

    # Convert requests to dicts
    requests_data = [r.model_dump() for r in requests]

    # Import batch task
    from src.worker.tasks import enrich_batch as enrich_batch_task

    # Submit batch task
    task = enrich_batch_task.delay(requests_data, callback_url)

    return {
        "batch_task_id": task.id,
        "status": "queued",
        "batch_size": len(requests),
        "status_url": f"/api/v1/enrich/tasks/{task.id}",
    }
