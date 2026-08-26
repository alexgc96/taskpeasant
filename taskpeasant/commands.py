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
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .urgency import UrgencyConfig

from .task_model import Task, _tw_to_iso
from .storage import read_tasks, write_tasks, assign_ids
from .query import apply_filter
from .undo import record_undo
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

def cmd_add(yaml_path: str, description: str, tags: Optional[list[str]] = None,
            due: str = "", scheduled: str = "", wait: str = "",
            project: str = "", priority: str = "",
            recur: str = "", until: str = "") -> str:
    """Create a new task. Returns a confirmation string.

    recur (with a due date) stores a recurring TEMPLATE with status
    "recurring" — callers gate this behind the recurrence=on config.
    """
    reserved = _reserved_tag(tags)
    if reserved:
        return f"Error: '+{reserved}' is a virtual tag and cannot be added."
    if recur and not due:
        return "Error: recur requires a due date"
    tasks    = read_tasks(yaml_path)
    new_uuid = str(_uuid_mod.uuid4())
    status = "pending"
    if recur:
        status = "recurring"
    elif wait:
        status = "waiting"
    t = Task(
        uuid        = new_uuid,
        description = description,
        status      = status,
        entry       = _now_iso(),
        modified    = _now_iso(),
        tags        = list(tags or []),
        due         = due,
        scheduled   = scheduled,
        wait        = wait,
        project     = project,
        priority    = priority,
        recur       = recur,
        until       = until,
    )
    tasks.append(t)
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "add", [], [t.to_dict()])
    label = "recurring task" if recur else "task"
    return f"Created {label} {new_uuid[:8]}  '{description}'"


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
    before = [t.to_dict()]
    if not _apply_done(t):
        return f"Task {t.uuid[:8]} is already completed."
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "done", before, [t.to_dict()])
    return f"Completed task {t.uuid[:8]}  '{t.description}'"


# ── delete ────────────────────────────────────────────────────────────────────

def cmd_delete(yaml_path: str, uuid_prefix: str) -> str:
    """Mark a task deleted. Sets end."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    before = [t.to_dict()]
    if not _apply_delete(t):
        return f"Task {t.uuid[:8]} is already deleted."
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "delete", before, [t.to_dict()])
    return f"Deleted task {t.uuid[:8]}  '{t.description}'"


# ── start / stop ──────────────────────────────────────────────────────────────

def cmd_start(yaml_path: str, uuid_prefix: str) -> str:
    """Set start to now — task becomes active."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    before = [t.to_dict()]
    if not _apply_start(t):
        return f"Task {t.uuid[:8]} is already active."
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "start", before, [t.to_dict()])
    return f"Started task {t.uuid[:8]}  '{t.description}'"


def cmd_stop(yaml_path: str, uuid_prefix: str) -> str:
    """Clear start — task becomes inactive."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    before = [t.to_dict()]
    _apply_stop(t)
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "stop", before, [t.to_dict()])
    return f"Stopped task {t.uuid[:8]}  '{t.description}'"


# ── annotate ──────────────────────────────────────────────────────────────────

def cmd_annotate(yaml_path: str, uuid_prefix: str, note: str) -> str:
    """Append an annotation to a task."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    before = [t.to_dict()]
    t.annotations.append({"entry": _now_iso(), "description": note})
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "annotate", before, [t.to_dict()])
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
        elif key in ("due", "scheduled", "wait", "until"):
            setattr(t, key, val)
            if key == "wait":
                if val:
                    t.status = "waiting"
                elif t.status == "waiting":
                    t.status = "pending"    # cleared wait releases the task
        elif key in ("recur", "parent", "mask", "imask"):
            setattr(t, key, str(val))
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

    before = [t.to_dict()]
    err = _apply_mods(yaml_path, tasks, t, mods)
    if err:
        return err
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "modify", before, [t.to_dict()])
    return f"Modified task {t.uuid[:8]}  '{t.description}'"


# ── bulk (filter-targeted mutations: `task +urgent done`) ────────────────────

_BULK_LABELS = {
    "done":      "Completed",
    "delete":    "Deleted",
    "start":     "Started",
    "stop":      "Stopped",
    "modify":    "Modified",
    "annotate":  "Annotated",
    "duplicate": "Duplicated",
    "purge":     "Purged",
    "append":    "Appended to",
    "prepend":   "Prepended to",
    "denotate":  "Denotated",
}


