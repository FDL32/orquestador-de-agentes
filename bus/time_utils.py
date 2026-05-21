"""
Time utilities for the orchestration agent system.

Provides helpers for UTC and local aware datetime handling.
"""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """
    Get current UTC datetime (timezone aware).

    Use for bus events, persistence, and cross-host ordering.
    """
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    """
    Get current local datetime (timezone aware).

    Use for human-readable output, logs, and UI display.
    """
    return datetime.now().astimezone()


def parse_datetime_naive_fallback(dt_str: str) -> datetime:
    """
    Parse datetime string, assuming UTC if naive.

    Fallback for parsing legacy timestamps that may be naive.
    """
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
