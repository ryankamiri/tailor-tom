"""Shared validation helpers for API route parameters."""

from __future__ import annotations

from datetime import datetime, timezone


def validate_admin_utc_month(
    year: int | None,
    month: int | None,
) -> tuple[int, int]:
    """Validate and normalize UTC calendar month for admin endpoints.
    If both None, use current UTC month. If one provided, both required.
    Returns (year, month). Raises ValueError on invalid."""
    now = datetime.now(timezone.utc)
    if year is None and month is None:
        return now.year, now.month
    if year is not None and month is None:
        raise ValueError("when year is provided, month is required")
    if month is not None and year is None:
        raise ValueError("when month is provided, year is required")
    if not (1 <= month <= 12):
        raise ValueError("month must be 1..12")
    return year, month


def validate_pagination(
    page: int,
    limit: int,
    max_limit: int = 100,
) -> tuple[int, int]:
    """Validate pagination bounds. Returns (page, limit). Raises ValueError on invalid."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if limit < 1 or limit > max_limit:
        raise ValueError(f"limit must be 1..{max_limit}")
    return page, limit
