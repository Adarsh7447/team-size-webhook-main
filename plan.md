# Team Size Webhook API - Implementation Plan

## Overview

Transform the batch processing script into a production-grade FastAPI webhook service.

**Flow (Sync Mode - Default for n8n):**
```
n8n → FastAPI /enrich → Celery Task → Wait for Result → Return enriched data
```

**Flow (Async Mode - High Throughput):**
```
n8n → FastAPI /enrich → Celery Task → Return task_id immediately
n8n → FastAPI /tasks/{id} → Poll for result
```

**Architecture:**
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    n8n      │────▶│   FastAPI   │────▶│    Redis    │
│  (webhook)  │     │   (API)     │     │  (broker)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌─────────────┐            │
                    │   Celery    │◀───────────┘
                    │  (workers)  │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐
   │  Serper  │     │ Oxylabs  │     │   Grok   │
   │  (search)│     │ (scrape) │     │   (AI)   │
   └──────────┘     └──────────┘     └──────────┘
```

**Capacity:** 4000+ requests/minute with horizontal scaling

---

## Current vs Target

| Aspect | Current | Target |
|--------|---------|--------|
| Input | Poll PostgreSQL database | Receive webhook from n8n |
| Output | Update database + send webhooks | Return enriched data in HTTP response |
| Processing | Batch (mass enrichment) | Single request (on-demand) |
| Architecture | Single 1200+ line script | Modular FastAPI application |

---

## Target Folder Structure

```
team-size-webhook/
├── src/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app entry point
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py              # Pydantic Settings (env validation)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py            # Version router
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── enrichment.py    # POST /api/v1/enrich
│   │           └── health.py        # GET /health, /ready
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── requests.py              # EnrichmentRequest model
│   │   ├── responses.py             # EnrichmentResponse model
│   │   └── internal.py              # TeamMember, WebsiteAssessment, etc.
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── enrichment.py            # Main orchestration logic
│   │   ├── search.py                # Serper search service
│   │   ├── scraper.py               # Oxylabs scraping service
│   │   ├── ai_analyzer.py           # Grok AI analysis service
│   │   ├── link_extractor.py        # HTML link extraction
│   │   └── tech_detector.py         # CRM/technology detection
│   │
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── base.py                  # Base HTTP client with retry
│   │   ├── serper.py                # Serper API client
│   │   ├── oxylabs.py               # Oxylabs API client
│   │   └── grok.py                  # Grok AI client
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── templates.py             # AI prompts & Pydantic models
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py            # Custom exceptions
│   │   ├── logging.py               # Structured logging setup
│   │   └── dependencies.py          # FastAPI dependencies
│   │
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── rate_limiter.py          # Redis-based rate limiting
│   │   └── error_handler.py         # Global exception handlers
│   │
│   └── worker/
│       ├── __init__.py
│       ├── celery_app.py            # Celery application config
│       └── tasks.py                 # Celery tasks for enrichment
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_enrichment.py
│   └── test_clients.py
│
├── .env.example
├── .env.local                       # (gitignored)
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## API Contract

### Endpoint: `POST /api/v1/enrich`

#### Request Body
```json
{
  "agent_id": "uuid-string",
  "full_name": "John Smith",
  "first_name": "John",
  "last_name": "Smith",
  "organization_names": ["Smith Realty Group"],
  "email": ["john@smithrealty.com"],
  "phone": ["+1-555-123-4567"],
  "office_number": "+1-555-000-0000",
  "website_url": "https://smithrealty.com",
  "city": "Austin",
  "state": "TX"
}
```