def cmd_bulk(yaml_path: str, filter_tokens: list[str], verb: str,
             mods: Optional[dict[str, Any]] = None, note: str = "") -> str:
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
    created: list = []      # new tasks from bulk duplicate
    purged:  list = []      # snapshots of permanently removed tasks
    skipped = 0
    before = {t.uuid: t.to_dict() for t in matches}

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
    elif verb in ("append", "prepend"):
        if not note.strip():
            return f"Error: text required for '{verb}'"
        for t in matches:
            t.description = (f"{t.description} {note}" if verb == "append"
                             else f"{note} {t.description}")
            t.modified = _now_iso()
        applied = matches
    elif verb == "denotate":
        for t in matches:
            if _apply_denotate(t, note):
                applied.append(t)
            else:
                skipped += 1
    elif verb == "duplicate":
        for t in matches:
            dup = _duplicate_of(t)
            created.append(dup)
            applied.append(t)
        tasks.extend(created)
    elif verb == "purge":
        for t in matches:
            if t.status == "deleted":
                purged.append(t)
                applied.append(t)
            else:
                skipped += 1
        purged_uuids = {t.uuid for t in purged}
        tasks = [t for t in tasks if t.uuid not in purged_uuids]
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
    if verb == "purge":
        record_undo(yaml_path, "purge",
                    [before[t.uuid] for t in applied], [])
    elif verb == "duplicate":
        record_undo(yaml_path, "duplicate", [],
                    [t.to_dict() for t in created])
    else:
        record_undo(yaml_path, verb,
                    [before[t.uuid] for t in applied],
                    [t.to_dict() for t in applied])
    lines = [f"{label} {len(applied)} task(s){skip_str}:"]
    for t in applied[:10]:
        lines.append(f"  {t.uuid[:8]}  '{t.description}'")
    if len(applied) > 10:
        lines.append(f"  ... and {len(applied) - 10} more")
    return "\n".join(lines)


# ── duplicate / purge / log / append / prepend / denotate / import ──────────

def _duplicate_of(t: Task) -> Task:
    """A fresh pending copy of a task (TW `duplicate` semantics: new uuid,
    entry=now, status/start/end reset, everything else carried over)."""
    return Task(
        uuid        = str(_uuid_mod.uuid4()),
        description = t.description,
        status      = "waiting" if t.wait else "pending",
        entry       = _now_iso(),
        modified    = _now_iso(),
        due         = t.due,
        scheduled   = t.scheduled,
        wait        = t.wait,
        tags        = list(t.tags),
        depends     = list(t.depends),
        annotations = [dict(a) for a in t.annotations],
        project     = t.project,
        priority    = t.priority,
        udas        = dict(t.udas),
    )


def _apply_denotate(t: Task, pattern: str) -> bool:
    """Remove matching annotations (all of them when pattern is empty).
    Returns True when at least one was removed."""
    if not t.annotations:
        return False
    if not pattern.strip():
        t.annotations = []
        t.modified = _now_iso()
        return True
    p = pattern.lower()
    for i, a in enumerate(t.annotations):
        if p in str(a.get("description", "")).lower():
            del t.annotations[i]
            t.modified = _now_iso()
            return True
    return False


