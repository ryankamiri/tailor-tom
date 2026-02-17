"""TailorTom constants. User settings validation, job limits, optimizer knobs"""

# ---------------------------------------------------------------------------
# User settings validation (PATCH /auth/me, job creation)
# ---------------------------------------------------------------------------
USER_SETTINGS_MAX_ITERATIONS_MIN = 2
USER_SETTINGS_MAX_ITERATIONS_MAX = 5
USER_SETTINGS_TARGET_PAGES_MIN = 1
USER_SETTINGS_TARGET_PAGES_MAX = 3

# ---------------------------------------------------------------------------
# Job limits per user
# ---------------------------------------------------------------------------
DAILY_JOB_LIMIT = 6  # Max completed + active jobs per user per day (UTC)

# ---------------------------------------------------------------------------
# Optimizer (economy mode; token budget uses config max_tokens)
# ---------------------------------------------------------------------------
ECONOMY_TOP_K = 8  # Top-K bullets to consider for rewrite
MIN_SCORE_DELTA_TO_ACCEPT = 0.0  # Minimum ATS score delta to accept (0 = any non-regression)
CANDIDATES_PER_BULLET = 2  # How many candidates the LLM generates per bullet (default when config unset)
