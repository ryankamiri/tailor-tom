"""Helpers for classifying provider/LLM exceptions into stable error codes."""

from tailor_tom.optimizer.v3.types import LLMErrorInfo


ERROR_INVALID_API_KEY = "invalid_api_key"
ERROR_LLM_AUTH = "llm_auth_error"
ERROR_LLM_PROVIDER = "llm_provider_error"


def classify_llm_exception(exc: Exception, *, stage: str) -> LLMErrorInfo:
    """Convert provider exceptions into a stable error payload."""
    raw_error = str(exc or "").strip()
    normalized = raw_error.lower()

    if (
        "incorrect api key provided" in normalized
        or "invalid api key" in normalized
        or ("authenticationerror" in normalized and "api key" in normalized)
    ):
        return LLMErrorInfo(
            code=ERROR_INVALID_API_KEY,
            message="Invalid OpenAI API key configured for the worker.",
            stage=stage,
            raw_error=raw_error,
        )

    if "authenticationerror" in normalized or "unauthorized" in normalized:
        return LLMErrorInfo(
            code=ERROR_LLM_AUTH,
            message="LLM provider authentication failed.",
            stage=stage,
            raw_error=raw_error,
        )

    return LLMErrorInfo(
        code=ERROR_LLM_PROVIDER,
        message=f"LLM provider call failed during {stage}.",
        stage=stage,
        raw_error=raw_error,
    )
