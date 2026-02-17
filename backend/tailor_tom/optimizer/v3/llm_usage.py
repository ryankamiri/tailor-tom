"""Aggregate and report LLM token/cost usage for V3."""

from tailor_tom.optimizer.v3.types import TokenUsage
from tailor_tom.optimizer.v3.usage_extractor import merge_usage_sources


def merge_usage(acc: TokenUsage, inc: TokenUsage) -> TokenUsage:
    """Merge incremental usage into accumulator. Numerics sum; source via merge_usage_sources."""
    # Bootstrap behavior: don't let an empty accumulator force a mixed source
    # on the first real increment.
    if (acc.prompt_tokens == 0 and acc.completion_tokens == 0 and acc.estimated_cost_usd == 0):
        combined_source = inc.usage_source
    elif (inc.prompt_tokens == 0 and inc.completion_tokens == 0 and inc.estimated_cost_usd == 0):
        combined_source = acc.usage_source
    else:
        combined_source = merge_usage_sources(acc.usage_source, inc.usage_source)
    return TokenUsage(
        prompt_tokens=acc.prompt_tokens + inc.prompt_tokens,
        completion_tokens=acc.completion_tokens + inc.completion_tokens,
        estimated_cost_usd=acc.estimated_cost_usd + inc.estimated_cost_usd,
        usage_source=combined_source,
    )


def usage_from_counts(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    usage_source: str = "estimated",
) -> TokenUsage:
    """Build TokenUsage from raw counts."""
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
        usage_source=usage_source,
    )
