"""
Grok AI client for AI-powered analysis.

Uses the xAI SDK for interacting with Grok models.
Supports multiple API keys for load balancing and rate limiting.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from xai_sdk import Client
from xai_sdk.chat import user

from src.config.settings import settings
from src.core.exceptions import GrokAPIError, GrokCreditExhaustedError
from src.core.logging import get_logger

logger = get_logger("grok-client")


# Credit/quota related error keywords
CREDIT_ERROR_KEYWORDS = [
    "credit",
    "quota",
    "insufficient",
    "balance",
    "limit",
    "exceeded",
    "429",
    "402",
    "payment",
    "resource_exhausted",
]


def is_credit_error(error_message: str) -> bool:
    """Check if an error message indicates credit/quota exhaustion."""
    error_lower = error_message.lower()
    return any(keyword in error_lower for keyword in CREDIT_ERROR_KEYWORDS)


@dataclass
class GrokResponse:
    """Generic response from Grok AI."""

    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class GrokClient:
    """
    Async client for Grok AI API.

    Features:
    - Multiple API key support for load balancing
    - Per-account rate limiting
    - Automatic retry on transient failures
    - Credit exhaustion detection

    Usage:
        client = GrokClient()
        result = await client.analyze_with_schema(prompt, ResponseModel)
        await client.close()
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model_name: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        rate_limit_per_account: Optional[float] = None,
    ):
        """
        Initialize Grok client.

        Args:
            api_keys: List of API keys (defaults to settings)
            model_name: Grok model to use (defaults to settings)
            timeout: Request timeout in seconds (defaults to settings)
            max_retries: Maximum retry attempts (defaults to settings)
            rate_limit_per_account: Requests per second per account (defaults to settings)
        """
        # Get API keys from settings if not provided
        self.api_keys = api_keys or settings.get_grok_api_keys()
        if not self.api_keys:
            raise ValueError("No Grok API keys configured")

        self.model_name = model_name or settings.grok_model_name
        self.timeout = timeout or settings.grok_timeout
        self.max_retries = max_retries or settings.grok_max_retries
        self.rate_limit_per_account = (
            rate_limit_per_account or settings.grok_rate_limit_per_account
        )

        # Calculate minimum interval between requests per account
        self.min_interval = (
            1.0 / self.rate_limit_per_account if self.rate_limit_per_account > 0 else 0
        )

        # Initialize clients for each API key
        self.clients: List[Client] = []
        self.last_request_times: List[float] = []
        self.rate_locks: List[asyncio.Lock] = []

        for i, key in enumerate(self.api_keys):
            self.clients.append(Client(api_key=key, timeout=self.timeout))
            self.last_request_times.append(0.0)
            self.rate_locks.append(asyncio.Lock())
            logger.debug(f"Initialized Grok client {i + 1}")

        # Round-robin client selection
        self.current_index = 0
        self._selection_lock = asyncio.Lock()

        total_rate = self.rate_limit_per_account * len(self.clients)
        logger.info(
            "Grok client initialized",
            num_clients=len(self.clients),
            model=self.model_name,
            rate_limit_per_account=self.rate_limit_per_account,
            total_rate_limit=total_rate,
        )

    async def _get_client(self) -> tuple[Client, int]:
        """Get the next client in round-robin fashion."""
        async with self._selection_lock:
            idx = self.current_index
            client = self.clients[idx]
            self.current_index = (self.current_index + 1) % len(self.clients)
            return client, idx

    async def _apply_rate_limit(self, client_index: int) -> None:
        """Apply rate limiting for a specific client."""
        async with self.rate_locks[client_index]:
            now = time.time()
            elapsed = now - self.last_request_times[client_index]
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                await asyncio.sleep(sleep_time)
            self.last_request_times[client_index] = time.time()

    async def _execute_with_retry(
        self,
        operation_name: str,
        sync_func,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute a synchronous SDK function with retry logic.

        Args:
            operation_name: Name of the operation for logging
            sync_func: Synchronous function to execute
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Result from the function

        Raises:
            GrokAPIError: If all retries fail
            GrokCreditExhaustedError: If credits are exhausted
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            client, client_idx = await self._get_client()
            await self._apply_rate_limit(client_idx)

            try:
                # Run synchronous SDK call in thread pool
                result = await asyncio.to_thread(
                    sync_func, client, *args, **kwargs
                )
                return result

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # Check for credit/quota errors
                if is_credit_error(error_msg):
                    logger.error(
                        "Grok credit exhausted",
                        error=error_msg[:200],
                        attempt=attempt + 1,
                    )
                    # Wait longer on rate limit errors
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(5 + (2 ** attempt))
                    else:
                        raise GrokCreditExhaustedError(
                            message=f"Grok API credits exhausted: {error_msg[:100]}"
                        )

                logger.warning(
                    f"{operation_name} failed",
                    error=error_msg[:200],
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise GrokAPIError(
            message=f"{operation_name} failed after {self.max_retries} attempts: {str(last_error)[:100]}",
            details={"last_error": str(last_error)[:500]},
        )

    def _sync_chat_with_schema(
        self,
        client: Client,
        prompt: str,
        response_schema: type,
    ) -> Any:
        """
        Synchronous chat completion with structured response.

        Args:
            client: Grok client instance
            prompt: User prompt
            response_schema: Pydantic model for response validation

        Returns:
            Parsed response object
        """
        chat = client.chat.create(
            model=self.model_name,
            response_format=response_schema,
        )
        chat.append(user(prompt))
        response = chat.sample()

        if isinstance(response.content, str):
            return response_schema.model_validate_json(response.content)
        return response.content

    async def analyze_with_schema(
        self,
        prompt: str,
        response_schema: type,
        operation_name: str = "analyze",
    ) -> Any:
        """
        Perform AI analysis with a structured response schema.

        Args:
            prompt: The prompt to send to Grok
            response_schema: Pydantic model for response validation
            operation_name: Name for logging

        Returns:
            Parsed response matching the schema

        Raises:
            GrokAPIError: If analysis fails
        """
        return await self._execute_with_retry(
            operation_name,
            self._sync_chat_with_schema,
            prompt,
            response_schema,
        )

    async def close(self) -> None:
        """Close the client (no-op for SDK, but maintains interface consistency)."""
        logger.debug("Grok client closed")

    def get_status(self) -> Dict[str, Any]:
        """Get current client status."""
        return {
            "num_clients": len(self.clients),
            "model": self.model_name,
            "rate_limit_per_account": self.rate_limit_per_account,
            "total_rate_limit": self.rate_limit_per_account * len(self.clients),
        }
