"""
Team Size Estimator - Async High-Performance Version
Processes real estate agents to determine team sizes using AI analysis.
"""

import os
import sys
import json
import logging
import base64
import time
import argparse
import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Set, Tuple
from urllib.parse import urljoin, urlparse
from pathlib import Path

import aiohttp
from aiohttp import TCPConnector, ClientTimeout
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from dotenv import load_dotenv
from xai_sdk import Client
from xai_sdk.chat import user
from bs4 import BeautifulSoup
from prompts import (
    WEBSITE_ASSESSMENT_PROMPT, WebsiteAssessment,
    TEAM_PAGE_SELECTION_PROMPT, TeamPageSelection,
    TEAM_SIZE_ANALYSIS_PROMPT, TeamSizeAnalysis,
    TEAM_BROKERAGE_EXTRACTION_PROMPT, TeamBrokerageExtraction
)

MIN_HTML_BYTES = 3500
BLOCKED_DOMAIN_KEYWORDS = {"linkedin.com", "facebook.com", "instagram.com", "twitter.com", "idxbroker.com", "zillow.com", "realtor.com"}
DEAD_CONTENT_SNIPPETS = ["page not found", "404 not found", "coming soon", "domain expired", "site has been archived", "under construction", "loading, please wait", "this site is parked", "IDX search", "sign in to view this page"]

env_local_path = Path(__file__).parent / ".env.local"
env_path = Path(__file__).parent / ".env"
if env_local_path.exists():
    load_dotenv(env_local_path, override=True)
    print("✓ Loaded .env.local")
elif env_path.exists():
    load_dotenv(env_path, override=True)
    print("✓ Loaded .env")

def _get_env_int(n, d): 
    r = os.getenv(n)
    return int(r) if r and r.strip() else d

def _get_env_float(n, d):
    r = os.getenv(n)
    return float(r) if r and r.strip() else d

def _get_env_bool(n, d):
    r = os.getenv(n)
    return r.strip().lower() in {"1", "true", "yes"} if r else d

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
OXYLABS_USERNAME = os.getenv("OXYLABS_USERNAME")
OXYLABS_PASSWORD = os.getenv("OXYLABS_PASSWORD")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_API_KEY_1 = os.getenv("GROK_API_KEY_1")
GROK_API_KEY_2 = os.getenv("GROK_API_KEY_2")
PAGE_FETCH_WEBHOOK_URL = os.getenv("PAGE_FETCH_WEBHOOK_URL", "").strip() or None
SECONDARY_PAGE_FETCH_WEBHOOK_URL = os.getenv("SECONDARY_PAGE_FETCH_WEBHOOK_URL", "").strip() or None
TERTIARY_PAGE_FETCH_WEBHOOK_URL = os.getenv("TERTIARY_PAGE_FETCH_WEBHOOK_URL", "").strip() or None
DEFAULT_FETCH_LIMIT = _get_env_int("FETCH_LIMIT", 50)
MAX_WORKERS = _get_env_int("MAX_WORKERS", 100)
WEBHOOK_ENABLED = _get_env_bool("WEBHOOK_ENABLED", True)
WEBHOOK_RATE_LIMIT = _get_env_float("WEBHOOK_RATE_LIMIT", 100.0)
WEBHOOK_QUEUE_SIZE = _get_env_int("WEBHOOK_QUEUE_SIZE", 5000)
WEBHOOK_WORKERS = _get_env_int("WEBHOOK_WORKERS", 20)
POSTGRES_CONFIG = {"host": os.getenv("POSTGRES_HOST"), "port": int(os.getenv("POSTGRES_PORT", 5432)), "dbname": os.getenv("POSTGRES_DB"), "user": os.getenv("POSTGRES_USER"), "password": os.getenv("POSTGRES_PASSWORD")}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format="%(asctime)s - %(levelname)s - %(name)s - %(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)
logger.info(f"\n{'='*80}\n🚀 NEW RUN STARTED (ASYNC MODE)\n{'='*80}")

def get_ist_timestamp():
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


class AsyncDatabaseManager:
    def __init__(self, config, min_conn=10, max_conn=50):
        self.config = config
        self.min_conn = min_conn
        self.max_conn = max_conn
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        conninfo = db_url if db_url else f"host={self.config['host']} port={self.config['port']} dbname={self.config['dbname']} user={self.config['user']} password={self.config['password']}"
        self.pool = AsyncConnectionPool(conninfo, min_size=self.min_conn, max_size=self.max_conn, kwargs={"row_factory": dict_row}, open=False)
        await self.pool.open()
        logger.info(f"✓ Connected to PostgreSQL (pool: {self.min_conn}-{self.max_conn})")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()
        logger.info("✓ Disconnected from database")

    async def fetch_agents_without_team_size(self, limit=100):
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM public.new_unified_agents WHERE team_size_count is null AND source IS NOT NULL AND array_to_string(source, ',') ILIKE %s LIMIT %s;", ('%data_bhhs%', limit))
                agents = await cur.fetchall()
                logger.info(f"✓ Fetched {len(agents)} agents")
                return agents

    async def update_agent_team_size(self, uuid, team_size, team_members, team_size_text=None, team_page_url=None, team_size_reasoning=None, agent_designation=None):
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE public.new_unified_agents SET team_size_count=%s, team_size=CASE WHEN %s IN (0,-1,-2) THEN 'Unknown' WHEN %s=1 THEN 'Individual' WHEN %s<=5 THEN 'Small' WHEN %s<=10 THEN 'Medium' WHEN %s<=20 THEN 'Large' ELSE 'Mega' END, team_page_url=%s, updated_at=%s WHERE supabase_uuid=%s AND %s IS NOT NULL;", (team_size,team_size,team_size,team_size,team_size,team_size,team_page_url,get_ist_timestamp(),uuid,team_size))
                if agent_designation is not None:
                    agent_designation_array = agent_designation if isinstance(agent_designation, list) else ([agent_designation] if agent_designation else [])
                    await cur.execute("UPDATE public.new_unified_agents SET agent_designation=%s WHERE supabase_uuid=%s;", (agent_designation_array, uuid))
                if team_members is not None or team_size_reasoning:
                    nr = team_size_reasoning.strip() if isinstance(team_size_reasoning, str) else None
                    await cur.execute("INSERT INTO public.company_info (uuid, team_members, analysis) VALUES (%s,%s,%s) ON CONFLICT (uuid) DO UPDATE SET team_members=COALESCE(EXCLUDED.team_members, public.company_info.team_members), analysis=COALESCE(EXCLUDED.analysis, public.company_info.analysis);", (uuid, json.dumps(team_members) if team_members else None, nr))
            await conn.commit()

    async def update_agent_team_brokerage(self, uuid, team_name, brokerage_name):
        tn = team_name.strip() if team_name and team_name.strip().lower() != "null" else 'NA'
        bn = brokerage_name.strip() if brokerage_name and brokerage_name.strip().lower() != "null" else 'NA'
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE public.new_unified_agents SET team_name=%s, brokerage_name=%s, updated_at=%s WHERE supabase_uuid=%s;", (tn, bn, get_ist_timestamp(), uuid))
            await conn.commit()

    async def update_rashi_crm(self, uuid, data):
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE public.new_unified_agents SET rashi_crm=%s, updated_at=%s WHERE supabase_uuid=%s;", (json.dumps(data), get_ist_timestamp(), uuid))
            await conn.commit()


class AsyncSerperClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://google.serper.dev/search"
        self.headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        self.session = None
        self.call_count = 0
        self._lock = asyncio.Lock()

    async def _ensure_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(connector=TCPConnector(limit=100), timeout=ClientTimeout(total=30), headers=self.headers)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def search_places(self, query, location="us"):
        await self._ensure_session()
        async with self._lock:
            self.call_count += 1
        for attempt in range(3):
            try:
                async with self.session.post(self.base_url, json={"q": query, "gl": location}) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        return {}

    def get_call_count(self):
        return self.call_count


class AsyncOxylabsClient:
    def __init__(self, username, password):
        self.base_url = "https://realtime.oxylabs.io/v1/queries"
        creds = f"{username}:{password}"
        self.headers = {"Authorization": f"Basic {base64.b64encode(creds.encode()).decode()}", "Content-Type": "application/json"}
        self.session = None

    async def _ensure_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(connector=TCPConnector(limit=150), timeout=ClientTimeout(total=90), headers=self.headers)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def scrape_url(self, url):
        await self._ensure_session()
        payload = {"source": "universal", "url": url, "geo_location": "United States"}
        for attempt in range(3):
            try:
                async with self.session.post(self.base_url, json=payload) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(5)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    if data.get("results") and len(data["results"]) > 0:
                        r = data["results"][0]
                        return {"content": r.get("content"), "status_code": r.get("status_code"), "final_url": r.get("url") or url}
                    return None
            except asyncio.TimeoutError:
                if attempt == 2:
                    return None
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"  ⚠ Scraping failed: {url[:50]}...")
                if attempt == 2:
                    return None
                await asyncio.sleep(2 ** attempt)
        return None


