"""
Application settings using Pydantic Settings for environment variable validation.
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Main application settings.

    All settings are loaded from environment variables.
    Nested prefixes: SERPER_, OXYLABS_, GROK_, RATE_LIMIT_
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ==========================================================================
    # Server settings
    # ==========================================================================
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=4, description="Number of worker processes")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # Request settings
    request_timeout: int = Field(default=300, description="Total request timeout in seconds")

    # ==========================================================================
    # Serper API settings (prefix: SERPER_)
    # ==========================================================================
    serper_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Serper API key",
        alias="SERPER_API_KEY",
    )
    serper_timeout: int = Field(
        default=30,
        description="Serper request timeout",
        alias="SERPER_TIMEOUT",
    )
    serper_max_retries: int = Field(
        default=3,
        description="Serper max retries",
        alias="SERPER_MAX_RETRIES",
    )

    # ==========================================================================
    # Oxylabs API settings (prefix: OXYLABS_)
    # ==========================================================================
    oxylabs_username: Optional[str] = Field(
        default=None,
        description="Oxylabs username",
        alias="OXYLABS_USERNAME",
    )
    oxylabs_password: Optional[SecretStr] = Field(
        default=None,
        description="Oxylabs password",
        alias="OXYLABS_PASSWORD",
    )
    oxylabs_timeout: int = Field(
        default=90,
        description="Oxylabs request timeout",
        alias="OXYLABS_TIMEOUT",
    )
    oxylabs_max_retries: int = Field(
        default=3,
        description="Oxylabs max retries",
        alias="OXYLABS_MAX_RETRIES",
    )

    # ==========================================================================
    # Grok AI settings (prefix: GROK_)
    # ==========================================================================
    grok_api_key: Optional[SecretStr] = Field(
        default=None,
        description="Primary Grok API key",
        alias="GROK_API_KEY",
    )
    grok_api_key_1: Optional[SecretStr] = Field(
        default=None,
        description="First Grok API key for load balancing",
        alias="GROK_API_KEY_1",
    )
    grok_api_key_2: Optional[SecretStr] = Field(
        default=None,
        description="Second Grok API key for load balancing",
        alias="GROK_API_KEY_2",
    )
    grok_timeout: int = Field(
        default=120,
        description="Grok request timeout",
        alias="GROK_TIMEOUT",
    )
    grok_max_retries: int = Field(
        default=3,
        description="Grok max retries",
        alias="GROK_MAX_RETRIES",
    )
    grok_model_name: str = Field(
        default="grok-4-1-fast-non-reasoning",
        description="Grok model to use",
        alias="GROK_MODEL_NAME",
    )
    grok_rate_limit_per_account: float = Field(
        default=3.5,
        description="Requests per second per Grok account",
        alias="GROK_RATE_LIMIT_PER_ACCOUNT",
    )

    # ==========================================================================
    # Rate limiting settings (prefix: RATE_LIMIT_)
    # ==========================================================================
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting",
        alias="RATE_LIMIT_ENABLED",
    )
    rate_limit_requests: int = Field(
        default=100,
        description="Maximum requests per window",
        alias="RATE_LIMIT_REQUESTS",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        description="Rate limit time window in seconds",
        alias="RATE_LIMIT_WINDOW_SECONDS",
    )

    # ==========================================================================
    # Redis settings (prefix: REDIS_)
    # ==========================================================================
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
        alias="REDIS_URL",
    )
    redis_max_connections: int = Field(
        default=50,
        description="Maximum Redis connections in pool",
        alias="REDIS_MAX_CONNECTIONS",
    )
    redis_socket_timeout: float = Field(
        default=5.0,
        description="Redis socket timeout in seconds",
        alias="REDIS_SOCKET_TIMEOUT",
    )
    redis_retry_on_timeout: bool = Field(
        default=True,
        description="Retry Redis operations on timeout",
        alias="REDIS_RETRY_ON_TIMEOUT",
    )

    # ==========================================================================
    # Celery settings (prefix: CELERY_)
    # ==========================================================================
    celery_broker_url: Optional[str] = Field(
        default=None,
        description="Celery broker URL (defaults to REDIS_URL)",
        alias="CELERY_BROKER_URL",
    )
    celery_result_backend: Optional[str] = Field(
        default=None,
        description="Celery result backend URL (defaults to REDIS_URL)",
        alias="CELERY_RESULT_BACKEND",
    )
    celery_task_soft_time_limit: int = Field(
        default=240,
        description="Soft time limit for tasks in seconds",
        alias="CELERY_TASK_SOFT_TIME_LIMIT",
    )
    celery_task_time_limit: int = Field(
        default=300,
        description="Hard time limit for tasks in seconds",
        alias="CELERY_TASK_TIME_LIMIT",
    )
    celery_worker_concurrency: int = Field(
        default=8,
        description="Number of concurrent worker processes",
        alias="CELERY_WORKER_CONCURRENCY",
    )
    celery_worker_prefetch_multiplier: int = Field(
        default=4,
        description="Number of tasks to prefetch per worker",
        alias="CELERY_WORKER_PREFETCH_MULTIPLIER",
    )
    celery_task_acks_late: bool = Field(
        default=True,
        description="Acknowledge tasks after completion (safer)",
        alias="CELERY_TASK_ACKS_LATE",
    )
    celery_task_reject_on_worker_lost: bool = Field(
        default=True,
        description="Reject tasks if worker is lost",
        alias="CELERY_TASK_REJECT_ON_WORKER_LOST",
    )

    # ==========================================================================
    # Processing settings
    # ==========================================================================
    max_concurrent_requests: int = Field(
        default=100,
        description="Maximum concurrent enrichment requests",
        alias="MAX_CONCURRENT_REQUESTS",
    )
    async_processing_enabled: bool = Field(
        default=False,
        description="Enable async processing via Celery (for high throughput)",
        alias="ASYNC_PROCESSING_ENABLED",
    )

    # ==========================================================================
    # Content filtering settings
    # ==========================================================================
    blocked_domains: str = Field(
        default="linkedin.com,facebook.com,instagram.com,twitter.com,idxbroker.com,zillow.com,realtor.com",
        description="Comma-separated list of blocked domains",
    )
    min_html_bytes: int = Field(
        default=3500,
        description="Minimum HTML content size",
    )
    dead_content_snippets: str = Field(
        default="page not found,404 not found,coming soon,domain expired,site has been archived,under construction,loading please wait,this site is parked,IDX search,sign in to view this page",
        description="Comma-separated list of dead content indicators",
    )

    # ==========================================================================
    # Validators
    # ==========================================================================

    @field_validator(
        "grok_api_key", "grok_api_key_1", "grok_api_key_2",
        "serper_api_key", "oxylabs_password",
        mode="before"
    )
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None for optional SecretStr fields."""
        if v == "" or v is None:
            return None
        return v

    # ==========================================================================
    # Properties for convenient access
    # ==========================================================================

    @property
    def blocked_domains_set(self) -> set:
        """Get blocked domains as a set."""
        return {d.strip().lower() for d in self.blocked_domains.split(",") if d.strip()}

    @property
    def dead_content_snippets_list(self) -> List[str]:
        """Get dead content snippets as a list."""
        return [s.strip().lower() for s in self.dead_content_snippets.split(",") if s.strip()]

    def get_grok_api_keys(self) -> List[str]:
        """Get list of available Grok API keys."""
        keys = []
        if self.grok_api_key_1:
            keys.append(self.grok_api_key_1.get_secret_value())
        if self.grok_api_key_2:
            keys.append(self.grok_api_key_2.get_secret_value())
        if not keys and self.grok_api_key:
            keys.append(self.grok_api_key.get_secret_value())
        return keys

    def get_celery_broker_url(self) -> str:
        """Get Celery broker URL (defaults to Redis URL)."""
        return self.celery_broker_url or self.redis_url

    def get_celery_result_backend(self) -> str:
        """Get Celery result backend URL (defaults to Redis URL)."""
        return self.celery_result_backend or self.redis_url

    def validate_api_keys(self) -> dict:
        """
        Validate that required API keys are configured.

        Returns:
            Dictionary of missing keys with error messages.
            Empty dict means all required keys are present.
        """
        errors = {}

        if not self.serper_api_key:
            errors["SERPER_API_KEY"] = "Missing Serper API key"

        if not self.oxylabs_username:
            errors["OXYLABS_USERNAME"] = "Missing Oxylabs username"

        if not self.oxylabs_password:
            errors["OXYLABS_PASSWORD"] = "Missing Oxylabs password"

        if not self.get_grok_api_keys():
            errors["GROK_API_KEY"] = "Missing Grok API key (set GROK_API_KEY or GROK_API_KEY_1/GROK_API_KEY_2)"

        return errors

    def is_configured(self) -> bool:
        """Check if all required API keys are configured."""
        return len(self.validate_api_keys()) == 0


