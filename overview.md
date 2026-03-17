# Codebase Overview

## Overview

This repository is a FastAPI service that enriches real estate agent records by determining team size and related metadata from public web data. The main workflow is:

1. Accept agent input
2. Find the likely website
3. Scrape the homepage and possibly a team page
4. Send cleaned page text to Grok for structured extraction
5. Return team size, members, brokerage/team names, and detected CRMs

The main app entry point is `src/main.py`. It configures startup and shutdown, CORS, middleware, and routes. The API surface is intentionally small:

- Sync enrichment
- Async enrichment
- Task status and cancellation
- Health and readiness endpoints

The main endpoint files are:

- `src/api/v1/endpoints/enrichment.py`
- `src/api/v1/endpoints/health.py`

## Request Lifecycle

The core orchestration logic lives in `src/services/enrichment.py`. This is the central file in the codebase.

Each request is converted into an internal `AgentData` model from `src/schemas/internal.py`, and state is carried through the pipeline using `EnrichmentContext`.

The enrichment pipeline works like this:

1. Try direct scraping of `list_website` if it is provided
2. Otherwise search for the site with Serper via `src/services/search.py`
3. Use Grok to choose the best search result
4. Scrape the selected site with Oxylabs via `src/services/scraper.py`
5. Extract internal links and identify likely team pages via `src/services/link_extractor.py`
6. Analyze page text with Grok via `src/services/ai_analyzer.py`
7. Detect CRM and related technologies via `src/services/tech_detector.py`

The AI layer is schema-driven. Prompts live in `src/prompts/templates.py`, and Grok is expected to return JSON matching Pydantic response models. That keeps the LLM interaction structured instead of free-form.

## Main Components

- `src/api/dependencies.py`
  Creates singleton clients and services during app startup.

- `src/clients/base.py`
  Shared async HTTP client with retry logic, timeouts, and a circuit breaker.

- `src/clients/serper.py`
  Wrapper around the Serper search API.

- `src/clients/oxylabs.py`
  Wrapper around the Oxylabs scraping API.

- `src/clients/grok.py`
  Wrapper around the xAI SDK with multi-key round-robin selection and per-key rate limiting.

- `src/core/redis.py`
  Redis singleton used for rate limiting and Celery integration.

- `src/api/middleware.py`
  Handles request IDs, global error responses, and Redis-backed rate limiting.

- `src/worker/celery_app.py`
  Celery application configuration for async processing.

- `src/worker/tasks.py`
  Background task entry points that run the same enrichment flow outside the request-response path.

## Data Contracts

The current request schema is defined in `src/schemas/requests.py`. The live API expects fields in the `list_*` format, including:

- `list_name`
- `list_email`
- `list_team_name`
- `list_brokerage`
- `list_website`
- `list_location`

Response models are defined in `src/schemas/responses.py`.

One important caveat: the repository still contains signs of an older request shape using fields like `full_name`, `email`, and `organization_names`. The fixtures in `tests/conftest.py` use the current `list_*` shape, but parts of:

- `README.md`
- `tests/test_enrichment_endpoint.py`
- `tests/test_async_endpoints.py`

still reference legacy fields. So the codebase appears to be mid-migration on its request contract and documentation.

## Suggested Reading Order

To understand the codebase quickly, read these files in order:

1. `src/main.py`
2. `src/api/v1/endpoints/enrichment.py`
3. `src/services/enrichment.py`
4. `src/services/ai_analyzer.py`
5. `src/schemas/internal.py`
6. `src/prompts/templates.py`

This sequence gives the fastest path from entry point to request handling, business orchestration, AI behavior, and internal state models.