class AsyncGrokAIClient:
    def __init__(self):
        self.clients = []
        self.current_index = 0
        self._lock = asyncio.Lock()
        # Rate limiting: If both keys are from same team, they share 480 req/min limit
        # Use 4 req/s (240 req/min) per account to be very conservative
        # With 2 accounts: 8 req/s = 480 req/min (at the limit) or 4 req/s = 240 req/min if same team
        # Being conservative: use 3.5 req/s per account = 7 req/s total = 420 req/min (safe buffer)
        self.rate_limit_per_account = 3.5  # requests per second per account (210 req/min)
        self.min_interval = 1.0 / self.rate_limit_per_account  # ~0.286 seconds between requests per account
        # Track last request time per client
        self.last_request_times = []
        self._rate_locks = []
        api_keys = []
        if GROK_API_KEY_1:
            api_keys.append(GROK_API_KEY_1)
        if GROK_API_KEY_2:
            api_keys.append(GROK_API_KEY_2)
        if not api_keys and GROK_API_KEY:
            api_keys.append(GROK_API_KEY)
        if not api_keys:
            raise ValueError("GROK_API_KEY required")
        for idx, key in enumerate(api_keys, 1):
            self.clients.append(Client(api_key=key, timeout=3600))
            self.last_request_times.append(0.0)
            self._rate_locks.append(asyncio.Lock())
            logger.info(f"✓ Grok client {idx} initialized")
        self.model_name = "grok-4-1-fast-non-reasoning"
        total_rate = self.rate_limit_per_account * len(self.clients)
        logger.info(f"✓ Grok: {len(self.clients)} client(s), model: {self.model_name}, rate limit: {self.rate_limit_per_account} req/s per account ({total_rate} req/s total)")

    async def _get_client(self):
        async with self._lock:
            idx = self.current_index
            c = self.clients[idx]
            self.current_index = (self.current_index + 1) % len(self.clients)
            return c, idx

    async def _rate_limit(self, client_index):
        """Rate limit per account to stay under 480 requests/minute (8 req/s per account)"""
        async with self._rate_locks[client_index]:
            now = time.time()
            elapsed = now - self.last_request_times[client_index]
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                await asyncio.sleep(sleep_time)
            self.last_request_times[client_index] = time.time()

    def _html_to_markdown(self, html):
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "meta", "link"]):
                tag.decompose()
            return "\n\n".join([l.strip() for l in soup.get_text(separator="\n", strip=True).split("\n") if l.strip()])
        except:
            return ""

    def _sync_select_team_pages(self, client, urls):
        prompt = TEAM_PAGE_SELECTION_PROMPT.format(urls=json.dumps(urls[:100], indent=2))
        chat = client.chat.create(model=self.model_name, response_format=TeamPageSelection)
        chat.append(user(prompt))
        resp = chat.sample()
        if isinstance(resp.content, str):
            r = TeamPageSelection.model_validate_json(resp.content)
            return {"selectedUrl": r.selectedUrl, "reasoning": r.reasoning}
        return {"selectedUrl": "", "reasoning": "Parse failed"}

    async def select_best_team_pages(self, urls):
        client, client_idx = await self._get_client()
        await self._rate_limit(client_idx)
        for attempt in range(3):
            try:
                return await asyncio.to_thread(self._sync_select_team_pages, client, urls)
            except Exception as e:
                error_msg = str(e).lower()
                # Check for credit/quota related errors - re-raise immediately
                if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment", "resource_exhausted"]):
                    # Rate limit hit - wait longer before retry
                    if attempt < 2:
                        await asyncio.sleep(5 + (2 ** attempt))  # Wait 5+ seconds for rate limit
                    raise
                if attempt == 2:
                    return {"selectedUrl": "", "reasoning": str(e)}
                await asyncio.sleep(2 ** attempt)
        return {"selectedUrl": "", "reasoning": "Max retries"}

    def _sync_analyze_team_size(self, client, html, agent_full_name=""):
        md = self._html_to_markdown(html)
        prompt = TEAM_SIZE_ANALYSIS_PROMPT.format(markdown_content=md, agent_full_name=agent_full_name or "")
        chat = client.chat.create(model=self.model_name, response_format=TeamSizeAnalysis)
        chat.append(user(prompt))
        resp = chat.sample()
        r = TeamSizeAnalysis.model_validate_json(resp.content) if isinstance(resp.content, str) else resp.content
        def gv(o, f, d=None):
            return getattr(o, f, d) if hasattr(o, f) else o.get(f, d) if isinstance(o, dict) else d
        tm = gv(r, "teamMembers", [])
        if not isinstance(tm, list):
            tm = []
        ts = gv(r, "teamSize")
        if ts is not None:
            return {"teamSize": ts, "confidence": gv(r, "confidence"), "teamMembers": [m.model_dump() if hasattr(m, 'model_dump') else m for m in tm[:50]], "reasoning": gv(r, "reasoning")}
        return {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": "Analysis failed"}

    async def analyze_team_size(self, html, agent_full_name=""):
        client, client_idx = await self._get_client()
        await self._rate_limit(client_idx)
        last_res = {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": "Analysis failed"}
        for attempt in range(3):
            try:
                res = await asyncio.to_thread(self._sync_analyze_team_size, client, html, agent_full_name)
                if res.get("teamSize") != -2:
                    return res
                last_res = res
            except Exception as e:
                error_msg = str(e).lower()
                # Check for credit/quota related errors
                if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment", "resource_exhausted"]):
                    # Rate limit hit - wait longer before retry
                    if attempt < 2:
                        await asyncio.sleep(5 + (2 ** attempt))  # Wait 5+ seconds for rate limit
                    # Re-raise credit errors so they can be caught and tracked properly
                    raise
                last_res = {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": str(e)}
            
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
        return last_res

    def _sync_assess_website(self, client, agent, serper, exclude):
        org_list = agent.get('organization_names', [])
        org = org_list[0] if org_list else 'N/A'
        fn = str(agent.get("full_name") or "").strip() or f"{str(agent.get('first_name') or '')} {str(agent.get('last_name') or '')}".strip()
        ph = agent.get('phone', ['N/A'])[0] if agent.get('phone') else 'N/A'
        em = agent.get('email', ['N/A'])[0] if agent.get('email') else 'N/A'
        on = agent.get('office_number', 'N/A')
        if isinstance(on, list):
            on = on[0] if on else 'N/A'
        wc = agent.get('website_clean', 'N/A')
        city = agent.get('city', 'N/A')
        if isinstance(city, list):
            city = city[0] if city else 'N/A'
        state = agent.get('state', 'N/A')
        if isinstance(state, list):
            state = state[0] if state else 'N/A'
        ex = f"\nDo NOT return: {exclude}\n" if exclude else ""
        prompt = WEBSITE_ASSESSMENT_PROMPT.format(organization_name=org, full_name=fn, phone=ph, email=em, office_number=on, city=city, state=state, website_clean=wc, serper_results=json.dumps(serper.get('organic', [])[:8], indent=2), exclude_text=ex)
        chat = client.chat.create(model=self.model_name, response_format=WebsiteAssessment)
        chat.append(user(prompt))
        resp = chat.sample()
        r = WebsiteAssessment.model_validate_json(resp.content) if isinstance(resp.content, str) else resp.content
        if r and (hasattr(r, 'url') or isinstance(r, dict)):
            return {"url": r.url if hasattr(r, 'url') else r.get("url", ""), "reason": r.reason if hasattr(r, 'reason') else r.get("reason", "")}
        return {"url": "", "reason": "Parse failed"}

    async def assess_website(self, agent, serper, exclude=None):
        client, client_idx = await self._get_client()
        await self._rate_limit(client_idx)
        for attempt in range(3):
            try:
                return await asyncio.to_thread(self._sync_assess_website, client, agent, serper, exclude)
            except Exception as e:
                error_msg = str(e).lower()
                # Check for credit/quota related errors - re-raise immediately
                if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment", "resource_exhausted"]):
                    # Rate limit hit - wait longer before retry
                    if attempt < 2:
                        await asyncio.sleep(5 + (2 ** attempt))  # Wait 5+ seconds for rate limit
                    raise
                if attempt == 2:
                    return {"url": "", "reason": str(e)}
                await asyncio.sleep(2 ** attempt)
        return {"url": "", "reason": "Max retries"}

    def _sync_extract_brokerage(self, client, md, url):
        prompt = TEAM_BROKERAGE_EXTRACTION_PROMPT.format(content=md, homepage_url=url)
        chat = client.chat.create(model=self.model_name, response_format=TeamBrokerageExtraction)
        chat.append(user(prompt))
        resp = chat.sample()
        r = TeamBrokerageExtraction.model_validate_json(resp.content) if isinstance(resp.content, str) else resp.content
        def gv(o, f, d=None):
            return getattr(o, f, d) if hasattr(o, f) else o.get(f, d) if isinstance(o, dict) else d
        return {"team_name": gv(r, "team_name"), "brokerage_name": gv(r, "brokerage_name")}

    async def extract_team_brokerage(self, md, url):
        client, client_idx = await self._get_client()
        await self._rate_limit(client_idx)
        for attempt in range(3):
            try:
                return await asyncio.to_thread(self._sync_extract_brokerage, client, md, url)
            except:
                if attempt == 2:
                    return {"team_name": None, "brokerage_name": None}
                await asyncio.sleep(2 ** attempt)
        return {"team_name": None, "brokerage_name": None}


class LinkExtractor:
    @staticmethod
    def extract_all_links(html, base_url):
        try:
            soup = BeautifulSoup(html, "html.parser")
            links = [urljoin(base_url, tag.get("href", "").strip()) for tag in soup.find_all("a", href=True) if tag.get("href", "").strip() and not tag.get("href", "").startswith(("#", "mailto:", "tel:"))]
            return list(dict.fromkeys(links))
        except:
            return []


class AsyncWebhookManager:
    def __init__(self, rate_limit=100.0, queue_size=5000, num_workers=20):
        self.interval = 1.0 / rate_limit if rate_limit > 0 else 0.01
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.num_workers = num_workers
        self.workers = []
        self.stop_event = asyncio.Event()
        self.session = None
        self.total_sent = 0
        self.total_failed = 0
        self._lock = asyncio.Lock()

    async def start(self):
        self.session = aiohttp.ClientSession(connector=TCPConnector(limit=100), timeout=ClientTimeout(total=30))
        for i in range(self.num_workers):
            self.workers.append(asyncio.create_task(self._worker()))
        logger.info(f"✓ Webhook manager: {self.num_workers} workers")

    async def stop(self):
        await self.queue.join()
        self.stop_event.set()
        for w in self.workers:
            w.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        if self.session:
            await self.session.close()
        logger.info(f"✓ Webhooks: sent={self.total_sent}, failed={self.total_failed}")

    async def queue_webhook(self, target, payload):
        try:
            await asyncio.wait_for(self.queue.put((target, payload)), timeout=60.0)
        except asyncio.TimeoutError:
            async with self._lock:
                self.total_failed += 1

    async def _worker(self):
        while not self.stop_event.is_set():
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                target, payload = item
                try:
                    if not self.session or self.session.closed:
                        logger.error("Webhook session not available, recreating...")
                        self.session = aiohttp.ClientSession(connector=TCPConnector(limit=100), timeout=ClientTimeout(total=30))
                    async with self.session.post(target, json=payload) as resp:
                        await resp.read()
                        if resp.status >= 400:
                            logger.warning(f"Webhook failed with status {resp.status} for {target[:50]}...")
                            async with self._lock:
                                self.total_failed += 1
                        else:
                            async with self._lock:
                                self.total_sent += 1
                except Exception as e:
                    logger.warning(f"Webhook error for {target[:50]}...: {str(e)[:100]}")
                    async with self._lock:
                        self.total_failed += 1
                self.queue.task_done()
                await asyncio.sleep(self.interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_stats(self):
        return {"queue_size": self.queue.qsize(), "total_sent": self.total_sent, "total_failed": self.total_failed}


class AsyncProgressTracker:
    # Failure reason constants
    FAIL_NO_SEARCH_QUERY = "no_search_query"
    FAIL_SERPER_NO_RESULTS = "serper_no_results"
    FAIL_SERPER_ERROR = "serper_error"
    FAIL_GROK_NO_URL = "grok_no_url_selected"
    FAIL_BLOCKED_DOMAIN = "blocked_domain"
    FAIL_SCRAPE_FAILED = "scrape_failed"
    FAIL_LOW_QUALITY_HTML = "low_quality_html"
    FAIL_GROK_ANALYSIS = "grok_analysis_failed"
    FAIL_TEAM_SIZE_ZERO = "team_size_zero"
    FAIL_EXCEPTION = "exception"

    def __init__(self, total, webhook_mgr):
        self.total = total
        self.webhook_mgr = webhook_mgr
        self.processed = 0
        self.successful = 0
        self.failed = 0
        self.failure_reasons = {}
        self._lock = asyncio.Lock()
        self.start_time = time.time()

    async def update(self, success, failure_reason=None):
        async with self._lock:
            self.processed += 1
            if success:
                self.successful += 1
            else:
                self.failed += 1
                if failure_reason:
                    self.failure_reasons[failure_reason] = self.failure_reasons.get(failure_reason, 0) + 1

    def display(self):
        elapsed = time.time() - self.start_time
        pct = (self.processed / self.total * 100) if self.total > 0 else 0
        rate = self.processed / elapsed if elapsed > 0 else 0
        rem = self.total - self.processed
        eta = rem / rate if rate > 0 else 0
        ws = self.webhook_mgr.get_stats()
        print(f"\r📊 {self.processed}/{self.total} ({pct:.1f}%) | ✓{self.successful} ✗{self.failed} | {rate:.2f}/s | ETA:{int(eta//60)}m{int(eta%60)}s | Q:{ws['queue_size']} S:{ws['total_sent']}", end="", flush=True)

    def get_failure_breakdown(self):
        if not self.failure_reasons:
            return "  No failures recorded"
        labels = {
            self.FAIL_NO_SEARCH_QUERY: "No search query (missing name/org/email)",
            self.FAIL_SERPER_NO_RESULTS: "Serper returned no results",
            self.FAIL_SERPER_ERROR: "Serper API error",
            self.FAIL_GROK_NO_URL: "Grok couldn't select a valid URL",
            self.FAIL_BLOCKED_DOMAIN: "Domain is blocked (linkedin, etc.)",
            self.FAIL_SCRAPE_FAILED: "Oxylabs scraping failed",
            self.FAIL_LOW_QUALITY_HTML: "Low quality HTML (404, too small)",
            self.FAIL_GROK_ANALYSIS: "Grok team size analysis failed",
            self.FAIL_TEAM_SIZE_ZERO: "Team size returned as 0",
            self.FAIL_EXCEPTION: "Unexpected exception",
        }
        lines = []
        for reason, count in sorted(self.failure_reasons.items(), key=lambda x: x[1], reverse=True):
            pct = (count / self.failed * 100) if self.failed > 0 else 0
            lines.append(f"  • {labels.get(reason, reason)}: {count} ({pct:.1f}%)")
        return "\n".join(lines)


class TechnologyDetector:
    CRM_SIGNATURES = {
        'Follow Up Boss': [r'\bfollowupboss\.com', r'window\.FUB'],
        'KVCore': [r'\bkvcore\.com', r'window\.kvCore'],
        'Ylopo': [r'\bylopo\.com', r'window\.YLOPO'],
        'WordPress': [r'\bwp-content\b', r'\bwp-includes\b'],
        'Squarespace': [r'\bsquarespace\.com'],
        'Wix': [r'\bwix\.com'],
    }

    @staticmethod
    def detect(html):
        if not html:
            return [{"detectedCRMs": ["Not Found"], "detectedEmailTools": ["Not Found"]}]
        crms = [name for name, patterns in TechnologyDetector.CRM_SIGNATURES.items() if any(re.search(p, html, re.IGNORECASE) for p in patterns)]
        return [{"detectedCRMs": crms or ["Not Found"], "detectedEmailTools": ["Not Found"]}]


class AsyncWorkflowExecutor:
    def __init__(self, db, serper, oxylabs, grok, max_concurrency=100):
        self.db = db
        self.serper = serper
        self.oxylabs = oxylabs
        self.grok = grok
        self.link_extractor = LinkExtractor()
        self.failed_domains = set()
        self.failed_urls = {}  # URL -> timestamp of last failure
        self.failed_url_ttl = 3600  # Don't retry failed URLs for 1 hour
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.webhook_mgr = AsyncWebhookManager(rate_limit=WEBHOOK_RATE_LIMIT, queue_size=WEBHOOK_QUEUE_SIZE, num_workers=WEBHOOK_WORKERS)
        # API failure tracking - track consecutive failures with time window
        self.api_failures = {
            "grok": 0,
            "oxylabs": 0,
            "serper": 0,
            "timeout": 0
        }
        self.api_last_success_time = {
            "grok": 0.0,
            "oxylabs": 0.0,
            "serper": 0.0,
            "timeout": 0.0
        }
        self.api_failure_times = {
            "grok": [],
            "oxylabs": [],
            "serper": [],
            "timeout": []
        }
        self.MAX_API_FAILURES = 50
        self.FAILURE_WINDOW_SECONDS = 60  # Only count failures within this window
        self._should_stop = False
        self._stop_lock = asyncio.Lock()

    async def _record_api_failure(self, api_name):
        """Record an API failure and check if we should stop"""
        async with self._stop_lock:
            now = time.time()
            # Remove failures older than the window
            self.api_failure_times[api_name] = [
                t for t in self.api_failure_times[api_name] 
                if now - t < self.FAILURE_WINDOW_SECONDS
            ]
            
            # Only count as consecutive failure if no success occurred recently
            # (within the same time window)
            if now - self.api_last_success_time[api_name] < self.FAILURE_WINDOW_SECONDS:
                # Recent success exists, reset consecutive failures
                self.api_failures[api_name] = 0
                self.api_failure_times[api_name] = []
            
            # Add this failure
            self.api_failure_times[api_name].append(now)
            self.api_failures[api_name] = len(self.api_failure_times[api_name])
            
            if self.api_failures[api_name] >= self.MAX_API_FAILURES:
                self._should_stop = True
                logger.error(f"\n{'='*70}\n🚨 STOPPING WORKFLOW: {api_name.upper()} has {self.api_failures[api_name]} consecutive failures in {self.FAILURE_WINDOW_SECONDS}s window (threshold: {self.MAX_API_FAILURES})\n{'='*70}")
                return True
        return False

    async def _record_api_success(self, api_name):
        """Reset failure counter on success"""
        async with self._stop_lock:
            now = time.time()
            # Only log recovery if we had significant failures (>= 5) to reduce noise
            if self.api_failures[api_name] >= 5:
                logger.info(f"✓ {api_name.upper()} recovered after {self.api_failures[api_name]} failures")
            # Reset counters and record success time
            self.api_failures[api_name] = 0
            self.api_failure_times[api_name] = []
            self.api_last_success_time[api_name] = now

    async def _check_should_stop(self):
        """Check if workflow should stop"""
        async with self._stop_lock:
            return self._should_stop

    def _extract_domain(self, url):
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower().lstrip("www.") if parsed.netloc else None
        except:
            return None

    def _should_skip(self, url):
        d = self._extract_domain(url)
        if not d:
            return False
        # Check if domain is blocked
        if d in self.failed_domains or any(d == kw or d.endswith('.' + kw) for kw in BLOCKED_DOMAIN_KEYWORDS):
            return True
        # Check if URL failed recently (circuit breaker)
        if url in self.failed_urls:
            last_failure = self.failed_urls[url]
            if time.time() - last_failure < self.failed_url_ttl:
                return True
            else:
                # TTL expired, remove from cache
                del self.failed_urls[url]
        return False

    def _mark_bad(self, url):
        d = self._extract_domain(url)
        if d:
            self.failed_domains.add(d)
        # Also mark the specific URL as failed
        self.failed_urls[url] = time.time()

    def _html_to_markdown(self, html):
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "meta", "link"]):
                tag.decompose()
            return "\n\n".join([l.strip() for l in soup.get_text(separator="\n", strip=True).split("\n") if l.strip()])
        except:
            return ""

    async def _send_webhook(self, uuid, src, content, homepage=None):
        if not uuid or not content or not WEBHOOK_ENABLED:
            if not WEBHOOK_ENABLED:
                logger.debug(f"Webhooks disabled, skipping webhook for {uuid}")
            return
        targets = list(dict.fromkeys([t for t in [PAGE_FETCH_WEBHOOK_URL, SECONDARY_PAGE_FETCH_WEBHOOK_URL, TERTIARY_PAGE_FETCH_WEBHOOK_URL] if t]))
        if not targets:
            logger.warning(f"No webhook URLs configured, skipping webhook for {uuid}")
            return
        md = self._html_to_markdown(content)
        # Convert UUID to string for JSON serialization
        uuid_str = str(uuid) if uuid else None
        for t in targets:
            payload = {"uuid": uuid_str, "source_url": src, "homepage_url": homepage, "content": md or content}
            if t == TERTIARY_PAGE_FETCH_WEBHOOK_URL:
                payload.pop("content", None)
            await self.webhook_mgr.queue_webhook(t, payload)

    async def _scrape(self, url):
        # Add timeout wrapper to prevent hanging
        try:
            r = await asyncio.wait_for(self.oxylabs.scrape_url(url), timeout=300.0)
            if not r:
                if await self._record_api_failure("oxylabs"):
                    return None, None, None
                return None, None, None
            await self._record_api_success("oxylabs")
            return r.get("content"), r.get("status_code"), r.get("final_url") or url
        except asyncio.TimeoutError:
            logger.warning(f"  ⚠ Scrape timeout: {url[:50]}...")
            self._mark_bad(url)
            if await self._record_api_failure("oxylabs"):
                return None, None, None
            return None, None, None
        except Exception as e:
            logger.warning(f"  ⚠ Scrape error: {url[:50]}... - {str(e)[:50]}")
            if await self._record_api_failure("oxylabs"):
                return None, None, None
            return None, None, None

    def _is_low_quality(self, content, status):
        if status and status != 200:
            return True
        if not content or len(content) < MIN_HTML_BYTES:
            return True
        return any(s in content[:8000].lower() for s in DEAD_CONTENT_SNIPPETS)

    def _clean_org(self, name):
        if not name:
            return ""
        name = str(name).strip()
        for p in [r'\s*\(.*?\)', r'\s*-\s*Team', r'\s*-\s*Group', r'\s*\|\s*.*']:
            name = re.sub(p, '', name, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', name).strip()

    def _extract_agent_designation(self, agent_full_name, team_members):
        """Extract agent designation by matching full_name with team members"""
        if not agent_full_name or not team_members:
            return []
        
        agent_full_name = str(agent_full_name).strip().lower()
        if not agent_full_name:
            return []
        
        # Normalize name for matching (remove extra spaces, handle variations)
        def normalize_name(name):
            if not name:
                return ""
            return re.sub(r'\s+', ' ', str(name).strip().lower())
        
        normalized_agent_name = normalize_name(agent_full_name)
        designations = []
        
        for member in team_members:
            if not isinstance(member, dict):
                continue
            
            member_name = member.get("name", "")
            if not member_name:
                continue
            
            normalized_member_name = normalize_name(member_name)
            
            # Check for exact match or partial match (handle middle names, initials, etc.)
            if normalized_agent_name == normalized_member_name:
                designation = member.get("designation", "").strip()
                if designation:
                    designations.append(designation)
            else:
                # Check if agent name parts match member name (handle "John Smith" vs "John A. Smith")
                agent_parts = set(normalized_agent_name.split())
                member_parts = set(normalized_member_name.split())
                # If at least 2 words match (first and last name), consider it a match
                if len(agent_parts) >= 2 and len(member_parts) >= 2:
                    common_parts = agent_parts.intersection(member_parts)
                    if len(common_parts) >= 2:
                        designation = member.get("designation", "").strip()
                        if designation:
                            designations.append(designation)
        
        # Return unique designations
        return list(dict.fromkeys(designations))

    def _build_queries(self, agent):
        fn = str(agent.get("full_name") or "").strip() or f"{str(agent.get('first_name') or '')} {str(agent.get('last_name') or '')}".strip()
        orgs = agent.get("organization_names", [])
        org = self._clean_org(orgs[0]) if orgs and orgs[0] else ""
        emails = agent.get("email", [])
        email = str(emails[0]).strip() if emails and emails[0] else ""
        queries = []
        if fn and org:
            queries.append(re.sub(r"\s+", " ", f"{fn} {org}").strip())
        if fn and email:
            queries.append(re.sub(r"\s+", " ", f"{fn} {email}").strip())
        return list(dict.fromkeys(queries))

    async def _select_candidate(self, agent, serper, exclude=None):
        """Returns (url, html, failure_reason)"""
        attempts = 0
        curr_exclude = exclude
        last_failure = None
        while attempts < 3:
            if await self._check_should_stop():
                return None, None, "Workflow stopped due to API failures"
            try:
                assessment = await self.grok.assess_website(agent, serper, curr_exclude)
                url = assessment.get("url", "")
                # Empty URL is a valid response (no website found), not an API failure
                if not url:
                    return None, None, AsyncProgressTracker.FAIL_GROK_NO_URL
                await self._record_api_success("grok")
            except Exception as e:
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment"]):
                    logger.error(f"🚨 GROK CREDIT ERROR: {str(e)}")
                    if await self._record_api_failure("grok"):
                        return None, None, "Grok API credit exhausted"
                    return None, None, "Grok API credit exhausted"
                # Record actual API exceptions as failures
                logger.warning(f"⚠ Grok API exception: {str(e)[:100]}")
                if await self._record_api_failure("grok"):
                    return None, None, f"Grok API error: {str(e)[:50]}"
                # Re-raise to let caller handle
                raise
            if self._should_skip(url):
                self._mark_bad(url)
                curr_exclude = url
                attempts += 1
                last_failure = AsyncProgressTracker.FAIL_BLOCKED_DOMAIN
                continue
            html, status, final = await self._scrape(url)
            if not html:
                self._mark_bad(url)
                curr_exclude = url
                attempts += 1
                last_failure = AsyncProgressTracker.FAIL_SCRAPE_FAILED
                continue
            if self._is_low_quality(html, status):
                self._mark_bad(url)
                curr_exclude = url
                attempts += 1
                last_failure = AsyncProgressTracker.FAIL_LOW_QUALITY_HTML
                continue
            return final or url, html, None
        return None, None, last_failure

    async def _process_serper(self, agent, uuid):
        """Returns (url, html, success, failure_reason)"""
        queries = self._build_queries(agent)
        if not queries:
            return None, None, False, AsyncProgressTracker.FAIL_NO_SEARCH_QUERY
        last_failure = AsyncProgressTracker.FAIL_SERPER_NO_RESULTS
        for q in queries:
            try:
                serper = await self.serper.search_places(q)
                await self._record_api_success("serper")
            except Exception as e:
                last_failure = AsyncProgressTracker.FAIL_SERPER_ERROR
                if await self._record_api_failure("serper"):
                    return None, None, False, last_failure
                continue
            if not serper.get("organic"):
                continue
            url, html, fail = await self._select_candidate(agent, serper)
            if url and html:
                return url, html, True, None
            if fail:
                last_failure = fail
        return None, None, False, last_failure

    async def process_agent(self, agent, progress=None):
        uuid = agent.get("supabase_uuid")
        agent_full_name = str(agent.get("full_name") or "").strip() or f"{str(agent.get('first_name') or '')} {str(agent.get('last_name') or '')}".strip()
        async with self.semaphore:
            try:
                # Wrap entire processing in timeout to prevent hanging
                return await asyncio.wait_for(self._process_agent_inner(agent, uuid, agent_full_name, progress), timeout=600.0)
            except asyncio.TimeoutError:
                logger.warning(f"  ⚠ Agent processing timeout: {uuid}")
                if await self._record_api_failure("timeout"):
                    return False
                try:
                    await self.db.update_agent_team_size(uuid, -2, [], "Processing timeout", None, "Processing exceeded 10 minute timeout", [])
                except:
                    pass
                if progress:
                    await progress.update(False, AsyncProgressTracker.FAIL_EXCEPTION)
                return False
            except Exception as e:
                logger.error(f"✗ Error {uuid}: {str(e)[:80]}")
                try:
                    await self.db.update_agent_team_size(uuid, -2, [], str(e)[:50], None, str(e), [])
                except:
                    pass
                if progress:
                    await progress.update(False, AsyncProgressTracker.FAIL_EXCEPTION)
                return False

    async def _process_agent_inner(self, agent, uuid, agent_full_name, progress=None):
        try:
                url, html, success, failure_reason = await self._process_serper(agent, uuid)
                if not success or not html:
                    await self.db.update_agent_team_size(uuid, -2, [], "No website", None, f"Failed: {failure_reason}", [])
                    if progress:
                        await progress.update(False, failure_reason)
                    return False

                links = self.link_extractor.extract_all_links(html, url)
                team_page_url = ""
                homepage_html = html # Save homepage html for double-check
                if links:
                    if await self._check_should_stop():
                        await self.db.update_agent_team_size(uuid, -2, [], "Workflow stopped", None, "Workflow stopped due to API failures", [])
                        if progress:
                            await progress.update(False, "Workflow stopped")
                        return False
                    try:
                        sel = await self.grok.select_best_team_pages(links[:100])
                        # Empty selectedUrl is a valid response (no team page found), not an API failure
                        team_page_url = sel.get("selectedUrl", "")
                        await self._record_api_success("grok")
                    except Exception as e:
                        error_msg = str(e).lower()
                        if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment"]):
                            logger.error(f"🚨 GROK CREDIT ERROR: {str(e)}")
                            if await self._record_api_failure("grok"):
                                return False
                            return False
                        # Record actual API exceptions as failures
                        logger.warning(f"⚠ Grok API exception: {str(e)[:100]}")
                        if await self._record_api_failure("grok"):
                            return False
                        # Re-raise to let caller handle
                        raise
                    if team_page_url and not self._should_skip(team_page_url):
                        tp_html, tp_status, _ = await self._scrape(team_page_url)
                        if tp_html and not self._is_low_quality(tp_html, tp_status):
                            html = tp_html
                    elif team_page_url:
                        self._mark_bad(team_page_url)
                        team_page_url = ""

                final_url = team_page_url or url

                async def extract_brokerage():
                    if url and html:
                        try:
                            md = self._html_to_markdown(html)
                            if md:
                                r = await self.grok.extract_team_brokerage(md, url)
                                # extract_team_brokerage failures are non-critical, don't track as API failures
                                tn = r.get("team_name")
                                bn = r.get("brokerage_name")
                                tn = tn.strip() if tn and isinstance(tn, str) and tn.lower() != "null" else None
                                bn = bn.strip() if bn and isinstance(bn, str) and bn.lower() != "null" else None
                                await self.db.update_agent_team_brokerage(uuid, tn, bn)
                        except:
                            pass

                async def analyze():
                    if await self._check_should_stop():
                        return {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": "Workflow stopped"}
                    try:
                        result = await self.grok.analyze_team_size(html, agent_full_name)
                        # teamSize -2 is a valid response (analysis failed), not an API failure
                        # Only count actual API exceptions as failures
                        await self._record_api_success("grok")
                        return result
                    except Exception as e:
                        error_msg = str(e).lower()
                        if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment"]):
                            logger.error(f"🚨 GROK CREDIT ERROR: {str(e)}")
                            if await self._record_api_failure("grok"):
                                return {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": "Grok API credit exhausted"}
                            return {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": "Grok API credit exhausted"}
                        # Record actual API exceptions as failures
                        logger.warning(f"⚠ Grok API exception: {str(e)[:100]}")
                        if await self._record_api_failure("grok"):
                            return {"teamSize": -2, "confidence": "low", "teamMembers": [], "reasoning": f"Grok API error: {str(e)[:50]}"}
                        # Re-raise to let caller handle
                        raise

                analysis_task = asyncio.create_task(analyze())
                extract_task = asyncio.create_task(extract_brokerage())
                analysis = await analysis_task
                await extract_task

                if await self._check_should_stop():
                    await self.db.update_agent_team_size(uuid, -2, [], "Workflow stopped", None, "Workflow stopped due to API failures", [])
                    if progress:
                        await progress.update(False, "Workflow stopped")
                    return False

                team_size = analysis.get("teamSize", -2)

                # Double-Check Logic: If sub-page yields 0, try Homepage
                if team_size == 0 and team_page_url and homepage_html:
                    if await self._check_should_stop():
                        await self.db.update_agent_team_size(uuid, -2, [], "Workflow stopped", None, "Workflow stopped due to API failures", [])
                        if progress:
                            await progress.update(False, "Workflow stopped")
                        return False
                    try:
                        analysis = await self.grok.analyze_team_size(homepage_html, agent_full_name)
                        # teamSize -2 is a valid response, not an API failure
                        await self._record_api_success("grok")
                        team_size = analysis.get("teamSize", -2)
                    except Exception as e:
                        error_msg = str(e).lower()
                        if any(keyword in error_msg for keyword in ["credit", "quota", "insufficient", "balance", "limit", "exceeded", "429", "402", "payment"]):
                            logger.error(f"🚨 GROK CREDIT ERROR: {str(e)}")
                            if await self._record_api_failure("grok"):
                                return False
                            return False
                        # Record actual API exceptions as failures
                        logger.warning(f"⚠ Grok API exception: {str(e)[:100]}")
                        if await self._record_api_failure("grok"):
                            return False
                        # Re-raise to let caller handle
                        raise
                    if team_size > 0:
                        final_url = url
                        html = homepage_html

                team_members = analysis.get("teamMembers", [])
                confidence = analysis.get("confidence", "low")
                reasoning = analysis.get("reasoning")
                
                # Extract agent designation from team members
                agent_designation = self._extract_agent_designation(agent_full_name, team_members)

                if team_size == -2:
                    await self.db.update_agent_team_size(uuid, team_size, team_members, confidence, final_url, reasoning, agent_designation)
                    if progress:
                        await progress.update(False, AsyncProgressTracker.FAIL_GROK_ANALYSIS)
                    return False

                if team_size == 0:
                    await self.db.update_agent_team_size(uuid, -2, team_members, confidence, final_url, reasoning, agent_designation)
                    if progress:
                        await progress.update(False, AsyncProgressTracker.FAIL_TEAM_SIZE_ZERO)
                    return False

                await self.db.update_agent_team_size(uuid, team_size, team_members, confidence, final_url, reasoning, agent_designation)

                if html:
                    try:
                        tech = TechnologyDetector.detect(html)
                        await self.db.update_rashi_crm(uuid, tech)
                    except:
                        pass

                if team_size > 0:
                    await self._send_webhook(uuid, final_url, html, url)

                if progress:
                    await progress.update(True)
                return True
        except Exception as e:
            # This should not be reached due to outer try-catch, but keep for safety
            raise

    async def run(self, limit=50):
        print(f"\n{'='*70}\n🚀 TEAM SIZE ESTIMATION (ASYNC)\n{'='*70}")
        print(f"Goal: {limit} | Concurrency: {self.semaphore._value}\n{'='*70}\n")

        await self.webhook_mgr.start()
        stats = {"successful": 0, "failed": 0, "total": 0, "failure_breakdown": ""}
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 50
        last_successful_count = 0
        last_failed_count = 0

        try:
            progress = AsyncProgressTracker(limit, self.webhook_mgr)

            while stats["total"] < limit:
                if await self._check_should_stop():
                    logger.warning(f"\n{'='*70}\n⚠️  WORKFLOW STOPPED: API failure threshold reached\n{'='*70}")
                    print(f"\n⚠️  Workflow stopped due to API failures")
                    break

                fetch = min(1000, limit - stats["total"])
                if fetch <= 0:
                    break

                print(f"Fetching {fetch} agents...")
                agents = await self.db.fetch_agents_without_team_size(fetch)
                if not agents:
                    print("No more agents")
                    break

                print(f"✓ Got {len(agents)} agents\n")

                tasks = [self.process_agent(a, progress) for a in agents]
                display_task = asyncio.create_task(self._display_loop(progress))
                await asyncio.gather(*tasks, return_exceptions=True)
                display_task.cancel()
                try:
                    await display_task
                except asyncio.CancelledError:
                    pass

                stats["successful"] = progress.successful
                stats["failed"] = progress.failed
                stats["total"] = progress.processed
                stats["failure_breakdown"] = progress.get_failure_breakdown()
                progress.display()
                print()

                # Check for consecutive failures
                current_successful = stats["successful"]
                current_failed = stats["failed"]
                
                if current_successful > last_successful_count:
                    # We had at least one success in this batch, reset counter
                    consecutive_failures = 0
                    last_successful_count = current_successful
                    last_failed_count = current_failed
                else:
                    # No new successes in this batch, all were failures
                    batch_failures = current_failed - last_failed_count
                    consecutive_failures += batch_failures
                    last_failed_count = current_failed
                    
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.warning(f"\n{'='*70}\n⚠️  STOPPING WORKFLOW: {consecutive_failures} consecutive failures detected (threshold: {MAX_CONSECUTIVE_FAILURES})\n{'='*70}")
                        print(f"\n⚠️  Workflow stopped due to {consecutive_failures} consecutive failures")
                        break

            return stats
        finally:
            await self.webhook_mgr.stop()

    async def _display_loop(self, progress):
        try:
            while True:
                await asyncio.sleep(3.0)
                progress.display()
        except asyncio.CancelledError:
            pass


def validate_config():
    required = {"SERPER_API_KEY": SERPER_API_KEY, "OXYLABS_USERNAME": OXYLABS_USERNAME, "OXYLABS_PASSWORD": OXYLABS_PASSWORD, "POSTGRES_HOST": POSTGRES_CONFIG.get("host"), "POSTGRES_DB": POSTGRES_CONFIG.get("dbname"), "POSTGRES_USER": POSTGRES_CONFIG.get("user"), "POSTGRES_PASSWORD": POSTGRES_CONFIG.get("password")}
    if not (GROK_API_KEY or GROK_API_KEY_1 or GROK_API_KEY_2):
        required["GROK_API_KEY"] = None
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(f"✗ Missing: {', '.join(missing)}")
        return False
    logger.info("✓ Config valid")
    return True


async def async_main(args):
    db, serper, oxylabs = None, None, None
    try:
        logger.info("Initializing...")
        db = AsyncDatabaseManager(POSTGRES_CONFIG, 10, 50)
        await db.connect()
        serper = AsyncSerperClient(SERPER_API_KEY)
        oxylabs = AsyncOxylabsClient(OXYLABS_USERNAME, OXYLABS_PASSWORD)
        grok = AsyncGrokAIClient()
        logger.info("✓ Ready\n")

        executor = AsyncWorkflowExecutor(db, serper, oxylabs, grok, args.workers)
        logger.info(f"Processing {args.limit} agents @ {args.workers} workers\n")

        results = await executor.run(args.limit)

        logger.info(f"\n{'='*60}\nSUMMARY\n{'='*60}")
        logger.info(f"✓ Success: {results['successful']} | ✗ Failed: {results['failed']} | Total: {results['total']}")
        if results['total'] > 0:
            logger.info(f"Success Rate: {results['successful']/results['total']*100:.1f}%")
        logger.info(f"Serper API calls: {serper.get_call_count()}")

        if results['failed'] > 0 and results.get('failure_breakdown'):
            logger.info(f"\n{'='*60}\nFAILURE BREAKDOWN ({results['failed']} failures)\n{'='*60}")
            for line in results['failure_breakdown'].split('\n'):
                logger.info(line)

        return 0
    except Exception as e:
        logger.error(f"✗ Fatal: {e}", exc_info=True)
        return 1
    finally:
        if serper:
            await serper.close()
        if oxylabs:
            await oxylabs.close()
        if db:
            await db.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Team Size Estimator (Async)")
    parser.add_argument("--limit", type=int, default=DEFAULT_FETCH_LIMIT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Starting (Async Mode)")
    if not validate_config():
        sys.exit(1)

    sys.exit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
