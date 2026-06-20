"""
taskpeasant/query.py
Structured filter engine for TaskPeasant.
Mirrors the subset of Taskwarrior filter syntax that the studio UI uses.

Supported filter keys:
  status:pending           exact match (also matches 'waiting' like TW does)
  +tag / -tag              tag inclusion / exclusion
  due.any: / due.none:     date field presence check
  scheduled.any:           same
  uuid:<prefix>            UUID prefix match (for targeted commands)
  bare word                case-insensitive description search
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List

from .task_model import Task


def _parse_tw_date(s: str):
    """Parse TW or ISO date → datetime (UTC). Returns None on failure."""
    if not s:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class Filter:
    """
    Compiled filter object.  Build once with Filter.parse(tokens), then call
    filter.matches(task) repeatedly.
    """

    def __init__(self):
        self._rules: list = []     # list of callables: (Task) -> bool

    @classmethod
    def parse(cls, tokens: list[str]) -> "Filter":
        f = cls()
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue

            # +tag  /  -tag
            if tok.startswith("+") and len(tok) > 1:
                tag = tok[1:]
                f._rules.append(lambda t, tg=tag: tg in t.tags)
            elif tok.startswith("-") and len(tok) > 1:
                tag = tok[1:]
                f._rules.append(lambda t, tg=tag: tg not in t.tags)

            # uuid:<prefix>
            elif tok.startswith("uuid:"):
                prefix = tok[5:].lower()
                f._rules.append(lambda t, px=prefix: t.uuid.lower().startswith(px))

            # status:<value>
            elif tok.startswith("status:"):
                val = tok[7:]
                if val == "pending":
                    # Mirror TW: status:pending also returns waiting tasks
                    f._rules.append(lambda t: t.status in ("pending", "waiting"))
                else:
                    f._rules.append(lambda t, v=val: t.status == v)

            # due.any: / scheduled.any: / due.none:  etc.
            elif re.match(r'\w+\.(any|none):', tok):
                field, _, qualifier = tok.partition(".")
                presence = qualifier.startswith("any")
                f._rules.append(
                    lambda t, fld=field, pres=presence:
                        bool(getattr(t, fld, "")) == pres
                )

            # bare word = description search (case-insensitive)
            elif ":" not in tok:
                word = tok.lower()
                f._rules.append(
                    lambda t, w=word: w in t.description.lower()
                )

        return f

    def matches(self, task: Task) -> bool:
        return all(rule(task) for rule in self._rules)


def apply_filter(tasks: List[Task], tokens: list[str]) -> List[Task]:
    f = Filter.parse(tokens)
    return [t for t in tasks if f.matches(t)]
