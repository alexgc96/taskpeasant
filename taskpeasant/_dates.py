"""Shared date utilities — TW-style alias resolution and parsing.

Grammar (a close port of Taskwarrior's Datetime/Duration handling):

    <date> := <base>? <offset>*
    base   := today | now | tomorrow | yesterday | sod | eod | sow | eow
            | soww | eoww | som | eom | soq | eoq | soy | eoy | weekday name
            | Nth ordinal (23rd) | 10-digit epoch | someday | later
            | YYYY-MM-DD[THH:MM[:SS]]
    offset := (+|-) N unit      unit ∈ s, min, h, d, w, m(onths), q, y

Examples: today, +3d, -2w, eom-1d, now+3h, monday+1w, soq, 23rd.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

# Longest alternatives first so 'mo'/'min' win over bare 'm'
_OFFSET_RE = re.compile(
    r'([+-])(\d+)'
    r'(seconds?|secs?|s|minutes?|mins?|min|hours?|hrs?|h|'
    r'days?|d|weeks?|wks?|w|months?|mos?|mths?|quarters?|qtrs?|q|'
    r'years?|yrs?|y|m)',
    re.IGNORECASE,
)

_ORDINAL_RE = re.compile(r'^(\d{1,2})(st|nd|rd|th)$', re.IGNORECASE)
_EPOCH_RE   = re.compile(r'^\d{10}$')

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _next_weekday_dt(now: datetime, weekday: int) -> datetime:
    days_ahead = weekday - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (now + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0)


def _add_months(dt: datetime, n: int) -> datetime:
    month = dt.month + n
    year  = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day   = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _end_of_month(now: datetime) -> datetime:
    last = calendar.monthrange(now.year, now.month)[1]
    return now.replace(day=last, hour=0, minute=0, second=0, microsecond=0)


def _base_datetime(name: str, now: datetime) -> Optional[Tuple[datetime, bool]]:
    """Resolve a base name → (datetime, carries_time_of_day)."""
    n = name.lower()
    sod = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if n in ("today", "sod"):
        return sod, False
    if n == "eod":
        return sod + timedelta(days=1) - timedelta(seconds=1), True
    if n == "now":
        return now, True
    if n == "tomorrow":
        return sod + timedelta(days=1), False
    if n == "yesterday":
        return sod - timedelta(days=1), False
    if n == "sow":
        return sod - timedelta(days=now.weekday()), False           # Monday
    if n == "eow":
        return sod + timedelta(days=(6 - now.weekday())), False     # Sunday
    if n == "soww":
        return _next_weekday_dt(now, 0), False                      # next Monday
    if n == "eoww":
        return _next_weekday_dt(now, 4), False                      # next Friday
    if n == "som":
        return sod.replace(day=1), False
    if n == "eom":
        return _end_of_month(now), False
    if n == "soq":
        q_month = ((now.month - 1) // 3) * 3 + 1
        return sod.replace(month=q_month, day=1), False
    if n == "eoq":
        q_month = ((now.month - 1) // 3) * 3 + 3
        last = calendar.monthrange(now.year, q_month)[1]
        return sod.replace(month=q_month, day=last), False
    if n == "soy":
        return sod.replace(month=1, day=1), False
    if n == "eoy":
        return sod.replace(month=12, day=31), False
    if n in ("someday", "later"):
        return sod.replace(year=now.year + 9), False
    if n in _WEEKDAYS:
        return _next_weekday_dt(now, _WEEKDAYS[n]), False

    m = _ORDINAL_RE.match(n)
    if m:
        day = int(m.group(1))
        # TW: the next occurrence of that day-of-month
        candidate = now if now.day < day else _add_months(sod, 1)
        last = calendar.monthrange(candidate.year, candidate.month)[1]
        if day > last:
            candidate = _add_months(candidate, 1)
            last = calendar.monthrange(candidate.year, candidate.month)[1]
            if day > last:
                return None
        return candidate.replace(day=day, hour=0, minute=0, second=0,
                                 microsecond=0), False

    if _EPOCH_RE.match(n):
        return datetime.fromtimestamp(int(n), tz=timezone.utc), True

    # Literal dates
    for fmt, has_time in (("%Y-%m-%dT%H:%M:%SZ", True),
                          ("%Y-%m-%dT%H:%M:%S", True),
                          ("%Y-%m-%dT%H:%M", True),
                          ("%Y-%m-%d", False),
                          ("%Y%m%dT%H%M%SZ", True)):
        try:
            return (datetime.strptime(name, fmt).replace(tzinfo=timezone.utc),
                    has_time)
        except ValueError:
            continue
    return None


def _apply_offset(dt: datetime, sign: str, n: int, unit: str
                  ) -> Tuple[datetime, bool]:
    """Apply one signed offset; returns (datetime, offset_carries_time)."""
    mult = 1 if sign == "+" else -1
    u = unit.lower()
    if u.startswith("sec") or u == "s":
        return dt + timedelta(seconds=mult * n), True
    if u.startswith("min"):
        return dt + timedelta(minutes=mult * n), True
    if u.startswith(("hour", "hr")) or u == "h":
        return dt + timedelta(hours=mult * n), True
    if u.startswith("d"):
        return dt + timedelta(days=mult * n), False
    if u.startswith("w"):
        return dt + timedelta(weeks=mult * n), False
    if u.startswith(("q", "qtr")):
        return _add_months(dt, mult * n * 3), False
    if u.startswith("y"):
        return _add_months(dt, mult * n * 12), False
    # months: m, mo, mos, month(s), mth(s)
    return _add_months(dt, mult * n), False


def resolve_date_dt(val: str):
    """Resolve a TW date expression → aware datetime, or None.

    Handles bare offsets (+3d = today+3d), compound expressions
    (eom-2d, now+3h, monday+1w) and all base synonyms.
    """
    s = (val or "").strip()
    if not s:
        return None
    now = datetime.now(timezone.utc)

    # Split base and trailing offsets.  Bare signed offsets anchor at
    # sod for date units / now for time units (matches TW intuition).
    first_off = None
    for m in _OFFSET_RE.finditer(s):
        # Only treat as offset when it runs to the end of the string in a
        # chain — find the earliest offset whose chain covers the tail.
        tail = s[m.start():]
        chain_end = 0
        for cm in _OFFSET_RE.finditer(tail):
            if cm.start() != chain_end:
                break
            chain_end = cm.end()
        if chain_end == len(tail):
            first_off = m.start()
            break

    base_str   = s[:first_off] if first_off is not None else s
    offset_str = s[first_off:] if first_off is not None else ""

    has_time = False
    if base_str:
        base = _base_datetime(base_str, now)
        if base is None:
            return None
        dt, has_time = base
    else:
        # Bare offset: date units anchor at start-of-day, time units at now
        probe = _OFFSET_RE.match(offset_str)
        unit  = probe.group(3).lower() if probe else "d"
        is_time_unit = unit in ("s", "h") or \
            unit.startswith(("sec", "min", "hour", "hr"))
        if is_time_unit:
            dt, has_time = now, True
        else:
            dt = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for m in _OFFSET_RE.finditer(offset_str):
        dt, off_time = _apply_offset(dt, m.group(1), int(m.group(2)),
                                     m.group(3))
        has_time = has_time or off_time

    return dt


def resolve_date(val: str) -> str:
    """Expand TW date shortcuts/expressions to YYYY-MM-DD (or full ISO
    when the expression carries a time of day, e.g. `now`, `+3h`).

    Returns the original string unchanged if it doesn't resolve —
    callers should validate with parse_date() if they need to reject
    garbage.
    """
    s = (val or "").strip()
    if not s:
        return val
    # Fast path: already a plain date / ISO datetime — pass through so
    # stored values round-trip byte-identical.
    if re.match(r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?$', s) or \
            re.match(r'^\d{8}T\d{6}Z$', s):
        return val

    dt = resolve_date_dt(s)
    if dt is None:
        return val

    # Time-of-day matters for `now` and hour/min/sec offsets
    if dt.hour or dt.minute or dt.second:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if s.lower() == "now":
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d")


def parse_date(s: str):
    """Parse ISO / TW wire / synonym date string → aware datetime, or None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return resolve_date_dt(s)
