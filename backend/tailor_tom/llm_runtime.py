"""Lightweight DSPy configuration for V2 worker and callers.

Avoids importing the full V1 optimizer pipeline when only configuration is needed.
"""

import logging
from typing import Optional

import dspy

from tailor_tom.config import settings

logger = logging.getLogger(__name__)


def configure_dspy(
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> None:
    """Configure DSPy with the specified model.

    Idempotent: if DSPy is already configured, does not reconfigure.
    Call safely at worker startup or per task.

    Args:
        model_name: Model identifier (e.g. openai/gpt-5-mini).
        api_key: OpenAI API key. If not provided, uses settings.
        max_tokens: Max tokens for LLM responses. Defaults to settings.max_tokens.
        temperature: Temperature. Defaults to settings.temperature.
    """
    try:
        if hasattr(dspy.settings, "lm") and dspy.settings.lm is not None:
            return
    except (AttributeError, Exception):
        pass

    model_name = model_name or settings.model_name
    api_key = api_key or settings.openai_api_key
    max_tokens = max_tokens or settings.max_tokens
    temperature = temperature or settings.temperature

    try:
        lm = dspy.LM(
            model=model_name,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            cache=False,
        )
        dspy.configure(lm=lm)
    except Exception as e:
        logger.error(
            "Failed to configure DSPy: %s: %s",
            type(e).__name__,
            e,
            exc_info=True,
        )
        raise
