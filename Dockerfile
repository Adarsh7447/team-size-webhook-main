# =============================================================================
# Team Size Webhook API - Production Dockerfile
# =============================================================================
# Multi-stage build for smaller, secure production image
# Supports: FastAPI app, Celery workers

# -----------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies
# -----------------------------------------------------------------------------
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Production - Minimal runtime image
# -----------------------------------------------------------------------------
FROM python:3.11-slim as production

# Labels
LABEL maintainer="Team Size Webhook API" \
      version="1.0.0" \
      description="High-throughput webhook API for real estate agent enrichment"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    # Default settings (override with docker-compose or -e)
    HOST=0.0.0.0 \
    PORT=8000 \
    WORKERS=4 \
    LOG_LEVEL=INFO \
    DEBUG=false

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=appuser:appgroup src/ ./src/

# Create necessary directories
RUN mkdir -p /app/logs && chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Default command - FastAPI server
# Can be overridden for Celery worker
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

# -----------------------------------------------------------------------------
# Alternative entrypoints (use with docker-compose command override):
#
# FastAPI with multiple workers:
#   uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
#
# Celery worker:
#   celery -A src.worker.celery_app worker --loglevel=info --concurrency=8
#
# Celery beat (scheduler):
#   celery -A src.worker.celery_app beat --loglevel=info
# -----------------------------------------------------------------------------
