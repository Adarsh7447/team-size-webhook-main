# Railway Deployment Guide

## IMPORTANT: Async Processing Requires 2 Services

Your application uses **Celery** for async task processing, which requires:
1. **Web Service** (FastAPI API) - handles HTTP requests
2. **Worker Service** (Celery worker) - processes async tasks

**If you only deploy the web service, async endpoints will queue tasks but never process them!**

## Step 1: Add Redis Service (Required)

Your application requires Redis for rate limiting and Celery task queue.

1. In Railway dashboard, click **"+ New"** → **"Database"** → **"Add Redis"**
2. Railway will automatically create a Redis instance
3. Note the `REDIS_URL` from the Redis service (it will be something like `redis://default:password@redis.railway.internal:6379`)

## Step 2: Add Environment Variables

Go to your `team-size-webhook` service → **"Variables"** tab → Click **"+ New Variable"**

Add the following **REQUIRED** variables:

### API Keys (Required)
```
SERPER_API_KEY=<your-serper-api-key>
OXYLABS_USERNAME=<your-oxylabs-username>
OXYLABS_PASSWORD=<your-oxylabs-password>
GROK_API_KEY=<your-grok-api-key>
GROK_API_KEY_1=<your-grok-api-key-1>
GROK_API_KEY_2=<your-grok-api-key-2>
```

### Redis Configuration (Required)
```
REDIS_URL=<get this from Railway Redis service>
CELERY_BROKER_URL=<same as REDIS_URL>
CELERY_RESULT_BACKEND=<same as REDIS_URL>
```

### Server Configuration (Optional - defaults shown)
```
HOST=0.0.0.0
PORT=8000  # Railway sets this automatically, but you can override if needed
WORKERS=4
LOG_LEVEL=INFO
DEBUG=false  # Set to true to enable /docs endpoint
```

**Note:** Railway automatically sets the `PORT` environment variable. Your app will use it automatically. You don't need to set PORT unless you want to override Railway's default.

### Rate Limiting (Optional - defaults shown)
```
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60
```

### Timeouts (Optional - defaults shown)
```
SERPER_TIMEOUT=30
OXYLABS_TIMEOUT=90
GROK_TIMEOUT=120
REQUEST_TIMEOUT=300
```

## Step 3: Get Redis URL from Railway

After adding Redis service:
1. Click on the Redis service
2. Go to **"Variables"** tab
3. Copy the `REDIS_URL` value (or `REDIS_URL_PRIVATE` if available)
4. Add it to your web service variables

**Note:** Railway may provide `REDIS_URL` automatically if you use their Redis addon. Check if it's already available in your web service's variables.

## Step 4: Deploy Celery Worker Service (REQUIRED for Async)

**This is the critical step that's likely missing!** You need a second service to run the Celery worker.

### Option A: Using railway.toml (Automatic)

1. Push the `railway.toml` file to your repo (it's already created)
2. Railway will automatically detect and deploy both services

### Option B: Manual Setup in Railway Dashboard

1. In your Railway project, click **"+ New"** → **"GitHub Repo"**
2. Select the **same repository** you used for the web service
3. Name it `celery-worker`
4. Go to **Settings** → **Deploy**
5. Set **Start Command** to:
   ```
   celery -A src.worker.celery_app worker --loglevel=info --concurrency=4
   ```
6. Copy **ALL environment variables** from your web service:
   - SERPER_API_KEY
   - OXYLABS_USERNAME
   - OXYLABS_PASSWORD
   - GROK_API_KEY (and GROK_API_KEY_1, GROK_API_KEY_2)
   - REDIS_URL (same as web service)
   - CELERY_BROKER_URL (same as web service)
   - CELERY_RESULT_BACKEND (same as web service)
   - LOG_LEVEL=INFO

7. Deploy the worker service

### Verify Worker is Running

Check the worker logs. You should see:
```
[tasks]
  . src.worker.tasks.enrich_agent_priority
  . src.worker.tasks.enrich_agent_task

celery@hostname ready.
```

## Step 5: Redeploy Web Service

After adding all variables and setting up the worker:
1. Go back to your `team-size-webhook` web service
2. Ensure `ASYNC_PROCESSING_ENABLED=true` is set
3. Click **"Deploy"** or Railway will auto-deploy
4. Check the **"Deploy Logs"** to verify it starts successfully

## Quick Copy-Paste for Railway Variables

Copy these exact variable names and add your values:

**Required:**
- `SERPER_API_KEY`
- `OXYLABS_USERNAME`
- `OXYLABS_PASSWORD`
- `GROK_API_KEY` (or `GROK_API_KEY_1` and `GROK_API_KEY_2`)
- `REDIS_URL`
- `CELERY_BROKER_URL` (can be same as `REDIS_URL`)
- `CELERY_RESULT_BACKEND` (can be same as `REDIS_URL`)

## Troubleshooting

### If async tasks stay "pending" forever:
**This is your current issue!**
- ✅ Make sure you've deployed the **Celery worker service** (see Step 4)
- ✅ Check worker service logs to verify it's running
- ✅ Verify worker has the same Redis URL as web service
- ✅ Ensure worker has all API keys (SERPER, OXYLABS, GROK)
- Test with: Create a task, then check worker logs for processing

### If tasks return "task does not exist":
- Celery returns "PENDING" for both non-existent tasks AND unprocessed tasks
- Check if you're using a valid task_id from a POST /async response
- If you just created the task, wait a few seconds for worker to pick it up

### If Redis connection fails:
- Make sure Redis service is running
- Use `REDIS_URL_PRIVATE` if available (internal Railway network)
- Check Redis service logs
- Ensure both web AND worker services use the same REDIS_URL

### If API keys are missing:
- Verify all required variables are set in BOTH services (web + worker)
- Check variable names match exactly (case-sensitive)
- Redeploy after adding variables

### If deployment fails:
- Check **"Deploy Logs"** for specific errors
- Verify Dockerfile builds correctly
- Ensure all required environment variables are present

### If worker keeps crashing:
- Check worker logs for errors
- Verify API keys are correct
- Ensure Redis is accessible
- Try reducing concurrency: `--concurrency=2`
