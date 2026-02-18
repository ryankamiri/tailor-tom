"""Configuration management for TailorTom.

Uses Pydantic Settings to load configuration from environment variables.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from typing import Optional

# Resolve backend directory (parent of tailor_tom/) so .env is loaded from backend/
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.exists() else ".env",
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
    
    # LaTeX Compilation Settings
    compile_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout in seconds for LaTeX compilation (xelatex/lualatex/pdflatex)",
    )

    # Database
    database_url: str = Field(
        default=None,
        description="PostgreSQL URL (e.g., postgresql://user:pass@localhost:5432/dbname). Used when DB is enabled.",
    )

    # Redis Configuration
    redis_url: str = Field(
        ...,
        description="Redis URL for Celery broker and result backend (e.g., redis://localhost:6379/0)",
    )

    # Celery Configuration
    celery_task_time_limit: int = Field(
        default=900,
        ge=60,
        le=3600,
        description="Maximum time in seconds for a Celery task to complete (15 minutes default)",
    )

    celery_worker_concurrency: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Number of concurrent Celery worker processes",
    )

    worker_max_tasks_per_child: int = Field(
        default=25,
        ge=1,
        le=500,
        description="Max tasks per worker child before restart (memory hardening).",
    )

    celery_queue_name: str = Field(
        default="default",
        description="Celery queue name for task routing. Use 'local' for local development, 'hosted' for production.",
    )
    discord_webhook_url: Optional[str] = Field(
        default=None,
        description="Discord webhook URL for Celery task failure notifications. If unset, no Discord notifications are sent.",
    )

    # Target Pages (Deprecated: Now configured via frontend settings UI)
    target_pages: int = Field(
        default=1,
        ge=1,
        le=3,
        description="[Deprecated] Target number of pages - now configured via frontend settings",
    )

    # Google OAuth
    google_client_id: str = Field(
        default="",
        description="Google OAuth client ID (from Google Cloud Console)",
    )
    google_client_secret: str = Field(
        default="",
        description="Google OAuth client secret",
    )
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Frontend URL for OAuth redirect (e.g., https://www.tailortom.org)",
    )

    # Optimizer (economy mode; token budget = max_tokens above)
    economy_top_k: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Economy mode: top-K bullets to consider for rewrite.",
    )
    candidates_per_bullet: int = Field(
        default=2,
        ge=1,
        le=6,
        description="Number of candidates the LLM generates per bullet per pass (cap).",
    )
    min_score_delta_to_accept: Optional[float] = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Minimum ATS score delta to accept (0 = accept any non-regression).",
    )
    optimizer_max_char_growth: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Max allowed character growth per rewritten bullet before line-count verification (V2 prefilter guard).",
    )
    optimizer_max_word_growth: int = Field(
        default=0,
        ge=0,
        le=20,
        description="Max allowed word growth per rewritten bullet (V3 pass-1 guard).",
    )
    optimizer_max_shrink_words: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Max words allowed to be removed per bullet (V3 pass-1 shrink limit).",
    )
    optimizer_max_shrink_percent: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Max character shrink fraction per bullet (V3 pass-1 shrink limit).",
    )
    optimizer_mapping_min_similarity: float = Field(
        default=0.74,
        ge=0.0,
        le=1.0,
        description="V3 mapping: minimum normalized similarity (original_text vs latex_source) to keep a bullet. Below = drop and continue.",
    )

    # Optimizer V2 debug observability (all DEBUG lines prefixed with 'DEBUG ')
    optimizer_debug_enabled: bool = Field(
        default=False,
        description="Enable optimizer debug logging. When false, no DEBUG lines are emitted.",
    )
    optimizer_debug_raw_text: bool = Field(
        default=False,
        description="When true (and debug enabled), log raw LLM output text (truncated by optimizer_debug_max_text_chars).",
    )
    optimizer_debug_max_text_chars: int = Field(
        default=12000,
        ge=100,
        le=100000,
        description="Max characters for debug raw text truncation.",
    )
    optimizer_debug_emit_candidate_payload: bool = Field(
        default=True,
        description="Emit candidate payload in debug logs (set false in production to reduce volume).",
    )
    optimizer_debug_emit_pass_snapshots: bool = Field(
        default=True,
        description="Emit pass-level snapshots in debug logs.",
    )
    use_chooser_path: bool = Field(
        default=True,
        description="Use global one-pass bundle chooser. When False, use legacy pass-loop optimizer.",
    )

    # JWT
    jwt_secret: str = Field(
        default="dev-jwt-secret-change-in-production",
        description="Secret key for signing JWT access tokens (use a long random string in production)",
    )
    jwt_access_expiration_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Access token lifetime in minutes (default: 60)",
    )
    jwt_refresh_expiration_days: int = Field(
        default=30,
        ge=1,
        le=90,
        description="Refresh token lifetime in days (default: 30)",
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
