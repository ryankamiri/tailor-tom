"""V3 optimizer result and internal data types."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TokenUsage:
    """Per-job LLM usage and cost."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    usage_source: str = "estimated"  # "actual" | "mixed" | "estimated"


@dataclass
class V3OptimizationResult:
    """Result of V3 optimize_resume_v3."""

    success: bool
    optimized_latex: Optional[str] = None
    error_message: Optional[str] = None
    pdf_bytes: Optional[bytes] = None
    page_count: int = 0
    passes_done: int = 0
    quality_passes: bool = False
    quality_issues_summary: str = ""
    token_usage: Optional[TokenUsage] = None
    diagnostics: Optional[dict[str, Any]] = None
