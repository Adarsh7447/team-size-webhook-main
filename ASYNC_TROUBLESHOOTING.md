# Async Processing Not Working - Root Cause & Fix

## 🔴 Problem

Your async endpoint creates tasks but they stay "pending" forever because **Railway is only running the web service, not the Celery worker**.

## 🎯 Root Cause

### What's Happening

1. ✅ POST `/api/v1/enrich/async` → Creates task → Saves to Redis → Returns task_id
2. ❌ **No worker is running** → Task sits in Redis queue forever
3. ❌ GET `/api/v1/enrich/tasks/{task_id}` → Returns "pending" (because task never started)

### Why Tasks Show "pending" for Non-Existent IDs

Celery's `AsyncResult()` returns `status="PENDING"` for:
- Tasks that exist but haven't been processed yet
- **Task IDs that don't exist at all**

This is a Celery design choice - it can't distinguish between them without checking the backend storage.

## ✅ Solution

You need **TWO services** running on Railway:

### Service 1: Web (API) - Already Running ✅
```bash
uvicorn src.main:app --host 0.0.0.0 --port $PORT
```
Handles HTTP requests, creates tasks, returns task IDs

### Service 2: Worker (Celery) - MISSING ❌
```bash
celery -A src.worker.celery_app worker --loglevel=info --concurrency=4
```
**This is what you're missing!** This service picks up tasks from Redis and processes them.

## 🚀 How to Fix on Railway

### Quick Fix (Recommended)

1. **Push the `railway.toml` file** (already created for you)
   ```bash
   git add railway.toml RAILWAY_SETUP.md ASYNC_TROUBLESHOOTING.md check_async.py
   git commit -m "Add Celery worker configuration for Railway"
   git push
   ```

2. **Railway should auto-detect** and deploy both services

3. **Or manually create the worker service:**
   - Click "+ New" → "GitHub Repo" → Select your repo
   - Name it `celery-worker`
   - Go to Settings → Deploy
   - Set Start Command: `celery -A src.worker.celery_app worker --loglevel=info --concurrency=4`
   - Copy ALL environment variables from web service (especially REDIS_URL, API keys)
   - Deploy

### Verification

After deploying the worker, check the logs. You should see:

```
[tasks]
  . src.worker.tasks.enrich_agent_priority
  . src.worker.tasks.enrich_agent_task
  . src.worker.tasks.enrich_batch

celery@hostname ready.
```

When you create a task via POST `/async`, the worker logs will show:
```
[2024-XX-XX XX:XX:XX] Task src.worker.tasks.enrich_agent_task[task-id] received
[2024-XX-XX XX:XX:XX] Starting enrichment task
[2024-XX-XX XX:XX:XX] Enrichment task completed
```

## 🧪 Testing

### Test Locally First (Recommended)

```bash
# Terminal 1 - Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Terminal 2 - Start API
python -m uvicorn src.main:app --reload

# Terminal 3 - Start Worker (THIS IS THE KEY!)
celery -A src.worker.celery_app worker --loglevel=info

# Terminal 4 - Test
curl -X POST "http://localhost:8000/api/v1/enrich/async" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-123",
    "list_name": "Test Agent",
    "list_email": "test@example.com"
  }'

# Get task_id from response, then check status
curl http://localhost:8000/api/v1/enrich/tasks/{task_id}
```

Watch Terminal 3 (worker) - you should see the task being processed!

### Test on Railway

Once you've deployed the worker:

```bash
curl -X POST "https://team-size-webhook-production.up.railway.app/api/v1/enrich/async" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-123",
    "list_name": "Test Agent",
    "list_email": "test@example.com"
  }'
```

Then check the task status AND the worker logs on Railway.

## 📊 Architecture Overview

```
┌─────────────────┐
│   Your Request  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  Web Service (FastAPI)      │
│  - Receives HTTP requests   │
│  - Creates Celery tasks     │
│  - Returns task_id          │
└────────┬────────────────────┘
         │
         │ (Sends task to Redis)
         ▼
┌─────────────────────────────┐
│  Redis (Message Broker)     │
│  - Stores task queue        │
│  - Stores task results      │
└────────┬────────────────────┘
         │
         │ (Worker polls for tasks)
         ▼
┌─────────────────────────────┐
│  Worker Service (Celery)    │  ← YOU'RE MISSING THIS!
│  - Picks up tasks           │
│  - Processes enrichment     │
│  - Saves results to Redis   │
└─────────────────────────────┘
```

**Without the worker, tasks pile up in Redis and never get processed!**

## 🔧 Quick Diagnostic

Run this to check your configuration:

```bash
python check_async.py
```

This will verify:
- ✅ Environment variables are set
- ✅ Redis is accessible
- ✅ Celery app loads correctly
- ✅ Tasks are registered
- ⚠️  Can submit tasks (but warns if no worker is running)

## 📝 Checklist

Before async will work on Railway, you need:

- [x] Redis service deployed on Railway
- [x] Web service with REDIS_URL configured
- [ ] **Worker service deployed (THIS IS WHAT'S MISSING!)**
- [ ] Worker has same REDIS_URL as web service
- [ ] Worker has all API keys (SERPER, OXYLABS, GROK)
- [ ] ASYNC_PROCESSING_ENABLED=true in web service

## 🎓 Why This Happens

Your local docker-compose.yml has both services defined:
- `web` service (API)
- `celery-worker` service (worker)

When you run `docker-compose up`, both start automatically.

Railway doesn't use docker-compose. By default, it only deploys ONE service from your repo. You need to explicitly configure it to run the worker as a separate service.

## 💡 Alternative: Sync-Only Mode

If you don't want to manage workers, you can disable async:

```env
ASYNC_PROCESSING_ENABLED=false
```

Then only use POST `/api/v1/enrich` (sync endpoint). It will process immediately but take 30-60 seconds per request.

## 📚 References

- See `RAILWAY_SETUP.md` for detailed deployment steps
- See `docker-compose.yml` for the local multi-service setup
- See `src/worker/celery_app.py` for Celery configuration