#### Response Body (Success)
```json
{
  "status": "success",
  "agent_id": "uuid-string",
  "team_size_count": 5,
  "team_size_category": "Small",
  "team_members": [
    {
      "name": "John Smith",
      "email": "john@smithrealty.com",
      "phone": "+1-555-123-4567",
      "designation": "Team Lead"
    }
  ],
  "team_page_url": "https://smithrealty.com/our-team",
  "homepage_url": "https://smithrealty.com",
  "team_name": "Smith Realty Group",
  "brokerage_name": "Keller Williams",
  "agent_designation": ["Team Lead"],
  "detected_crms": ["Follow Up Boss"],
  "confidence": "HIGH",
  "reasoning": "Found 5 team members listed on the team page",
  "processing_time_ms": 4523
}
```

#### Response Body (Failure)
```json
{
  "status": "failed",
  "agent_id": "uuid-string",
  "team_size_count": -2,
  "team_size_category": "Unknown",
  "team_members": [],
  "error_code": "NO_WEBSITE_FOUND",
  "error_message": "Could not find a valid website for this agent",
  "processing_time_ms": 1234
}
```

### Health Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check (always 200) |
| `/ready` | GET | Readiness check (verifies API keys configured) |

---

## Implementation Phases

### Phase 1: Project Setup & Configuration
- [ ] Create folder structure
- [ ] Setup `pyproject.toml` with project metadata
- [ ] Create `src/config/settings.py` with Pydantic Settings
- [ ] Create `.env.example` with all required variables
- [ ] Update `requirements.txt` with new dependencies

**Files to create:**
- `src/__init__.py`
- `src/config/__init__.py`
- `src/config/settings.py`
- `.env.example`
- `pyproject.toml`

### Phase 2: Core Infrastructure
- [ ] Create custom exceptions (`src/core/exceptions.py`)
- [ ] Setup structured logging (`src/core/logging.py`)
- [ ] Create base HTTP client with retry logic (`src/clients/base.py`)

**Files to create:**
- `src/core/__init__.py`
- `src/core/exceptions.py`
- `src/core/logging.py`
- `src/clients/__init__.py`
- `src/clients/base.py`

### Phase 3: External API Clients
- [ ] Migrate Serper client (`src/clients/serper.py`)
- [ ] Migrate Oxylabs client (`src/clients/oxylabs.py`)
- [ ] Migrate Grok AI client (`src/clients/grok.py`)

**Files to create:**
- `src/clients/serper.py`
- `src/clients/oxylabs.py`
- `src/clients/grok.py`

### Phase 4: Prompts & Schemas
- [ ] Move prompts to `src/prompts/templates.py`
- [ ] Create request schemas (`src/schemas/requests.py`)
- [ ] Create response schemas (`src/schemas/responses.py`)
- [ ] Create internal schemas (`src/schemas/internal.py`)

**Files to create:**
- `src/prompts/__init__.py`
- `src/prompts/templates.py`
- `src/schemas/__init__.py`
- `src/schemas/requests.py`
- `src/schemas/responses.py`
- `src/schemas/internal.py`

### Phase 5: Business Logic Services
- [ ] Create link extractor service (`src/services/link_extractor.py`)
- [ ] Create tech detector service (`src/services/tech_detector.py`)
- [ ] Create search service (`src/services/search.py`)
- [ ] Create scraper service (`src/services/scraper.py`)
- [ ] Create AI analyzer service (`src/services/ai_analyzer.py`)
- [ ] Create main enrichment orchestrator (`src/services/enrichment.py`)

**Files to create:**
- `src/services/__init__.py`
- `src/services/link_extractor.py`
- `src/services/tech_detector.py`
- `src/services/search.py`
- `src/services/scraper.py`
- `src/services/ai_analyzer.py`
- `src/services/enrichment.py`

### Phase 6: FastAPI Application + Redis + Celery
- [ ] Create Redis client wrapper (`src/core/redis.py`)
- [ ] Create Celery app configuration (`src/worker/celery_app.py`)
- [ ] Create Celery tasks (`src/worker/tasks.py`)
- [ ] Create Redis-based rate limiter middleware (`src/middleware/rate_limiter.py`)
- [ ] Create error handler middleware (`src/middleware/error_handler.py`)
- [ ] Create FastAPI dependencies (`src/core/dependencies.py`)
- [ ] Create health endpoints (`src/api/v1/endpoints/health.py`)
- [ ] Create enrichment endpoint (`src/api/v1/endpoints/enrichment.py`)
- [ ] Create API router (`src/api/v1/router.py`)
- [ ] Create main application (`src/main.py`)

