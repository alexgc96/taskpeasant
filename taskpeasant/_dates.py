"""Shared date utilities — alias resolution and parsing."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone

_REL_DATE_RE = re.compile(r'^\+(\d+)([dwmy])$', re.IGNORECASE)


def _next_weekday(now: datetime, weekday: int) -> str:
    days_ahead = weekday - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def resolve_date(val: str) -> str:
    """Expand TW date shortcuts and +Nd/w/m/y offsets to YYYY-MM-DD.

    Returns the original string unchanged if it doesn't match any alias —
    callers should validate with parse_date() if they need to reject garbage.
    """
    now = datetime.now(timezone.utc)

    m = _REL_DATE_RE.match(val)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit == "d":
            return (now + timedelta(days=n)).strftime("%Y-%m-%d")
        if unit == "w":
            return (now + timedelta(weeks=n)).strftime("%Y-%m-%d")
        if unit == "m":
            month = now.month + n
            year  = now.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            day   = min(now.day, calendar.monthrange(year, month)[1])
            return datetime(year, month, day, tzinfo=timezone.utc).strftime("%Y-%m-%d")
        if unit == "y":
            return now.replace(year=now.year + n).strftime("%Y-%m-%d")

    eom = (now.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    aliases = {
        # Named points in time
        "now":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today":     now.strftime("%Y-%m-%d"),
        "tomorrow":  (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        # Week boundaries
        "sow":       (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d"),        # Monday
        "eow":       (now + timedelta(days=(6 - now.weekday()))).strftime("%Y-%m-%d"),  # Sunday
        "eoww":      _next_weekday(now, 4),  # end of work week = Friday
        # Month boundaries
        "som":       now.replace(day=1).strftime("%Y-%m-%d"),
        "eom":       eom.strftime("%Y-%m-%d"),
        # Year boundaries
        "soy":       now.replace(month=1, day=1).strftime("%Y-%m-%d"),
        "eoy":       now.replace(month=12, day=31).strftime("%Y-%m-%d"),
        # Weekday names — next occurrence (including today if it matches)
        "monday":    _next_weekday(now, 0),
        "tuesday":   _next_weekday(now, 1),
        "wednesday": _next_weekday(now, 2),
        "thursday":  _next_weekday(now, 3),
        "friday":    _next_weekday(now, 4),
        "saturday":  _next_weekday(now, 5),
        "sunday":    _next_weekday(now, 6),
        # Short forms
        "mon": _next_weekday(now, 0),
        "tue": _next_weekday(now, 1),
        "wed": _next_weekday(now, 2),
        "thu": _next_weekday(now, 3),
        "fri": _next_weekday(now, 4),
        "sat": _next_weekday(now, 5),
        "sun": _next_weekday(now, 6),
        # Someday / later — TW uses year 2038; we use 9 years out
        "someday":   now.replace(year=now.year + 9).strftime("%Y-%m-%d"),
        "later":     now.replace(year=now.year + 9).strftime("%Y-%m-%d"),
    }
    return aliases.get(val.lower(), val)


def parse_date(s: str):
    """Parse ISO or TW wire date string → aware datetime, or None."""
    s = resolve_date(s)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
