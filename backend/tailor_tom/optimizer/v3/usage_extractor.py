"""V3 usage extraction and normalization: actual-first with estimate fallback.

Centralizes parsing of provider usage from DSPy result objects and char-based
estimation. Usage source is one of: actual, mixed, estimated.
"""

from typing import Any

from tailor_tom.optimizer.v3.types import TokenUsage

# Cost per token placeholder; can be refined with model-specific rates
_COST_PER_TOKEN = 0.00001
_CHARS_PER_TOKEN = 4

UsageSource = str  # "actual" | "mixed" | "estimated"


def _safe_int(val: Any, default: int = 0) -> int:
    """Coerce to non-negative int."""
    if val is None:
        return default
    try:
        n = int(val)
        return max(0, n)
    except (TypeError, ValueError):
        return default


def _get_usage_dict(obj: Any) -> dict[str, Any] | None:
    """Extract a usage-like dict from DSPy result (multiple possible shapes). Returns None if not found."""
    if obj is None:
        return None
    # Common: result.response_metadata or result.response_metadata.get("usage")
    meta = getattr(obj, "response_metadata", None)
    if isinstance(meta, dict):
        usage = meta.get("usage") or meta.get("token_usage")
        if isinstance(usage, dict):
            return usage
        # Flat keys on metadata
        if "prompt_tokens" in meta or "input_tokens" in meta:
            return meta
    # Direct: result.usage
    usage = getattr(obj, "usage", None)
    if isinstance(usage, dict):
        return usage
    # Nested: result.response.usage (some backends)
    resp = getattr(obj, "response", None)
    if hasattr(resp, "usage") and isinstance(getattr(resp, "usage"), dict):
        return resp.usage
    return None


def extract_actual_usage(result_obj: Any) -> TokenUsage | None:
    """Parse provider usage from DSPy result. Returns None when no trustworthy usage exists."""
    d = _get_usage_dict(result_obj)
    if not d:
        return None
    # Support both prompt_tokens and input_tokens
    pt = _safe_int(d.get("prompt_tokens") or d.get("input_tokens"))
    ct = _safe_int(d.get("completion_tokens") or d.get("output_tokens"))
    # Only treat as actual if we have both (or at least one non-zero and both look valid)
    if pt == 0 and ct == 0:
        return None
    cost = float(d.get("estimated_cost_usd") or d.get("total_cost") or 0.0)
    if cost <= 0:
        cost = (pt + ct) * _COST_PER_TOKEN
    return TokenUsage(
        prompt_tokens=pt,
        completion_tokens=ct,
        estimated_cost_usd=cost,
        usage_source="actual",
    )


def estimate_usage(prompt_chars: int, completion_chars: int) -> TokenUsage:
    """Fallback: estimate tokens and cost from character counts."""
    pt = max(0, prompt_chars // _CHARS_PER_TOKEN)
    ct = max(0, completion_chars // _CHARS_PER_TOKEN)
    cost = (pt + ct) * _COST_PER_TOKEN
    return TokenUsage(
        prompt_tokens=pt,
        completion_tokens=ct,
        estimated_cost_usd=cost,
        usage_source="estimated",
    )


def resolve_usage(
    result_obj: Any,
    prompt_chars: int,
    completion_chars: int,
) -> TokenUsage:
    """Actual-first: use provider usage when present, else estimate. Returns normalized TokenUsage."""
    actual = extract_actual_usage(result_obj)
    if actual is not None:
        return actual
    return estimate_usage(prompt_chars, completion_chars)


def merge_usage_sources(acc_source: str, inc_source: str) -> str:
    """Compute combined usage_source when merging two usages.
    actual + actual -> actual; estimated + estimated -> estimated; else -> mixed.
    """
    a = (acc_source or "").strip().lower()
    b = (inc_source or "").strip().lower()
    if a == "actual" and b == "actual":
        return "actual"
    if a == "estimated" and b == "estimated":
        return "estimated"
    return "mixed"
