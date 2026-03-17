"""
Redis client wrapper for connection pooling and distributed operations.

Provides async Redis operations with connection pooling for high throughput.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from src.config.settings import settings
from src.core.logging import get_logger

logger = get_logger("redis-client")


class RedisClient:
    """
    Async Redis client with connection pooling.

    Features:
    - Connection pooling for high concurrency
    - Automatic reconnection on failures
    - Health checking
    - Distributed rate limiting support

    Usage:
        client = RedisClient()
        await client.connect()
        value = await client.get("key")
        await client.close()
    """

    _instance: Optional["RedisClient"] = None
    _lock = asyncio.Lock()

    def __init__(
        self,
        url: Optional[str] = None,
        max_connections: Optional[int] = None,
        socket_timeout: Optional[float] = None,
        retry_on_timeout: Optional[bool] = None,
    ):
        """
        Initialize Redis client.

        Args:
            url: Redis connection URL (defaults to settings)
            max_connections: Max connections in pool (defaults to settings)
            socket_timeout: Socket timeout in seconds (defaults to settings)
            retry_on_timeout: Whether to retry on timeout (defaults to settings)
        """
        self.url = url or settings.redis_url
        self.max_connections = max_connections or settings.redis_max_connections
        self.socket_timeout = socket_timeout or settings.redis_socket_timeout
        self.retry_on_timeout = (
            retry_on_timeout
            if retry_on_timeout is not None
            else settings.redis_retry_on_timeout
        )

        self._pool: Optional[ConnectionPool] = None
        self._redis: Optional[Redis] = None
        self._connected = False

    @classmethod
    async def get_instance(cls) -> "RedisClient":
        """Get or create singleton instance."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance.connect()
        return cls._instance

    @classmethod
    async def close_instance(cls) -> None:
        """Close singleton instance."""
        if cls._instance is not None:
            async with cls._lock:
                if cls._instance is not None:
                    await cls._instance.close()
                    cls._instance = None

    async def connect(self) -> None:
        """Establish connection pool to Redis."""
        if self._connected:
            return

        try:
            self._pool = ConnectionPool.from_url(
                self.url,
                max_connections=self.max_connections,
                socket_timeout=self.socket_timeout,
                retry_on_timeout=self.retry_on_timeout,
                decode_responses=True,
            )
            self._redis = Redis(connection_pool=self._pool)

            # Test connection
            await self._redis.ping()
            self._connected = True

            logger.info(
                "Redis connected",
                url=self._mask_url(self.url),
                max_connections=self.max_connections,
            )

        except RedisError as e:
            logger.error("Failed to connect to Redis", error=str(e))
            raise

    async def close(self) -> None:
        """Close connection pool."""
        if self._redis:
            await self._redis.close()
            self._redis = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        self._connected = False
        logger.info("Redis connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    def _mask_url(self, url: str) -> str:
        """Mask password in URL for logging."""
        if "@" in url:
            parts = url.split("@")
            return f"redis://***@{parts[-1]}"
        return url

    async def _ensure_connected(self) -> Redis:
        """Ensure connection is established and return Redis client."""
        if not self._connected or self._redis is None:
            await self.connect()
        return self._redis

    # ==========================================================================
    # Basic operations
    # ==========================================================================

    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        redis = await self._ensure_connected()
        return await redis.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """
        Set key-value pair.

        Args:
            key: Key name
            value: Value to set
            ex: Expire time in seconds
            px: Expire time in milliseconds
            nx: Only set if key doesn't exist
            xx: Only set if key exists

        Returns:
            True if set was successful
        """
        redis = await self._ensure_connected()
        result = await redis.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
        return result is not None

    async def delete(self, *keys: str) -> int:
        """Delete keys. Returns number of keys deleted."""
        redis = await self._ensure_connected()
        return await redis.delete(*keys)

    async def exists(self, *keys: str) -> int:
        """Check if keys exist. Returns count of existing keys."""
        redis = await self._ensure_connected()
        return await redis.exists(*keys)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiry on key. Returns True if successful."""
        redis = await self._ensure_connected()
        return await redis.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """Get time-to-live for key in seconds. Returns -2 if key doesn't exist, -1 if no expiry."""
        redis = await self._ensure_connected()
        return await redis.ttl(key)

    # ==========================================================================
    # Counter operations (for rate limiting)
    # ==========================================================================

    async def incr(self, key: str) -> int:
        """Increment key value by 1. Returns new value."""
        redis = await self._ensure_connected()
        return await redis.incr(key)

    async def incrby(self, key: str, amount: int) -> int:
        """Increment key value by amount. Returns new value."""
        redis = await self._ensure_connected()
        return await redis.incrby(key, amount)

    async def decr(self, key: str) -> int:
        """Decrement key value by 1. Returns new value."""
        redis = await self._ensure_connected()
        return await redis.decr(key)

    # ==========================================================================
    # Rate limiting operations
    # ==========================================================================

    async def rate_limit_check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """
        Check and update rate limit using sliding window.

        Args:
            key: Rate limit key (e.g., "ratelimit:ip:192.168.1.1")
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, current_count, remaining_requests)
        """
        redis = await self._ensure_connected()

        # Use atomic operations with pipeline
        pipe = redis.pipeline()

        # Increment counter
        pipe.incr(key)
        # Set expiry if key is new (only sets if no expiry exists)
        pipe.expire(key, window_seconds)
        # Get current TTL
        pipe.ttl(key)

        results = await pipe.execute()
        current_count = results[0]
        ttl = results[2]

        # If TTL is -1 (no expiry), set it
        if ttl == -1:
            await redis.expire(key, window_seconds)

        allowed = current_count <= max_requests
        remaining = max(0, max_requests - current_count)

        return allowed, current_count, remaining

    async def rate_limit_sliding_window(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int, int, int]:
        """
        Sliding window rate limit with more accurate counting.

        Args:
            key: Rate limit key
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, current_count, remaining, reset_seconds)
        """
        import time

        redis = await self._ensure_connected()
        now = time.time()
        window_start = now - window_seconds

        # Use sorted set with timestamp as score
        sorted_set_key = f"{key}:sw"

        pipe = redis.pipeline()

        # Remove entries outside window
        pipe.zremrangebyscore(sorted_set_key, 0, window_start)
        # Add current request
        pipe.zadd(sorted_set_key, {str(now): now})
        # Count requests in window
        pipe.zcard(sorted_set_key)
        # Set expiry on the set
        pipe.expire(sorted_set_key, window_seconds + 1)

        results = await pipe.execute()
        current_count = results[2]

        allowed = current_count <= max_requests
        remaining = max(0, max_requests - current_count)

        # Calculate reset time (when oldest entry expires)
        oldest = await redis.zrange(sorted_set_key, 0, 0, withscores=True)
        if oldest:
            reset_seconds = int(oldest[0][1] + window_seconds - now)
        else:
            reset_seconds = window_seconds

        return allowed, current_count, remaining, max(0, reset_seconds)

    # ==========================================================================
    # Health check
    # ==========================================================================

    async def health_check(self) -> dict[str, Any]:
        """
        Perform health check on Redis connection.

        Returns:
            Dictionary with health status and metrics
        """
        try:
            redis = await self._ensure_connected()

            # Ping test
            start = asyncio.get_event_loop().time()
            await redis.ping()
            latency = (asyncio.get_event_loop().time() - start) * 1000

            # Get info
            info = await redis.info("server", "clients", "memory")

            return {
                "status": "healthy",
                "connected": True,
                "latency_ms": round(latency, 2),
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
            }

        except RedisError as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }


# ==========================================================================
# Module-level helper functions
# ==========================================================================


async def get_redis() -> RedisClient:
    """Get Redis client instance (for dependency injection)."""
    return await RedisClient.get_instance()


@asynccontextmanager
async def redis_connection() -> AsyncGenerator[RedisClient, None]:
    """Context manager for Redis connection."""
    client = await RedisClient.get_instance()
    try:
        yield client
    finally:
        pass  # Don't close singleton instance


async def close_redis() -> None:
    """Close Redis connection (for app shutdown)."""
    await RedisClient.close_instance()
