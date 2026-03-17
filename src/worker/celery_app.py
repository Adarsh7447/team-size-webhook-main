"""
Celery application configuration for async task processing.

Configures Celery with Redis as broker and result backend.
Optimized for high throughput (4000+ requests/minute).
"""

from celery import Celery

from src.config.settings import settings
from src.core.logging import get_logger

logger = get_logger("celery-app")


def create_celery_app() -> Celery:
    """
    Create and configure Celery application.

    Returns:
        Configured Celery app instance
    """
    app = Celery(
        "team_size_webhook",
        broker=settings.get_celery_broker_url(),
        backend=settings.get_celery_result_backend(),
        include=["src.worker.tasks"],
    )

    # Task settings
    app.conf.update(
        # Task execution
        task_soft_time_limit=settings.celery_task_soft_time_limit,
        task_time_limit=settings.celery_task_time_limit,
        task_acks_late=settings.celery_task_acks_late,
        task_reject_on_worker_lost=settings.celery_task_reject_on_worker_lost,
        # Worker settings
        worker_concurrency=settings.celery_worker_concurrency,
        worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
        # Serialization
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Result settings
        result_expires=3600,  # Results expire after 1 hour
        result_extended=True,  # Store task args/kwargs in result
        # Reliability
        task_track_started=True,
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 1,
        },
        # Broker settings
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=10,
        # Task routing (for future queue separation)
        task_default_queue="enrichment",
        task_queues={
            "enrichment": {
                "exchange": "enrichment",
                "routing_key": "enrichment.#",
            },
            "priority": {
                "exchange": "priority",
                "routing_key": "priority.#",
            },
        },
        task_routes={
            "src.worker.tasks.enrich_agent_task": {"queue": "enrichment"},
            "src.worker.tasks.enrich_agent_priority": {"queue": "priority"},
        },
        # Beat scheduler (disabled by default)
        beat_scheduler="celery.beat:PersistentScheduler",
    )

    logger.info(
        "Celery app created",
        broker=_mask_url(settings.get_celery_broker_url()),
        concurrency=settings.celery_worker_concurrency,
        prefetch=settings.celery_worker_prefetch_multiplier,
    )

    return app


def _mask_url(url: str) -> str:
    """Mask password in URL for logging."""
    if "@" in url:
        parts = url.split("@")
        return f"redis://***@{parts[-1]}"
    return url


# Create the Celery app instance
celery_app = create_celery_app()


# ==========================================================================
# Celery signals for lifecycle events
# ==========================================================================


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Setup periodic tasks (if needed)."""
    pass


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working."""
    return f"Request: {self.request!r}"