# ==========================================================================
# Nested settings classes for type hints and grouping (optional use)
# ==========================================================================

class SerperConfig:
    """Helper class for Serper-related settings."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def api_key(self) -> Optional[SecretStr]:
        return self._settings.serper_api_key

    @property
    def timeout(self) -> int:
        return self._settings.serper_timeout

    @property
    def max_retries(self) -> int:
        return self._settings.serper_max_retries


class OxylabsConfig:
    """Helper class for Oxylabs-related settings."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def username(self) -> Optional[str]:
        return self._settings.oxylabs_username

    @property
    def password(self) -> Optional[SecretStr]:
        return self._settings.oxylabs_password

    @property
    def timeout(self) -> int:
        return self._settings.oxylabs_timeout

    @property
    def max_retries(self) -> int:
        return self._settings.oxylabs_max_retries


class GrokConfig:
    """Helper class for Grok-related settings."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def api_key(self) -> Optional[SecretStr]:
        return self._settings.grok_api_key

    @property
    def api_key_1(self) -> Optional[SecretStr]:
        return self._settings.grok_api_key_1

    @property
    def api_key_2(self) -> Optional[SecretStr]:
        return self._settings.grok_api_key_2

    @property
    def timeout(self) -> int:
        return self._settings.grok_timeout

    @property
    def max_retries(self) -> int:
        return self._settings.grok_max_retries

    @property
    def model_name(self) -> str:
        return self._settings.grok_model_name

    @property
    def rate_limit_per_account(self) -> float:
        return self._settings.grok_rate_limit_per_account

    def get_api_keys(self) -> List[str]:
        return self._settings.get_grok_api_keys()


class RateLimitConfig:
    """Helper class for rate limit settings."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.rate_limit_enabled

    @property
    def requests(self) -> int:
        return self._settings.rate_limit_requests

    @property
    def window_seconds(self) -> int:
        return self._settings.rate_limit_window_seconds


