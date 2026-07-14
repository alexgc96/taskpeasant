"""
taskpeasant/_vtags.py
Virtual tags — computed task state exposed through tag syntax.

Mirrors Taskwarrior's convention: uppercase tags are virtual, applied at
read time, never persisted.  `+OVERDUE`, `-BLOCKED` etc. work in any
filter because query.py checks Task.virtual_tags alongside real tags.

BLOCKED/BLOCKING need the whole task graph, so annotate_virtual_tags()
is the entry point: it builds the uuid and reverse-dependency indexes
once and stamps every task in a single O(n + edges) pass.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from ._dates import parse_date
from .task_model import Task

VIRTUAL_TAG_NAMES = frozenset([
    "PENDING", "COMPLETED", "DELETED", "WAITING", "RECURRING",
    "ACTIVE", "OVERDUE", "TODAY", "DUE", "SCHEDULED",
    "TAGGED", "ANNOTATED", "BLOCKED", "BLOCKING", "PROJECT",
    "READY", "UNBLOCKED", "UDA", "LATEST", "PARENT", "CHILD",
    "UNTIL", "PRIORITY",
])

# Statuses whose tasks participate in the dependency graph
_OPEN = ("pending", "waiting")

# TW's default "due" horizon
_DUE_HORIZON = timedelta(days=7)


def compute_virtual_tags(
    task: Task,
    tasks_by_uuid: Optional[Dict[str, Task]] = None,
    reverse_depends: Optional[Dict[str, List[str]]] = None,
) -> Set[str]:
    """Return the virtual tag set for one task.

    Graph tags (BLOCKED/BLOCKING) are only computed when the caller
    supplies the indexes — use annotate_virtual_tags() for a whole list.
    """
    now = datetime.now(timezone.utc)
    vtags: Set[str] = {task.status.upper()}

    if task.start and task.status == "pending":
        vtags.add("ACTIVE")

    if task.due:
        due_dt = parse_date(task.due)
        if due_dt:
            if due_dt < now:
                vtags.add("OVERDUE")
            if due_dt.date() == now.date():
                vtags.add("TODAY")
            if due_dt <= now + _DUE_HORIZON:
                vtags.add("DUE")

    if task.scheduled:
        vtags.add("SCHEDULED")
    if task.tags:
        vtags.add("TAGGED")
    if task.annotations:
        vtags.add("ANNOTATED")
    if task.project:
        vtags.add("PROJECT")
    if task.priority:
        vtags.add("PRIORITY")
    if task.udas:
        vtags.add("UDA")
    if task.udas.get("until"):
        vtags.add("UNTIL")
    if task.udas.get("recur"):
        vtags.add("PARENT" if task.status == "recurring" else "CHILD")

    if task.status in _OPEN:
        if tasks_by_uuid is not None:
            for dep_uuid in task.depends:
                dep = tasks_by_uuid.get(dep_uuid)
                if dep is not None and dep.status in _OPEN:
                    vtags.add("BLOCKED")
                    break
        if reverse_depends is not None and task.uuid in reverse_depends:
            vtags.add("BLOCKING")

    if task.status == "pending":
        if "BLOCKED" not in vtags:
            vtags.add("UNBLOCKED")
        # READY: pending, unblocked, and not scheduled for the future
        # (a pending status already means any wait date has passed)
        sched_dt = parse_date(task.scheduled) if task.scheduled else None
        if "BLOCKED" not in vtags and (sched_dt is None or sched_dt <= now):
            vtags.add("READY")

    return vtags


def annotate_virtual_tags(tasks: List[Task]) -> None:
    """Set t.virtual_tags on every task, computing BLOCKED/BLOCKING
    against the full graph in one pass."""
    tasks_by_uuid = {t.uuid: t for t in tasks}
    reverse_depends: Dict[str, List[str]] = {}
    for t in tasks:
        if t.status in _OPEN:
            for dep_uuid in t.depends:
                dep = tasks_by_uuid.get(dep_uuid)
                if dep is not None and dep.status in _OPEN:
                    reverse_depends.setdefault(dep_uuid, []).append(t.uuid)

    for t in tasks:
        t.virtual_tags = compute_virtual_tags(t, tasks_by_uuid, reverse_depends)

    # LATEST — the most recently added task (TW semantics)
    dated = [(t.entry, t.uuid, t) for t in tasks if t.entry]
    if dated:
        max(dated)[2].virtual_tags.add("LATEST")
