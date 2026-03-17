"""
Structured logging setup using structlog.

Provides JSON-formatted logs with:
- Request ID tracking
- Agent ID context
- Service/component identification
- Duration measurements
- Error details
"""

import logging
import sys
from contextvars import ContextVar
from typing import Any, Dict, Optional

import structlog
from structlog.types import Processor

# Context variables for request tracking
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
agent_id_ctx: ContextVar[Optional[str]] = ContextVar("agent_id", default=None)


def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return request_id_ctx.get()


def set_request_id(request_id: str) -> None:
    """Set request ID in context."""
    request_id_ctx.set(request_id)


def get_agent_id() -> Optional[str]:
    """Get current agent ID from context."""
    return agent_id_ctx.get()


def set_agent_id(agent_id: str) -> None:
    """Set agent ID in context."""
    agent_id_ctx.set(agent_id)


def add_context_info(
    logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Add context variables to log entries."""
    request_id = get_request_id()
    agent_id = get_agent_id()

    if request_id:
        event_dict["request_id"] = request_id
    if agent_id:
        event_dict["agent_id"] = agent_id

    return event_dict


def setup_logging(
    log_level: str = "INFO",
    json_format: bool = True,
    service_name: str = "team-size-api",
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_format: If True, output JSON logs; otherwise, console-friendly format
        service_name: Name of the service for log entries
    """
    # Determine log level
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Shared processors for all logging
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        add_context_info,
    ]

    if json_format:
        # JSON format for production
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        # Console-friendly format for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Setup handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Log startup message
    logger = get_logger(service_name)
    logger.info(
        "Logging configured",
        log_level=log_level,
        json_format=json_format,
    )


def get_logger(name: str = "team-size-api") -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically module or component name)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


class LogContext:
    """
    Context manager for adding temporary log context.

    Usage:
        with LogContext(operation="scrape", url="https://example.com"):
            logger.info("Starting scrape")
            # All logs within this block will have operation and url fields
    """

    def __init__(self, **kwargs: Any):
        self.context = kwargs
        self._token = None

    def __enter__(self) -> "LogContext":
        self._token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._token:
            structlog.contextvars.unbind_contextvars(*self.context.keys())


def log_duration(logger: structlog.stdlib.BoundLogger, operation: str):
    """
    Decorator/context manager to log operation duration.

    Usage as decorator:
        @log_duration(logger, "fetch_data")
        async def fetch_data():
            ...

    Usage as context manager:
        with log_duration(logger, "process_request"):
            ...
    """
    import time
    from contextlib import contextmanager
    from functools import wraps

    @contextmanager
    def _context_manager():
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                f"{operation} completed",
                operation=operation,
                duration_ms=round(duration_ms, 2),
            )

    def _decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.info(
                    f"{operation} completed",
                    operation=operation,
                    duration_ms=round(duration_ms, 2),
                )

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.info(
                    f"{operation} completed",
                    operation=operation,
                    duration_ms=round(duration_ms, 2),
                )

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    # Allow usage as both decorator and context manager
    return _context_manager()