class RedisConfig:
    """Helper class for Redis settings."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def url(self) -> str:
        return self._settings.redis_url

    @property
    def max_connections(self) -> int:
        return self._settings.redis_max_connections

    @property
    def socket_timeout(self) -> float:
        return self._settings.redis_socket_timeout

    @property
    def retry_on_timeout(self) -> bool:
        return self._settings.redis_retry_on_timeout


class CeleryConfig:
    """Helper class for Celery settings."""

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def broker_url(self) -> str:
        return self._settings.get_celery_broker_url()

    @property
    def result_backend(self) -> str:
        return self._settings.get_celery_result_backend()

    @property
    def task_soft_time_limit(self) -> int:
        return self._settings.celery_task_soft_time_limit

    @property
    def task_time_limit(self) -> int:
        return self._settings.celery_task_time_limit

    @property
    def worker_concurrency(self) -> int:
        return self._settings.celery_worker_concurrency

    @property
    def worker_prefetch_multiplier(self) -> int:
        return self._settings.celery_worker_prefetch_multiplier

    @property
    def task_acks_late(self) -> bool:
        return self._settings.celery_task_acks_late

    @property
    def task_reject_on_worker_lost(self) -> bool:
        return self._settings.celery_task_reject_on_worker_lost


# ==========================================================================
# Settings factory
# ==========================================================================

@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance (lazy loaded)
settings = get_settings()

# Helper accessors for grouped settings
serper_config = SerperConfig(settings)
oxylabs_config = OxylabsConfig(settings)
grok_config = GrokConfig(settings)
rate_limit_config = RateLimitConfig(settings)
redis_config = RedisConfig(settings)
celery_config = CeleryConfig(settings)
