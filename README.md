# Team Size Webhook API

High-throughput webhook API for enriching real estate agent data with team size information using AI-powered analysis.

## Features

- **Synchronous Mode**: Direct enrichment for immediate results (for n8n/webhooks)
- **Asynchronous Mode**: Task queue for high-throughput processing (4000+ req/min)
- **Rate Limiting**: Redis-based distributed rate limiting
- **AI Analysis**: Grok AI for intelligent team size estimation
- **Horizontal Scaling**: Scale Celery workers for increased throughput

## Architecture

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

## Quick Start

### 1. Clone and Configure

```bash
# Clone the repository
git clone <repo-url>
cd team-size-webhook

# Copy environment file
cp .env.example .env.local

# Edit with your API keys
nano .env.local
```

### 2. Configure Environment Variables

Create `.env.local` with your credentials:

```env
# Required API Keys
SERPER_API_KEY=your_serper_key
OXYLABS_USERNAME=your_oxylabs_username
OXYLABS_PASSWORD=your_oxylabs_password
GROK_API_KEY=your_grok_key

# Optional: Multiple Grok keys for load balancing
GROK_API_KEY_1=key1
GROK_API_KEY_2=key2
GROK_API_KEY_3=key3

# Server Configuration
HOST=0.0.0.0
PORT=8000
WORKERS=4
LOG_LEVEL=INFO
DEBUG=false

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60

# Async Processing
ASYNC_PROCESSING_ENABLED=true
```

### 3. Run with Docker (Recommended)

```bash
# Start all services (API + Redis + Celery worker)
docker-compose up --build -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

The API will be available at `http://localhost:8000`

### 4. Run Locally (Development)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start Redis (required)
docker run -d -p 6379:6379 redis:7-alpine

# Start API
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Start Celery worker (new terminal)
celery -A src.worker.celery_app worker --loglevel=info
```

## API Endpoints

### Health Checks

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /health` | GET | Liveness check |
| `GET /ready` | GET | Readiness check (verifies API keys) |

### Enrichment

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/v1/enrich` | POST | Synchronous enrichment (waits for result) |
| `POST /api/v1/enrich/async` | POST | Async enrichment (returns task_id) |
| `GET /api/v1/enrich/tasks/{task_id}` | GET | Check async task status |
| `DELETE /api/v1/enrich/tasks/{task_id}` | DELETE | Cancel async task |
| `POST /api/v1/enrich/batch` | POST | Batch enrichment (up to 100 items) |

### Example Request

```bash
# Synchronous enrichment
curl -X POST http://localhost:8000/api/v1/enrich \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "uuid-123",
    "full_name": "John Smith",
    "organization_names": ["Smith Realty Group"],
    "email": ["john@smithrealty.com"],
    "city": "Austin",
    "state": "TX"
  }'
```

### Example Response

```json
{
  "status": "success",
  "agent_id": "uuid-123",
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

## Deployment to VPS

### Prerequisites

- VPS with Docker and Docker Compose installed
- Domain name (optional, for SSL)
- API keys for Serper, Oxylabs, and Grok

### Step 1: Prepare VPS

```bash
# SSH into your VPS
ssh user@your-vps-ip

# Install Docker (if not installed)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get update
sudo apt-get install docker-compose-plugin
```

### Step 2: Deploy Application

```bash
# Clone repository
git clone <repo-url> /opt/team-size-webhook
cd /opt/team-size-webhook

# Create environment file
cp .env.example .env.local
nano .env.local  # Add your API keys

# Deploy with production settings
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Verify deployment
docker-compose ps
curl http://localhost:8000/health
```

### Step 3: Scale Workers (Optional)

```bash
# Scale to 4 Celery workers for higher throughput
docker-compose up -d --scale celery-worker=4
```

### Step 4: Enable Monitoring (Optional)

```bash
# Start with Flower monitoring dashboard
docker-compose --profile monitoring up -d

# Access Flower at http://your-vps-ip:5555
# Default credentials: admin/admin (change in .env.local)
```

### Step 5: Setup Reverse Proxy (Optional)

For SSL/HTTPS, use nginx or Caddy as a reverse proxy:

```nginx
# /etc/nginx/sites-available/team-size-api
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

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

## Performance

Based on load testing:

| Concurrency | Throughput | Success Rate |
|-------------|------------|--------------|
| 100 | 1,534 req/s | 100% |
| 500 | 1,148 req/s | 100% |
| 1000 | 886 req/s | 100% |

**Capacity**: 4000+ requests/minute with horizontal scaling

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SERPER_API_KEY` | Yes | - | Serper API key for web search |
| `OXYLABS_USERNAME` | Yes | - | Oxylabs username for scraping |
| `OXYLABS_PASSWORD` | Yes | - | Oxylabs password |
| `GROK_API_KEY` | Yes | - | Grok AI API key |
| `REDIS_URL` | No | redis://localhost:6379/0 | Redis connection URL |
| `RATE_LIMIT_ENABLED` | No | true | Enable rate limiting |
| `RATE_LIMIT_REQUESTS` | No | 100 | Max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | No | 60 | Rate limit window |
| `ASYNC_PROCESSING_ENABLED` | No | false | Enable async endpoints |
| `WORKERS` | No | 4 | Uvicorn workers |
| `CELERY_CONCURRENCY` | No | 8 | Celery worker concurrency |

## Project Structure

```
team-size-webhook/
├── src/
│   ├── main.py                 # FastAPI entry point
│   ├── config/settings.py      # Configuration
│   ├── api/
│   │   └── v1/endpoints/       # API endpoints
│   ├── services/               # Business logic
│   ├── clients/                # External API clients
│   ├── worker/                 # Celery tasks
│   └── core/                   # Logging, exceptions, Redis
├── tests/                      # Test suite (117 tests)
├── Dockerfile                  # Container image
├── docker-compose.yml          # Development setup
├── docker-compose.prod.yml     # Production overrides
├── requirements.txt            # Dependencies
└── README.md                   # This file
```

## Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run load tests
pytest tests/test_load.py -v
```

## Troubleshooting

### Container won't start

```bash
# Check logs
docker-compose logs web

# Verify API keys are set
docker-compose exec web env | grep API_KEY
```

### Rate limit errors (429)

```bash
# Increase rate limit
RATE_LIMIT_REQUESTS=1000 docker-compose up -d
```

### Redis connection errors

```bash
# Check Redis is running
docker-compose ps redis
docker-compose logs redis
```

### Slow responses

```bash
# Scale workers
docker-compose up -d --scale celery-worker=4

# Check Celery queue
docker-compose exec celery-worker celery -A src.worker.celery_app inspect active
```

## License

MIT