def cmd_duplicate(yaml_path: str, uuid_prefix: str) -> str:
    """Create a pending copy of a task."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    dup = _duplicate_of(t)
    tasks.append(dup)
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "duplicate", [], [dup.to_dict()])
    return (f"Duplicated task {t.uuid[:8]} → {dup.uuid[:8]}  "
            f"'{dup.description}'")


def cmd_purge(yaml_path: str, uuid_prefix: str = "") -> str:
    """Permanently remove deleted tasks (TW `purge`: deleted-only).

    With a uuid_prefix, purge that one task; without, purge every task
    whose status is deleted.
    """
    tasks = read_tasks(yaml_path)
    if uuid_prefix:
        t = _find_one(tasks, uuid_prefix)
        if not t:
            return f"No task matching '{uuid_prefix}'"
        if t.status != "deleted":
            return (f"Task {t.uuid[:8]} is not deleted — delete it first, "
                    "purge only removes deleted tasks.")
        victims = [t]
    else:
        victims = [t for t in tasks if t.status == "deleted"]
        if not victims:
            return "No deleted tasks to purge."

    victim_uuids = {t.uuid for t in victims}
    remaining = [t for t in tasks if t.uuid not in victim_uuids]
    # Drop dangling dependency references (TW does this on purge)
    for t in remaining:
        if t.depends:
            t.depends = [d for d in t.depends if d not in victim_uuids]
    write_tasks(yaml_path, remaining)
    record_undo(yaml_path, "purge", [t.to_dict() for t in victims], [])
    n = len(victims)
    return f"Purged {n} task{'s' if n != 1 else ''}."


def cmd_log(yaml_path: str, description: str, tags: Optional[list[str]] = None,
            project: str = "", priority: str = "") -> str:
    """Record an already-completed task (TW `log`)."""
    reserved = _reserved_tag(tags)
    if reserved:
        return f"Error: '+{reserved}' is a virtual tag and cannot be added."
    tasks = read_tasks(yaml_path)
    t = Task(
        uuid        = str(_uuid_mod.uuid4()),
        description = description,
        status      = "completed",
        entry       = _now_iso(),
        end         = _now_iso(),
        modified    = _now_iso(),
        tags        = list(tags or []),
        project     = project,
        priority    = priority,
    )
    tasks.append(t)
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "log", [], [t.to_dict()])
    return f"Logged task {t.uuid[:8]}  '{description}'"


def _cmd_text_edit(yaml_path: str, uuid_prefix: str, text: str,
                   op: str) -> str:
    """Shared body for append/prepend."""
    if not text.strip():
        return f"Error: text required for '{op}'"
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    before = [t.to_dict()]
    t.description = (f"{t.description} {text}" if op == "append"
                     else f"{text} {t.description}")
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, op, before, [t.to_dict()])
    return (f"{'Appended to' if op == 'append' else 'Prepended to'} task "
            f"{t.uuid[:8]}  '{t.description}'")


def cmd_append(yaml_path: str, uuid_prefix: str, text: str) -> str:
    """Append text to a task description."""
    return _cmd_text_edit(yaml_path, uuid_prefix, text, "append")


def cmd_prepend(yaml_path: str, uuid_prefix: str, text: str) -> str:
    """Prepend text to a task description."""
    return _cmd_text_edit(yaml_path, uuid_prefix, text, "prepend")


def cmd_denotate(yaml_path: str, uuid_prefix: str, pattern: str = "") -> str:
    """Remove an annotation matching pattern (all when no pattern)."""
    tasks = read_tasks(yaml_path)
    t     = _find_one(tasks, uuid_prefix)
    if not t:
        return f"No task matching '{uuid_prefix}'"
    before = [t.to_dict()]
    if not _apply_denotate(t, pattern):
        return (f"Task {t.uuid[:8]} has no annotation matching '{pattern}'"
                if pattern else f"Task {t.uuid[:8]} has no annotations.")
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "denotate", before, [t.to_dict()])
    return f"Denotated task {t.uuid[:8]}."


_WIRE_DATE_KEYS = ("entry", "start", "end", "due", "scheduled", "wait",
                   "until", "modified")


def cmd_import(yaml_path: str, json_text: str) -> str:
    """Import TW-export JSON (array, single object, or one object per
    line).  Tasks merge by uuid: existing are updated, new appended."""
    import json as _json

    text = (json_text or "").strip()
    if not text:
        return "Error: no JSON provided to import"

    try:
        data = _json.loads(text)
        records = data if isinstance(data, list) else [data]
    except ValueError:
        # TW also emits one JSON object per line
        try:
            records = [_json.loads(line) for line in text.splitlines()
                       if line.strip().strip(",")]
        except ValueError as e:
            return f"Error: invalid JSON — {e}"

    tasks = read_tasks(yaml_path)
    by_uuid = {t.uuid: i for i, t in enumerate(tasks)}
    before, after = [], []
    added = updated = 0

    for rec in records:
        if not isinstance(rec, dict) or not rec.get("description"):
            continue
        rec = dict(rec)
        for k in ("id", "urgency", "is_active"):      # computed fields
            rec.pop(k, None)
        for k in _WIRE_DATE_KEYS:                     # wire → ISO storage
            if rec.get(k):
                rec[k] = _tw_to_iso(str(rec[k]))
        t = Task.from_dict(rec)
        if t.uuid in by_uuid:
            before.append(tasks[by_uuid[t.uuid]].to_dict())
            tasks[by_uuid[t.uuid]] = t
            updated += 1
        else:
            tasks.append(t)
            by_uuid[t.uuid] = len(tasks) - 1
            added += 1
        after.append(t.to_dict())

    if not after:
        return "Error: no importable tasks found in JSON"

    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "import", before, after)
    return (f"Imported {added + updated} task"
            f"{'s' if added + updated != 1 else ''} "
            f"({added} new, {updated} updated).")


# ── export (used by Flask API routes) ────────────────────────────────────────

def cmd_export(yaml_path: str, filter_tokens: Optional[list[str]] = None, config: Optional["UrgencyConfig"] = None) -> list[dict[str, Any]]:
    """Return TW-wire-format dicts, ready to JSON-serialise for the UI.

    config: optional UrgencyConfig forwarded to compute_urgency.
    """
    from .urgency import compute_urgency
    all_tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, all_tasks, config)
    tasks = all_tasks
    if filter_tokens:
        tasks = apply_filter(tasks, filter_tokens, all_tasks=all_tasks)
    for t in tasks:
        t.urgency_value = compute_urgency(t, config)
    return [t.to_tw_export() for t in tasks]
