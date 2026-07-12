"""
taskpeasant/commands.py
Pure functional task operations. Each function reads from / writes to
a project YAML via storage.py, then returns a human-readable result string
(mirroring Taskwarrior's stdout so the terminal widget shows the same output).

Status transitions mirror Taskwarrior (from Task.h / Task.cpp):
  add          → pending, entry=now
  start        → pending + start=now  (TW: is_active when start is set)
  stop         → pending, start cleared
  done         → completed, end=now, start cleared
  delete       → deleted,  end=now
  annotate     → append to annotations[]
  modify       → update arbitrary fields
"""

from __future__ import annotations

import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Optional

from .task_model import Task
from .storage import read_tasks, write_tasks, assign_ids
from .query import apply_filter
from ._vtags import VIRTUAL_TAG_NAMES


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reserved_tag(tags) -> Optional[str]:
    """Return the first tag that collides with a virtual tag name, if any."""
    for tag in (tags or []):
        if tag in VIRTUAL_TAG_NAMES:
            return tag
    return None


def _find_one(tasks: list[Task], uuid_prefix: str) -> Optional[Task]:
    uuid_prefix = uuid_prefix.lower()
    matches = [t for t in tasks if t.uuid.lower().startswith(uuid_prefix)]
    return matches[0] if len(matches) == 1 else None


# ── add ───────────────────────────────────────────────────────────────────────

def cmd_add(yaml_path: str, description: str, tags: list = None,
            due: str = "", scheduled: str = "", wait: str = "",
            project: str = "", priority: str = "") -> str:
    """Create a new task. Returns a confirmation string."""
    reserved = _reserved_tag(tags)
    if reserved:
        return f"Error: '+{reserved}' is a virtual tag and cannot be added."
    tasks    = read_tasks(yaml_path)
    new_uuid = str(_uuid_mod.uuid4())
    t = Task(
        uuid        = new_uuid,
        description = description,
        status      = "waiting" if wait else "pending",
        entry       = _now_iso(),
        modified    = _now_iso(),
        tags        = list(tags or []),
        due         = due,
        scheduled   = scheduled,
        wait        = wait,
        project     = project,
        priority    = priority,
    )
    tasks.append(t)
    write_tasks(yaml_path, tasks)
    return f"Created task {new_uuid[:8]}  '{description}'"


# ── done ──────────────────────────────────────────────────────────────────────

def cmd_done(yaml_path: str, uuid_prefix: str) -> str:
    """Mark a task completed. Sets end, clears start."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    if t.status == "completed":
        return f"Task {t.uuid[:8]} is already completed."
    t.status   = "completed"
    t.end      = _now_iso()
    t.start    = ""          # TW clears start on completion
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    return f"Completed task {t.uuid[:8]}  '{t.description}'"


# ── delete ────────────────────────────────────────────────────────────────────

def cmd_delete(yaml_path: str, uuid_prefix: str) -> str:
    """Mark a task deleted. Sets end."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    t.status   = "deleted"
    t.end      = _now_iso()
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    return f"Deleted task {t.uuid[:8]}  '{t.description}'"


# ── start / stop ──────────────────────────────────────────────────────────────

def cmd_start(yaml_path: str, uuid_prefix: str) -> str:
    """Set start to now — task becomes active."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    if t.start:
        return f"Task {t.uuid[:8]} is already active."
    t.start    = _now_iso()
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    return f"Started task {t.uuid[:8]}  '{t.description}'"


def cmd_stop(yaml_path: str, uuid_prefix: str) -> str:
    """Clear start — task becomes inactive."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    t.start    = ""
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    return f"Stopped task {t.uuid[:8]}  '{t.description}'"


# ── annotate ──────────────────────────────────────────────────────────────────

def cmd_annotate(yaml_path: str, uuid_prefix: str, note: str) -> str:
    """Append an annotation to a task."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    t.annotations.append({"entry": _now_iso(), "description": note})
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    return f"Annotated task {t.uuid[:8]}."


# ── modify ────────────────────────────────────────────────────────────────────

def cmd_modify(yaml_path: str, uuid_prefix: str, mods: dict) -> str:
    """
    mods dict may contain: description, due, scheduled, status,
    tags_add (list), tags_remove (list), depends (list), and any UDA key.
    """
    reserved = _reserved_tag(mods.get("tags_add"))
    if reserved:
        return f"Error: '+{reserved}' is a virtual tag and cannot be added."

    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"

    for key, val in mods.items():
        if key == "description":
            t.description = val
        elif key in ("due", "scheduled", "wait"):
            setattr(t, key, val)
            if key == "wait" and val:
                t.status = "waiting"
        elif key == "status":
            if val in ("pending", "completed", "deleted", "waiting"):
                t.status = val
                if val == "completed" and not t.end:
                    t.end   = _now_iso()
                    t.start = ""
        elif key == "project":
            t.project = val
        elif key == "priority":
            t.priority = val
        elif key == "tags_add":
            for tag in (val or []):
                if tag not in t.tags:
                    t.tags.append(tag)
        elif key == "tags_remove":
            t.tags = [tg for tg in t.tags if tg not in (val or [])]
        elif key == "depends":
            t.depends = val if isinstance(val, list) else [val]
        else:
            t.udas[key] = val    # unknown keys stored as UDA

    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    return f"Modified task {t.uuid[:8]}  '{t.description}'"


# ── export (used by Flask API routes) ────────────────────────────────────────

def cmd_export(yaml_path: str, filter_tokens: list = None) -> list:
    """Return TW-wire-format dicts, ready to JSON-serialise for the UI."""
    from .urgency import compute_urgency
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    if filter_tokens:
        tasks = apply_filter(tasks, filter_tokens)
    for t in tasks:
        t.urgency_value = compute_urgency(t)
    return [t.to_tw_export() for t in tasks]