**Files to create:**
- `src/core/redis.py`
- `src/worker/__init__.py`
- `src/worker/celery_app.py`
- `src/worker/tasks.py`
- `src/middleware/rate_limiter.py`
- `src/middleware/error_handler.py`
- `src/api/v1/router.py`
- `src/api/v1/endpoints/health.py`
- `src/api/v1/endpoints/enrichment.py`
- `src/core/dependencies.py`
- `src/main.py`

### Phase 7: Production Readiness
- [ ] Create Dockerfile
- [ ] Create docker-compose.yml for local dev
- [ ] Update README.md with new usage instructions
- [ ] Add basic tests

**Files to create:**
- `Dockerfile`
- `docker-compose.yml`
- `tests/__init__.py`
- `tests/conftest.py`
- `requirements-dev.txt`

---

## Production Features

### 1. Rate Limiting (Redis-based)
```python
# Distributed rate limiter using Redis sliding window
# Supports 4000+ requests/minute across multiple workers
# Configurable via environment variables:
RATE_LIMIT_REQUESTS=4000     # Max requests
RATE_LIMIT_WINDOW_SECONDS=60 # Per time window
REDIS_URL=redis://localhost:6379/0
```

### 1.1 Celery Task Queue
```python
# Celery configuration for async task processing
# Supports high throughput with multiple workers
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
CELERY_TASK_TIME_LIMIT=300  # 5 min max per task

# Processing modes:
# - SYNC: Wait for result (default, for n8n compatibility)
# - ASYNC: Return task_id immediately, poll for result
PROCESSING_MODE=sync
SYNC_TIMEOUT=300  # Max wait time in sync mode
```

### 2. Retry Mechanism (Tenacity)
```python
# Retry configuration per client:
- max_attempts: 3
- wait: exponential backoff (1s, 2s, 4s)
- retry_on: timeout, 429, 5xx errors
- circuit_breaker: stop after N consecutive failures
```

### 3. Timeouts
```python
# Configurable timeouts:
SERPER_TIMEOUT_SECONDS=30
OXYLABS_TIMEOUT_SECONDS=90
GROK_TIMEOUT_SECONDS=120
TOTAL_REQUEST_TIMEOUT_SECONDS=300  # 5 min max per enrichment
```

### 4. Structured Logging
```python
# JSON logs with:
- request_id (for tracing)
- agent_id (for debugging)
- service (which component)
- duration_ms (performance)
- error details (when applicable)
```

### 5. Error Handling
| Error Type | HTTP Status | Error Code |
|------------|-------------|------------|
| Validation error | 422 | `VALIDATION_ERROR` |
| Rate limit exceeded | 429 | `RATE_LIMIT_EXCEEDED` |
| External API timeout | 504 | `EXTERNAL_TIMEOUT` |
| External API error | 502 | `EXTERNAL_API_ERROR` |
| No website found | 200 | `NO_WEBSITE_FOUND` |
| Analysis failed | 200 | `ANALYSIS_FAILED` |
| Internal error | 500 | `INTERNAL_ERROR` |

### 6. Graceful Degradation
- If Serper fails → return error with `NO_WEBSITE_FOUND`
- If Oxylabs fails → return error with `SCRAPE_FAILED`
- If Grok fails → return partial result with `team_size_count: -2`

---

## Environment Variables

