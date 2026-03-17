"""
Celery worker module for async task processing.

Provides distributed task execution for high-throughput enrichment requests.
"""

from src.worker.celery_app import celery_app

__all__ = ["celery_app"]
