"""
Celery tasks for async agent enrichment processing.

These tasks allow high-throughput processing by offloading enrichment
to background workers while the API remains responsive.
"""

import asyncio
from typing import Any, Dict, Optional

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from src.clients.grok import GrokClient
from src.clients.oxylabs import OxylabsClient
from src.clients.serper import SerperClient
from src.core.logging import get_logger
from src.schemas.requests import EnrichmentRequest
from src.services.ai_analyzer import AIAnalyzerService
from src.services.enrichment import EnrichmentService
from src.services.scraper import ScraperService
from src.services.search import SearchService

logger = get_logger("celery-tasks")


def _create_enrichment_service() -> EnrichmentService:
    """
    Create a new enrichment service instance with all dependencies.

    Returns:
        Configured EnrichmentService instance
    """
    # Create API clients
    serper_client = SerperClient()
    oxylabs_client = OxylabsClient()
    grok_client = GrokClient()

    # Create services
    search_service = SearchService(serper_client)
    scraper_service = ScraperService(oxylabs_client)
    ai_analyzer = AIAnalyzerService(grok_client)

    # Create orchestrator
    return EnrichmentService(
        search_service=search_service,
        scraper_service=scraper_service,
        ai_analyzer=ai_analyzer,
    )


async def _run_enrichment(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the enrichment process asynchronously.

    Args:
        request_data: Dictionary containing enrichment request data

    Returns:
        Dictionary containing enrichment response
    """
    service = _create_enrichment_service()

    try:
        # Parse request
        request = EnrichmentRequest.model_validate(request_data)

        # Run enrichment
        response = await service.enrich(request)

        # Convert to dict for serialization
        return response.model_dump()

    finally:
        # Clean up
        await service.close()


@shared_task(
    name="src.worker.tasks.enrich_agent_task",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=240,
    time_limit=300,
    acks_late=True,
    reject_on_worker_lost=True,
)
def enrich_agent_task(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Celery task for agent enrichment.

    This task processes enrichment requests asynchronously, allowing
    the API to return immediately while the work happens in the background.

    Args:
        request_data: Dictionary containing enrichment request data

    Returns:
        Dictionary containing enrichment response

    Raises:
        SoftTimeLimitExceeded: If task exceeds soft time limit
        Exception: On enrichment failure (will be retried)
    """
    agent_id = request_data.get("agent_id", "unknown")

    logger.info(
        "Starting enrichment task",
        task_id=self.request.id,
        agent_id=agent_id,
        retry=self.request.retries,
    )

    try:
        # Run the async enrichment in an event loop
        result = asyncio.run(_run_enrichment(request_data))

        logger.info(
            "Enrichment task completed",
            task_id=self.request.id,
            agent_id=agent_id,
            status=result.get("status"),
        )

        return result

    except SoftTimeLimitExceeded:
        logger.error(
            "Enrichment task soft time limit exceeded",
            task_id=self.request.id,
            agent_id=agent_id,
        )
        # Return error response instead of raising
        return {
            "status": "failed",
            "agent_id": agent_id,
            "team_size_count": -2,
            "team_size_category": "Unknown",
            "team_members": [],
            "error_code": "TIMEOUT",
            "error_message": "Task exceeded time limit",
            "processing_time_ms": 240000,
        }

    except Exception as e:
        logger.error(
            "Enrichment task failed",
            task_id=self.request.id,
            agent_id=agent_id,
            error=str(e),
            retry=self.request.retries,
        )
        raise  # Will trigger retry


@shared_task(
    name="src.worker.tasks.enrich_agent_priority",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_kwargs={"max_retries": 5},
    soft_time_limit=180,
    time_limit=240,
    acks_late=True,
    reject_on_worker_lost=True,
    queue="priority",
)
def enrich_agent_priority(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Priority enrichment task with shorter time limits and more retries.

    Use this queue for time-sensitive requests.

    Args:
        request_data: Dictionary containing enrichment request data

    Returns:
        Dictionary containing enrichment response
    """
    agent_id = request_data.get("agent_id", "unknown")

    logger.info(
        "Starting priority enrichment task",
        task_id=self.request.id,
        agent_id=agent_id,
    )

    try:
        result = asyncio.run(_run_enrichment(request_data))

        logger.info(
            "Priority enrichment task completed",
            task_id=self.request.id,
            agent_id=agent_id,
            status=result.get("status"),
        )

        return result

    except SoftTimeLimitExceeded:
        logger.error(
            "Priority task soft time limit exceeded",
            task_id=self.request.id,
            agent_id=agent_id,
        )
        return {
            "status": "failed",
            "agent_id": agent_id,
            "team_size_count": -2,
            "team_size_category": "Unknown",
            "team_members": [],
            "error_code": "TIMEOUT",
            "error_message": "Task exceeded time limit",
            "processing_time_ms": 180000,
        }

    except Exception as e:
        logger.error(
            "Priority enrichment task failed",
            task_id=self.request.id,
            agent_id=agent_id,
            error=str(e),
        )
        raise


@shared_task(
    name="src.worker.tasks.enrich_batch",
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def enrich_batch(
    self,
    requests_data: list[Dict[str, Any]],
    callback_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Batch enrichment task for processing multiple agents.

    Args:
        requests_data: List of enrichment request dictionaries
        callback_url: Optional URL to POST results when complete

    Returns:
        Dictionary with batch results
    """
    logger.info(
        "Starting batch enrichment",
        task_id=self.request.id,
        batch_size=len(requests_data),
    )

    results = []
    successful = 0
    failed = 0

    for i, request_data in enumerate(requests_data):
        agent_id = request_data.get("agent_id", f"batch_{i}")

        try:
            result = asyncio.run(_run_enrichment(request_data))
            results.append(result)

            if result.get("status") == "success":
                successful += 1
            else:
                failed += 1

        except Exception as e:
            logger.error(
                "Batch item failed",
                task_id=self.request.id,
                agent_id=agent_id,
                error=str(e),
            )
            results.append({
                "status": "failed",
                "agent_id": agent_id,
                "error_code": "INTERNAL_ERROR",
                "error_message": str(e),
            })
            failed += 1

        # Update task state for progress tracking
        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": len(requests_data),
                "successful": successful,
                "failed": failed,
            },
        )

    logger.info(
        "Batch enrichment complete",
        task_id=self.request.id,
        total=len(requests_data),
        successful=successful,
        failed=failed,
    )

    # Send callback if provided
    if callback_url:
        _send_callback(callback_url, results)

    return {
        "status": "complete",
        "total": len(requests_data),
        "successful": successful,
        "failed": failed,
        "results": results,
    }