```env
# Required - API Keys
SERPER_API_KEY=your_key
OXYLABS_USERNAME=your_username
OXYLABS_PASSWORD=your_password
GROK_API_KEY=your_key
# Or use multiple Grok keys for load balancing:
GROK_API_KEY_1=key1
GROK_API_KEY_2=key2

# Server Configuration
HOST=0.0.0.0
PORT=8000
WORKERS=4
LOG_LEVEL=INFO

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
CELERY_TASK_TIME_LIMIT=300

# Processing Mode (sync or async)
PROCESSING_MODE=sync
SYNC_TIMEOUT=300

# Rate Limiting (Redis-based)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=4000
RATE_LIMIT_WINDOW_SECONDS=60

# Timeouts (seconds)
SERPER_TIMEOUT=30
OXYLABS_TIMEOUT=90
GROK_TIMEOUT=120
REQUEST_TIMEOUT=300

# Retry Configuration
MAX_RETRIES=3
RETRY_BACKOFF_MULTIPLIER=2

# Feature Flags
BLOCKED_DOMAINS=linkedin.com,facebook.com,instagram.com,twitter.com,idxbroker.com,zillow.com,realtor.com
MIN_HTML_BYTES=3500
```

---

## Dependencies

### requirements.txt
```txt
# Web Framework
fastapi>=0.109.0
uvicorn[standard]>=0.27.0

# Data Validation
pydantic>=2.5.0
pydantic-settings>=2.1.0

# HTTP Client
httpx>=0.26.0

# Retry Logic
tenacity>=8.2.0

# AI SDK
xai-sdk>=1.0.0

# HTML Parsing
beautifulsoup4>=4.12.0

# Environment
python-dotenv>=1.0.0

# Logging
structlog>=24.1.0

# Redis + Celery (High Throughput)
redis>=5.0.0
celery[redis]>=5.3.0
```

### requirements-dev.txt
```txt
-r requirements.txt
pytest>=7.4.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
httpx>=0.26.0  # For TestClient
ruff>=0.1.0    # Linting
black>=24.1.0  # Formatting
mypy>=1.8.0    # Type checking
```

---

## Running the Application

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Production
```bash
# Run with multiple workers
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4

# Or with gunicorn
gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Docker
```bash
# Build
docker build -t team-size-api .

# Run
docker run -p 8000:8000 --env-file .env.local team-size-api
```

---

## n8n Integration

### HTTP Request Node Configuration
```
Method: POST
URL: http://your-server:8000/api/v1/enrich
Headers:
  Content-Type: application/json
Body:
  {
    "agent_id": "{{ $json.uuid }}",
    "full_name": "{{ $json.full_name }}",
    "organization_names": {{ $json.organization_names }},
    "email": {{ $json.email }},
    "phone": {{ $json.phone }},
    "city": "{{ $json.city }}",
    "state": "{{ $json.state }}"
  }
Timeout: 300000 (5 minutes)
```

### Expected Response in n8n
The enriched data will be available in `$json` for the next node:
- `$json.team_size_count`
- `$json.team_size_category`
- `$json.team_members`
- `$json.team_name`
- etc.

---

## Files to Delete After Migration

Once the new structure is working:
- `team_size_estimator.py` (replaced by modular services)
- `prompts.py` (moved to `src/prompts/templates.py`)

---

## Estimated Implementation Order

1. **Phase 1-2**: Foundation (~30 mins)
2. **Phase 3**: Clients (~45 mins)
3. **Phase 4**: Schemas & Prompts (~30 mins)
4. **Phase 5**: Services (~1 hour)
5. **Phase 6**: FastAPI App (~45 mins)
6. **Phase 7**: Docker & Tests (~30 mins)

**Total: ~4-5 hours**

---

## Success Criteria

- [ ] `POST /api/v1/enrich` accepts agent data and returns enriched response
- [ ] Rate limiting prevents abuse (429 when exceeded)
- [ ] Retries handle transient failures gracefully
- [ ] Structured logs enable debugging
- [ ] Health endpoints enable monitoring
- [ ] Docker container runs successfully
- [ ] n8n can call the API and receive enriched data
