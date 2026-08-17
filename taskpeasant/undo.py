"""
taskpeasant/undo.py
Undo journal — TaskPeasant's equivalent of Taskwarrior's undo.data.

The compat contract (§2) forbids writing any top-level YAML key other
than `taskpeasant_tasks:`, so the journal lives in a SIDECAR file next
to the tasks file: `<tasks>.yaml` → `<tasks>.yaml.undo`.

Journal format (YAML list, oldest first, capped at UNDO_LIMIT):

    - time: 2026-07-14T10:00:00Z
      op: done
      before: [{uuid: ..., status: pending, ...}]   # pre-mutation snapshots
      after:  [{uuid: ..., status: completed, ...}] # post-mutation snapshots

`task undo` reverts the most recent entry: every `before` snapshot is
restored by uuid, and uuids that only appear in `after` (creations) are
removed.  Journal writes never raise — a failed journal write must not
break the mutation that triggered it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import yaml

UNDO_LIMIT = 100


def undo_path(yaml_path: str) -> str:
    return str(yaml_path) + ".undo"


def _read_journal(yaml_path: str) -> list:
    try:
        raw = yaml.safe_load(Path(undo_path(yaml_path)).read_text(
            encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _write_journal(yaml_path: str, journal: list) -> None:
    try:
        Path(undo_path(yaml_path)).write_text(
            yaml.dump(journal, default_flow_style=False, sort_keys=False,
                      allow_unicode=True),
            encoding="utf-8")
    except Exception:
        pass       # journaling must never break the mutation itself


def record_undo(yaml_path: str, op: str,
                before: List[dict], after: List[dict],
                limit: int = UNDO_LIMIT) -> None:
    """Append one undo entry.  Never raises."""
    try:
        journal = _read_journal(yaml_path)
        journal.append({
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "op": op,
            "before": [dict(d) for d in before],
            "after": [dict(d) for d in after],
        })
        _write_journal(yaml_path, journal[-limit:])
    except Exception:
        pass


def cmd_undo(yaml_path: str) -> str:
    """Revert the most recent journaled operation."""
    from .storage import read_tasks, write_tasks
    from .task_model import Task

    journal = _read_journal(yaml_path)
    if not journal:
        return "No operations to undo."

    entry = journal.pop()
    before = entry.get("before") or []
    after = entry.get("after") or []

    tasks = read_tasks(yaml_path)
    by_uuid = {t.uuid: i for i, t in enumerate(tasks)}

    restored = 0
    for snap in before:
        u = snap.get("uuid")
        if not u:
            continue
        t = Task.from_dict(snap)
        if u in by_uuid:
            tasks[by_uuid[u]] = t
        else:                          # task was purged — bring it back
            tasks.append(t)
        restored += 1

    before_uuids = {d.get("uuid") for d in before}
    created = {d.get("uuid") for d in after} - before_uuids
    if created:
        tasks = [t for t in tasks if t.uuid not in created]
        restored += len(created)

    write_tasks(yaml_path, tasks)
    _write_journal(yaml_path, journal)

    op = entry.get("op", "change")
    return (f"Undid '{op}' — {restored} task"
            f"{'s' if restored != 1 else ''} restored.")
