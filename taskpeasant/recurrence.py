"""
taskpeasant/recurrence.py
Recurring tasks — a port of Taskwarrior's template/child model, OPT-IN.

The compat contract freezes the status enum at four values, so nothing
here runs unless the host sets `recurrence=on` (taskrc, rc override, or
Taskrc instance).  When enabled:

  task add pay rent due:1st recur:monthly [until:<date>]
      → stores a TEMPLATE with status "recurring"

  On every command, synthesize() materialises child instances: one for
  each occurrence whose due date has arrived, plus `recurrence.limit`
  (default 1) upcoming ones.  Children are plain pending tasks carrying
  parent=<template uuid>, imask=<index>, recur and until copies.

  The template's `mask` records one character per generated child:
  '-' pending, '+' completed, 'X' deleted, 'W' waiting (TW's encoding).

  Tasks (of any kind) whose `until` date has passed are expired —
  status → deleted — matching TW's gc behaviour.

Duration grammar: daily, weekdays, weekly, biweekly/fortnight, monthly,
bimonthly, quarterly, semiannual, yearly/annual(ly), biannual/biyearly,
and <N><unit> forms (3d, 2w, 10mo, 1m=1month, 2q, 1y).
"""

from __future__ import annotations

import calendar
import re
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from ._dates import parse_date
from .task_model import Task

# (months, days) per occurrence step; "weekdays" is handled separately
_NAMED_DURATIONS = {
    "daily":      (0, 1),
    "day":        (0, 1),
    "weekly":     (0, 7),
    "biweekly":   (0, 14),
    "fortnight":  (0, 14),
    "monthly":    (1, 0),
    "bimonthly":  (2, 0),
    "quarterly":  (3, 0),
    "semiannual": (6, 0),
    "yearly":     (12, 0),
    "annual":     (12, 0),
    "annually":   (12, 0),
    "biannual":   (24, 0),
    "biyearly":   (24, 0),
}

_UNIT_RE = re.compile(
    r'^(\d+)\s*'
    r'(d|days?|w|wks?|weeks?|mo|mos|mths?|months?|m|q|qtrs?|quarters?|'
    r'y|yrs?|years?)$',
    re.IGNORECASE,
)


def parse_recur(spec: str) -> Optional[Tuple[int, int]]:
    """recur value → (months, days) per step, ("weekdays" → (0, 0) marker
    handled by callers via is_weekdays()).  None when unparseable."""
    s = (spec or "").strip().lower()
    if not s:
        return None
    if s == "weekdays":
        return (0, 0)
    if s in _NAMED_DURATIONS:
        return _NAMED_DURATIONS[s]
    m = _UNIT_RE.match(s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("d"):
        return (0, n)
    if unit.startswith("w"):
        return (0, 7 * n)
    if unit.startswith("q"):
        return (3 * n, 0)
    if unit.startswith("y"):
        return (12 * n, 0)
    return (n, 0)          # m / mo / month...


def is_weekdays(spec: str) -> bool:
    return (spec or "").strip().lower() == "weekdays"


def _add_months(dt: datetime, n: int) -> datetime:
    month = dt.month + n
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def nth_occurrence(base: datetime, spec: str, k: int) -> Optional[datetime]:
    """The k-th occurrence (k=0 is the template's own due date)."""
    if is_weekdays(spec):
        dt, remaining = base, k
        while remaining > 0:
            dt += timedelta(days=1)
            if dt.weekday() < 5:
                remaining -= 1
        return dt
    step = parse_recur(spec)
    if step is None:
        return None
    months, days = step
    if months == 0 and days == 0:
        return None
    return _add_months(base, months * k) + timedelta(days=days * k)


_MASK_CHAR = {"pending": "-", "completed": "+", "deleted": "X",
              "waiting": "W"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _spawn_child(tpl: Task, due_dt: datetime, index: int) -> Task:
    return Task(
        uuid        = str(_uuid_mod.uuid4()),
        description = tpl.description,
        status      = "pending",
        entry       = _now_iso(),
        modified    = _now_iso(),
        due         = due_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        tags        = list(tpl.tags),
        depends     = list(tpl.depends),
        project     = tpl.project,
        priority    = tpl.priority,
        recur       = tpl.recur,
        until       = tpl.until,
        parent      = tpl.uuid,
        imask       = str(index),
        udas        = dict(tpl.udas),
    )


def synthesize_tasks(tasks: List[Task], limit: int = 1,
                     now: Optional[datetime] = None) -> Tuple[list, bool]:
    """Generate missing children for every recurring template, refresh
    template masks, and expire tasks whose `until` has passed.

    Returns (new_children, changed_existing).
    """
    now = now or datetime.now(timezone.utc)
    changed = False

    children_by_parent: dict = {}
    for t in tasks:
        if t.parent:
            children_by_parent.setdefault(t.parent, []).append(t)

    # Expire: until has passed → deleted (only open, non-template tasks)
    for t in tasks:
        if t.until and t.status in ("pending", "waiting"):
            until_dt = parse_date(t.until)
            if until_dt and until_dt < now:
                t.status = "deleted"
                t.end = _now_iso()
                t.modified = _now_iso()
                changed = True

    new_children: List[Task] = []
    for tpl in tasks:
        if tpl.status != "recurring" or not tpl.recur or not tpl.due:
            continue
        base = parse_date(tpl.due)
        if base is None:
            continue
        until_dt = parse_date(tpl.until) if tpl.until else None

        kids = children_by_parent.get(tpl.uuid, [])
        existing = set()
        for c in kids:
            try:
                existing.add(int(c.imask))
            except (TypeError, ValueError):
                pass

        futures = 0
        k = 0
        while k < 1000:
            due_k = nth_occurrence(base, tpl.recur, k)
            if due_k is None:
                break
            if until_dt and due_k > until_dt:
                break
            if k not in existing:
                new_children.append(_spawn_child(tpl, due_k, k))
            if due_k > now:
                futures += 1
                if futures >= max(limit, 1):
                    k += 1
                    break
            k += 1

        # Refresh the mask: one char per generated child index
        statuses = {}
        for c in kids:
            try:
                statuses[int(c.imask)] = _MASK_CHAR.get(c.status, "-")
            except (TypeError, ValueError):
                pass
        for c in new_children:
            if c.parent == tpl.uuid:
                statuses[int(c.imask)] = "-"
        mask = "".join(statuses.get(i, "-")
                       for i in range(max(statuses) + 1)) if statuses else ""
        if mask != tpl.mask:
            tpl.mask = mask
            tpl.modified = _now_iso()
            changed = True

    return new_children, changed


def synthesize(yaml_path: str, conf) -> None:
    """Read-modify-write wrapper used by the dispatchers.  Only call
    when `recurrence` is enabled; never raises."""
    from .storage import read_tasks, write_tasks
    try:
        tasks = read_tasks(yaml_path)
        if not any(t.status == "recurring" or t.until for t in tasks):
            return
        new_children, changed = synthesize_tasks(
            tasks, conf.get_int("recurrence.limit", 1))
        if new_children or changed:
            write_tasks(yaml_path, tasks + new_children)
    except Exception:
        pass
