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


def _creates_cycle(tasks: list[Task], target: Task, new_dep_uuid: str) -> bool:
    """Would target→new_dep close a dependency cycle? DFS from new_dep."""
    by_uuid = {t.uuid: t for t in tasks}
    stack, seen = [new_dep_uuid], set()
    while stack:
        cur = stack.pop()
        if cur == target.uuid:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        node = by_uuid.get(cur)
        if node:
            stack.extend(node.depends)
    return False


def _resolve_depends(tasks: list[Task], target: Task, spec: str) -> tuple:
    """Resolve a depends: value like '2,8c2f,-3' into a full-UUID list.

    Comma-separated items: bare = add, '-'-prefixed = remove, empty spec
    clears all.  Items may be ephemeral integer IDs (requires assign_ids
    to have run) or UUID prefixes.  Returns (new_list, "") on success or
    ([], error_message) — callers must not write on error.
    """
    spec = spec.strip()
    if not spec:
        return [], ""

    def resolve(ref: str) -> Optional[Task]:
        if ref.isdigit():
            int_id = int(ref)
            return next((t for t in tasks if t.id == int_id), None)
        return _find_one(tasks, ref)

    new_deps = list(target.depends)
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        removing = item.startswith("-")
        ref = item[1:] if removing else item
        dep = resolve(ref)
        if dep is None:
            return [], f"Error: cannot resolve dependency '{ref}'"
        if removing:
            new_deps = [d for d in new_deps if d != dep.uuid]
            continue
        if dep.uuid == target.uuid:
            return [], "Error: a task cannot depend on itself"
        if _creates_cycle(tasks, target, dep.uuid):
            return [], (f"Error: depends:{ref} would create a "
                        "circular dependency")
        if dep.uuid not in new_deps:
            new_deps.append(dep.uuid)
    return new_deps, ""


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


# ── Per-verb field transitions (shared by single-target and bulk paths) ──────

def _apply_done(t: Task) -> bool:
    if t.status == "completed":
        return False
    t.status   = "completed"
    t.end      = _now_iso()
    t.start    = ""          # TW clears start on completion
    t.modified = _now_iso()
    return True


def _apply_delete(t: Task) -> bool:
    if t.status == "deleted":
        return False
    t.status   = "deleted"
    t.end      = _now_iso()
    t.modified = _now_iso()
    return True


def _apply_start(t: Task) -> bool:
    if t.start:
        return False
    t.start    = _now_iso()
    t.modified = _now_iso()
    return True


def _apply_stop(t: Task) -> bool:
    t.start    = ""
    t.modified = _now_iso()
    return True


# ── done ──────────────────────────────────────────────────────────────────────

def cmd_done(yaml_path: str, uuid_prefix: str) -> str:
    """Mark a task completed. Sets end, clears start."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    if not _apply_done(t):
        return f"Task {t.uuid[:8]} is already completed."
    write_tasks(yaml_path, tasks)
    return f"Completed task {t.uuid[:8]}  '{t.description}'"


# ── delete ────────────────────────────────────────────────────────────────────

def cmd_delete(yaml_path: str, uuid_prefix: str) -> str:
    """Mark a task deleted. Sets end."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    if not _apply_delete(t):
        return f"Task {t.uuid[:8]} is already deleted."
    write_tasks(yaml_path, tasks)
    return f"Deleted task {t.uuid[:8]}  '{t.description}'"


# ── start / stop ──────────────────────────────────────────────────────────────

def cmd_start(yaml_path: str, uuid_prefix: str) -> str:
    """Set start to now — task becomes active."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    if not _apply_start(t):
        return f"Task {t.uuid[:8]} is already active."
    write_tasks(yaml_path, tasks)
    return f"Started task {t.uuid[:8]}  '{t.description}'"


def cmd_stop(yaml_path: str, uuid_prefix: str) -> str:
    """Clear start — task becomes inactive."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    _apply_stop(t)
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