def _send_callback(url: str, data: Any) -> None:
    """Send results to callback URL."""
    import httpx

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json=data)
            response.raise_for_status()
            logger.info("Callback sent successfully", url=url[:50])
    except Exception as e:
        logger.error("Failed to send callback", url=url[:50], error=str(e))


# ==========================================================================
# Helper functions for task management
# ==========================================================================


def get_task_result(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the result of a task by ID.

    Args:
        task_id: Celery task ID

    Returns:
        Task result if complete, None otherwise
    """
    from src.worker.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)

    if result.ready():
        return result.get()

    return None


def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of a task by ID.

    Args:
        task_id: Celery task ID

    Returns:
        Dictionary with task status information including 'task_exists' flag
    """
    from src.worker.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)

    # Check if task actually exists in the backend
    # If status is PENDING, check if there's any metadata stored
    task_exists = True
    if result.status == "PENDING":
        try:
            # Get task metadata from backend
            task_meta = result._get_task_meta()

            # If task has never been seen, metadata will only have default values
            # Check if any meaningful data exists (result, traceback, children, date_done)
            has_data = any([
                task_meta.get("result"),
                task_meta.get("traceback"),
                task_meta.get("children"),
                task_meta.get("date_done"),
            ])

            # If no data and status is PENDING, task likely doesn't exist
            task_exists = has_data
        except Exception:
            # If we can't check, assume task exists to avoid false negatives
            task_exists = True

    return {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
        "info": result.info if result.status == "PROGRESS" else None,
        "task_exists": task_exists,
    }


def revoke_task(task_id: str, terminate: bool = False) -> None:
    """
    Revoke a pending task.

    Args:
        task_id: Celery task ID
        terminate: Whether to terminate if already running
    """
    from src.worker.celery_app import celery_app

    celery_app.control.revoke(task_id, terminate=terminate)
    logger.info("Task revoked", task_id=task_id, terminate=terminate)
