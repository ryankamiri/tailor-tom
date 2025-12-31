"""Configuration management for TailorTom.

Uses Pydantic Settings to load configuration from environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # OpenAI Configuration
    openai_api_key: str = Field(
        ...,
        description="OpenAI API key for GPT-5 access",
    )

    # Model Configuration
    model_name: str = Field(
        default="openai/gpt-5-mini",
        description="DSPy model identifier (e.g., openai/gpt-5-mini, openai/gpt-5)",
    )

    # LLM Generation Parameters
    # Note: GPT-5 models require temperature=1.0 and max_tokens>=16000
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1000,
        le=32000,
        description="Maximum tokens for LLM responses. None uses model default. GPT-5 requires >=16000.",
    )

    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM generation. None uses model default. GPT-5 requires 1.0.",
    )

    # Optimization Settings (Deprecated: These are now configured via frontend settings UI)
    # Kept for backwards compatibility but not used - values come from API requests
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="[Deprecated] Maximum iterations - now configured via frontend settings",
    )
    
    max_bullet_lines: int = Field(
        default=2,
        ge=1,
        le=5,
        description="[Deprecated] Maximum lines per bullet point - now configured via frontend settings",
    )

    # LaTeX Compilation Settings
    compile_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout in seconds for pdflatex compilation",
    )

    # Redis Configuration
    redis_url: str = Field(
        ...,
        description="Redis URL for Celery broker and result backend (e.g., redis://localhost:6379/0)",
    )

    redis_ttl_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Number of days to keep completed jobs in Redis before expiration",
    )

    # Celery Configuration
    celery_task_time_limit: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Maximum time in seconds for a Celery task to complete (10 minutes default)",
    )

    celery_worker_concurrency: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of concurrent Celery worker processes",
    )

    celery_queue_name: str = Field(
        default="default",
        description="Celery queue name for task routing. Use 'local' for local development, 'hosted' for production.",
    )

    # Target Pages (Deprecated: Now configured via frontend settings UI)
    target_pages: int = Field(
        default=1,
        ge=1,
        le=3,
        description="[Deprecated] Target number of pages - now configured via frontend settings",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.
    
    Returns:
        Settings: Application settings loaded from environment.
    """
    return Settings()


# Global settings instance for convenience
settings = get_settings()