def _apply_mods(yaml_path: str, tasks: list[Task], t: Task, mods: dict):
    """Apply a mods dict to one task in memory.

    Returns an error string (caller must not write) or None on success.
    Sets t.modified.
    """
    for key, val in mods.items():
        if key == "description":
            if not val.strip():
                return "Error: description cannot be blank"
            t.description = val
        elif key in ("due", "scheduled", "wait"):
            setattr(t, key, val)
            if key == "wait":
                if val:
                    t.status = "waiting"
                elif t.status == "waiting":
                    t.status = "pending"    # cleared wait releases the task
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
            if isinstance(val, list):
                t.depends = val
            else:
                assign_ids(yaml_path, tasks)   # int refs need ephemeral IDs
                new_deps, err = _resolve_depends(tasks, t, val)
                if err:
                    return err
                t.depends = new_deps
        else:
            # Unknown keys are UDAs; an empty value deletes the UDA
            if val == "":
                t.udas.pop(key, None)
            else:
                t.udas[key] = val

    t.modified = _now_iso()
    return None


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

    err = _apply_mods(yaml_path, tasks, t, mods)
    if err:
        return err
    write_tasks(yaml_path, tasks)
    return f"Modified task {t.uuid[:8]}  '{t.description}'"


# ── bulk (filter-targeted mutations: `task +urgent done`) ────────────────────

_BULK_LABELS = {
    "done":     "Completed",
    "delete":   "Deleted",
    "start":    "Started",
    "stop":     "Stopped",
    "modify":   "Modified",
    "annotate": "Annotated",
}


def cmd_bulk(yaml_path: str, filter_tokens: list, verb: str,
             mods: dict = None, note: str = "") -> str:
    """Apply a mutation verb to every task matching a filter expression.

    One read, one write: all matches are resolved against the pre-write
    snapshot and persisted together.  Inapplicable tasks (already
    completed/deleted/active) are skipped and counted, never errors.
    Any error (unusable filter, bad mods) aborts before writing.
    """
    from .query import Filter, FilterError

    if verb not in _BULK_LABELS:
        return f"Error: unknown bulk verb '{verb}'"

    try:
        f = Filter.parse(filter_tokens)
    except FilterError as e:
        return f"Error: {e}"
    if f.unknown_tokens:
        # A token the engine can't evaluate would silently match
        # everything — far too dangerous for a destructive bulk verb.
        return (f"Error: unrecognised filter token "
                f"'{f.unknown_tokens[0]}' in bulk operation")

    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)   # annotates virtual tags for the filter
    matches = [t for t in tasks if f.matches(t)]
    if not matches:
        return "No matching tasks."

    applied: list = []
    skipped = 0

    if verb == "modify":
        if not mods:
            return "Nothing to modify."
        reserved = _reserved_tag(mods.get("tags_add"))
        if reserved:
            return f"Error: '+{reserved}' is a virtual tag and cannot be added."
        for t in matches:
            err = _apply_mods(yaml_path, tasks, t, mods)
            if err:
                return err          # abort whole bulk before writing
        applied = matches
    elif verb == "annotate":
        for t in matches:
            t.annotations.append({"entry": _now_iso(), "description": note})
            t.modified = _now_iso()
        applied = matches
    else:
        apply_fn = {"done": _apply_done, "delete": _apply_delete,
                    "start": _apply_start, "stop": _apply_stop}[verb]
        for t in matches:
            if apply_fn(t):
                applied.append(t)
            else:
                skipped += 1

    label = _BULK_LABELS[verb]
    skip_str = f" ({skipped} skipped)" if skipped else ""
    if not applied:
        return f"{label} 0 tasks{skip_str}."

    write_tasks(yaml_path, tasks)
    lines = [f"{label} {len(applied)} task(s){skip_str}:"]
    for t in applied[:10]:
        lines.append(f"  {t.uuid[:8]}  '{t.description}'")
    if len(applied) > 10:
        lines.append(f"  ... and {len(applied) - 10} more")
    return "\n".join(lines)


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
