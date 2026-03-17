"""
Load/Stress tests for the async enrichment system.

Tests how many concurrent requests the system can handle.
"""

import asyncio
import statistics
import time
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch
import sys

# Mock xai_sdk before imports
mock_xai = MagicMock()
mock_xai.Client = MagicMock
sys.modules["xai_sdk"] = mock_xai
sys.modules["xai_sdk.chat"] = mock_xai.chat


def generate_test_requests(count: int) -> List[Dict[str, Any]]:
    """Generate test enrichment requests."""
    return [
        {
            "agent_id": f"load-test-agent-{i}",
            "full_name": f"Test Agent {i}",
            "organization_names": [f"Test Realty {i}"],
            "email": [f"agent{i}@test.com"],
        }
        for i in range(count)
    ]


class LoadTestResults:
    """Track load test results."""

    def __init__(self):
        self.total_requests = 0
        self.successful = 0
        self.failed = 0
        self.response_times: List[float] = []
        self.errors: List[str] = []
        self.start_time = 0
        self.end_time = 0

    def record_success(self, response_time: float):
        self.successful += 1
        self.response_times.append(response_time)

    def record_failure(self, error: str):
        self.failed += 1
        self.errors.append(error)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def requests_per_second(self) -> float:
        if self.duration == 0:
            return 0
        return self.total_requests / self.duration

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0
        return (self.successful / self.total_requests) * 100

    @property
    def avg_response_time(self) -> float:
        if not self.response_times:
            return 0
        return statistics.mean(self.response_times)

    @property
    def p50_response_time(self) -> float:
        if not self.response_times:
            return 0
        return statistics.median(self.response_times)

    @property
    def p95_response_time(self) -> float:
        if len(self.response_times) < 2:
            return self.avg_response_time
        sorted_times = sorted(self.response_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[idx]

    @property
    def p99_response_time(self) -> float:
        if len(self.response_times) < 2:
            return self.avg_response_time
        sorted_times = sorted(self.response_times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[idx]

    def print_summary(self):
        print("\n" + "=" * 60)
        print("LOAD TEST RESULTS")
        print("=" * 60)
        print(f"Total Requests:     {self.total_requests}")
        print(f"Successful:         {self.successful}")
        print(f"Failed:             {self.failed}")
        print(f"Success Rate:       {self.success_rate:.2f}%")
        print(f"Duration:           {self.duration:.2f}s")
        print(f"Requests/Second:    {self.requests_per_second:.2f}")
        print("-" * 60)
        print(f"Avg Response Time:  {self.avg_response_time * 1000:.2f}ms")
        print(f"P50 Response Time:  {self.p50_response_time * 1000:.2f}ms")
        print(f"P95 Response Time:  {self.p95_response_time * 1000:.2f}ms")
        print(f"P99 Response Time:  {self.p99_response_time * 1000:.2f}ms")
        print("=" * 60)
        if self.errors:
            print(f"\nFirst 5 errors:")
            for err in self.errors[:5]:
                print(f"  - {err}")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_redis():
    """Mock Redis client for load tests."""
    mock = AsyncMock()
    mock.health_check = AsyncMock(
        return_value={"status": "healthy", "connected": True}
    )
    mock.rate_limit_sliding_window = AsyncMock(
        return_value=(True, 1, 9999, 60)  # Always allow
    )
    mock.is_connected = True
    return mock


@pytest.fixture
def mock_enrichment_service():
    """Mock EnrichmentService that responds quickly."""
    from src.schemas.responses import EnrichmentResponse

    mock = AsyncMock()

    async def fast_enrich(request):
        # Simulate minimal processing time
        await asyncio.sleep(0.001)  # 1ms
        return EnrichmentResponse(
            status="success",
            agent_id=request.agent_id,
            team_size_count=5,
            team_size_category="Small",
            team_members=[],
            confidence="HIGH",
            reasoning="Load test response",
            processing_time_ms=1,
        )

    mock.enrich = fast_enrich
    mock.close = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def load_test_client(mock_redis, mock_enrichment_service):
    """Create test client optimized for load testing."""
    from src.api.dependencies import get_enrichment_service, get_redis
    from src.core.redis import RedisClient

    with patch("src.config.settings.settings.rate_limit_enabled", False):
        with patch.object(RedisClient, "get_instance", return_value=mock_redis):
            from src.main import create_app

            app = create_app()
            app.dependency_overrides[get_redis] = lambda: mock_redis
            app.dependency_overrides[get_enrichment_service] = (
                lambda: mock_enrichment_service
            )

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                timeout=30.0,
            ) as client:
                yield client

            app.dependency_overrides.clear()


# =============================================================================
# Load Tests - Sync Endpoint
# =============================================================================


class TestSyncEndpointLoad:
    """Load tests for POST /api/v1/enrich (sync)."""

    @pytest.mark.asyncio
    async def test_100_sequential_requests(self, load_test_client: AsyncClient):
        """Test 100 sequential requests."""
        results = LoadTestResults()
        results.total_requests = 100
        requests = generate_test_requests(100)

        results.start_time = time.time()

        for req in requests:
            start = time.time()
            try:
                response = await load_test_client.post("/api/v1/enrich", json=req)
                elapsed = time.time() - start

                if response.status_code == 200:
                    results.record_success(elapsed)
                else:
                    results.record_failure(f"Status {response.status_code}")
            except Exception as e:
                results.record_failure(str(e))

        results.end_time = time.time()
        results.print_summary()

        assert results.success_rate >= 95, f"Success rate too low: {results.success_rate}%"

    @pytest.mark.asyncio
    async def test_100_concurrent_requests(self, load_test_client: AsyncClient):
        """Test 100 concurrent requests."""
        results = LoadTestResults()
        results.total_requests = 100
        requests = generate_test_requests(100)

        async def make_request(req: Dict[str, Any]):
            start = time.time()
            try:
                response = await load_test_client.post("/api/v1/enrich", json=req)
                elapsed = time.time() - start
                return ("success" if response.status_code == 200 else "fail", elapsed)
            except Exception as e:
                return ("error", str(e))

        results.start_time = time.time()

        # Run all requests concurrently
        tasks = [make_request(req) for req in requests]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        results.end_time = time.time()

        for resp in responses:
            if isinstance(resp, Exception):
                results.record_failure(str(resp))
            elif resp[0] == "success":
                results.record_success(resp[1])
            else:
                results.record_failure(str(resp))

        results.print_summary()

        assert results.success_rate >= 90, f"Success rate too low: {results.success_rate}%"
        print(f"\n✅ Handled {results.requests_per_second:.0f} req/sec concurrently")

    @pytest.mark.asyncio
    async def test_500_concurrent_requests(self, load_test_client: AsyncClient):
        """Test 500 concurrent requests - stress test."""
        results = LoadTestResults()
        results.total_requests = 500
        requests = generate_test_requests(500)

        async def make_request(req: Dict[str, Any]):
            start = time.time()
            try:
                response = await load_test_client.post("/api/v1/enrich", json=req)
                elapsed = time.time() - start
                return ("success" if response.status_code == 200 else "fail", elapsed)
            except Exception as e:
                return ("error", str(e))

        results.start_time = time.time()

        # Run in batches to avoid overwhelming
        batch_size = 100
        for i in range(0, len(requests), batch_size):
            batch = requests[i : i + batch_size]
            tasks = [make_request(req) for req in batch]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for resp in responses:
                if isinstance(resp, Exception):
                    results.record_failure(str(resp))
                elif resp[0] == "success":
                    results.record_success(resp[1])
                else:
                    results.record_failure(str(resp))

        results.end_time = time.time()
        results.print_summary()

        assert results.success_rate >= 85, f"Success rate too low: {results.success_rate}%"
        print(f"\n✅ Handled {results.requests_per_second:.0f} req/sec with 500 requests")

    @pytest.mark.asyncio
    async def test_1000_concurrent_requests(self, load_test_client: AsyncClient):
        """Test 1000 concurrent requests - heavy stress test."""
        results = LoadTestResults()
        results.total_requests = 1000
        requests = generate_test_requests(1000)

        async def make_request(req: Dict[str, Any]):
            start = time.time()
            try:
                response = await load_test_client.post("/api/v1/enrich", json=req)
                elapsed = time.time() - start
                return ("success" if response.status_code == 200 else "fail", elapsed)
            except Exception as e:
                return ("error", str(e))

        results.start_time = time.time()

        # Run in batches
        batch_size = 100
        for i in range(0, len(requests), batch_size):
            batch = requests[i : i + batch_size]
            tasks = [make_request(req) for req in batch]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for resp in responses:
                if isinstance(resp, Exception):
                    results.record_failure(str(resp))
                elif resp[0] == "success":
                    results.record_success(resp[1])
                else:
                    results.record_failure(str(resp))

        results.end_time = time.time()
        results.print_summary()

        assert results.success_rate >= 80, f"Success rate too low: {results.success_rate}%"
        print(f"\n✅ Handled {results.requests_per_second:.0f} req/sec with 1000 requests")


# =============================================================================
# Load Tests - Async Endpoint (Task Queue)
# =============================================================================


class TestAsyncEndpointLoad:
    """Load tests for POST /api/v1/enrich/async."""

    @pytest.mark.asyncio
    async def test_1000_async_task_submissions(self, load_test_client: AsyncClient):
        """Test submitting 1000 tasks to async queue."""
        results = LoadTestResults()
        results.total_requests = 1000
        requests = generate_test_requests(1000)

        async def submit_task(req: Dict[str, Any]):
            start = time.time()
            try:
                response = await load_test_client.post(
                    "/api/v1/enrich/async", json=req
                )
                elapsed = time.time() - start
                # 400 is expected because async is disabled by default
                # but we're testing the endpoint can handle the load
                return (
                    "success" if response.status_code in [200, 400] else "fail",
                    elapsed,
                )
            except Exception as e:
                return ("error", str(e))

        results.start_time = time.time()

        # Run in batches
        batch_size = 200
        for i in range(0, len(requests), batch_size):
            batch = requests[i : i + batch_size]
            tasks = [submit_task(req) for req in batch]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for resp in responses:
                if isinstance(resp, Exception):
                    results.record_failure(str(resp))
                elif resp[0] == "success":
                    results.record_success(resp[1])
                else:
                    results.record_failure(str(resp))

        results.end_time = time.time()
        results.print_summary()

        assert results.success_rate >= 95, f"Success rate too low: {results.success_rate}%"
        print(f"\n✅ Async endpoint handled {results.requests_per_second:.0f} submissions/sec")


# =============================================================================
# Load Tests - Health Endpoint (Lightweight)
# =============================================================================


class TestHealthEndpointLoad:
    """Load tests for health endpoints - should be very fast."""

    @pytest.mark.asyncio
    async def test_5000_health_checks(self, load_test_client: AsyncClient):
        """Test 5000 health check requests."""
        results = LoadTestResults()
        results.total_requests = 5000

        async def health_check():
            start = time.time()
            try:
                response = await load_test_client.get("/health")
                elapsed = time.time() - start
                return ("success" if response.status_code == 200 else "fail", elapsed)
            except Exception as e:
                return ("error", str(e))

        results.start_time = time.time()

        # Run in large batches - health should be fast
        batch_size = 500
        for _ in range(results.total_requests // batch_size):
            tasks = [health_check() for _ in range(batch_size)]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for resp in responses:
                if isinstance(resp, Exception):
                    results.record_failure(str(resp))
                elif resp[0] == "success":
                    results.record_success(resp[1])
                else:
                    results.record_failure(str(resp))

        results.end_time = time.time()
        results.print_summary()

        assert results.success_rate >= 99, f"Health endpoint should be reliable"
        assert results.avg_response_time < 0.1, "Health should respond in < 100ms"
        print(f"\n✅ Health endpoint: {results.requests_per_second:.0f} req/sec")


# =============================================================================
# Load Tests - Rate Limiter
# =============================================================================


class TestRateLimiterLoad:
    """Test rate limiter under load."""

    @pytest.mark.asyncio
    async def test_rate_limiter_under_load(self, mock_redis, mock_enrichment_service):
        """Test rate limiter correctly limits under heavy load."""
        from src.api.dependencies import get_enrichment_service, get_redis
        from src.core.redis import RedisClient

        # Configure rate limit to allow only 50 requests per window
        call_count = 0

        async def rate_limit_mock(key, max_requests, window_seconds):
            nonlocal call_count
            call_count += 1
            # Allow first 50, then reject
            if call_count <= 50:
                return (True, call_count, 50 - call_count, 60)
            else:
                return (False, call_count, 0, 60)

        mock_redis.rate_limit_sliding_window = rate_limit_mock

        with patch("src.config.settings.settings.rate_limit_enabled", True):
            with patch.object(RedisClient, "get_instance", return_value=mock_redis):
                from src.main import create_app

                app = create_app()
                app.dependency_overrides[get_redis] = lambda: mock_redis
                app.dependency_overrides[get_enrichment_service] = (
                    lambda: mock_enrichment_service
                )

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    results = {"allowed": 0, "rejected": 0}

                    requests = generate_test_requests(100)

                    for req in requests:
                        response = await client.post("/api/v1/enrich", json=req)
                        if response.status_code == 200:
                            results["allowed"] += 1
                        elif response.status_code == 429:
                            results["rejected"] += 1

                    print(f"\nRate Limiter Results:")
                    print(f"  Allowed:  {results['allowed']}")
                    print(f"  Rejected: {results['rejected']}")

                    # Should have allowed ~50 and rejected ~50
                    assert results["allowed"] >= 45, "Should allow ~50 requests"
                    assert results["rejected"] >= 45, "Should reject ~50 requests"

                app.dependency_overrides.clear()


# =============================================================================
# Throughput Benchmark
# =============================================================================


class TestThroughputBenchmark:
    """Benchmark maximum throughput."""

    @pytest.mark.asyncio
    async def test_max_throughput_benchmark(self, load_test_client: AsyncClient):
        """
        Benchmark to find maximum sustainable throughput.

        Runs increasing loads until failure rate exceeds 5%.
        """
        print("\n" + "=" * 60)
        print("THROUGHPUT BENCHMARK")
        print("=" * 60)

        best_throughput = 0
        best_concurrency = 0

        for concurrency in [50, 100, 200, 300, 500]:
            results = LoadTestResults()
            results.total_requests = concurrency
            requests = generate_test_requests(concurrency)

            async def make_request(req):
                start = time.time()
                try:
                    response = await load_test_client.post("/api/v1/enrich", json=req)
                    elapsed = time.time() - start
                    return ("success" if response.status_code == 200 else "fail", elapsed)
                except Exception as e:
                    return ("error", str(e))

            results.start_time = time.time()
            tasks = [make_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            results.end_time = time.time()

            for resp in responses:
                if isinstance(resp, Exception):
                    results.record_failure(str(resp))
                elif resp[0] == "success":
                    results.record_success(resp[1])
                else:
                    results.record_failure(str(resp))

            print(
                f"Concurrency {concurrency:4d}: "
                f"{results.requests_per_second:6.0f} req/s, "
                f"{results.success_rate:5.1f}% success, "
                f"avg {results.avg_response_time * 1000:6.1f}ms"
            )

            if results.success_rate >= 95 and results.requests_per_second > best_throughput:
                best_throughput = results.requests_per_second
                best_concurrency = concurrency

            # Stop if failure rate too high
            if results.success_rate < 80:
                print(f"  ⚠️ Stopping - failure rate too high")
                break

        print("-" * 60)
        print(f"Best throughput: {best_throughput:.0f} req/s at concurrency {best_concurrency}")
        print("=" * 60)

        assert best_throughput > 100, "Should achieve at least 100 req/s"
