"""
taskpeasant/peasant_parser.py
Parse faux-terminal strings in Taskwarrior CLI syntax and dispatch
to the correct commands.py function.

Supported syntax (a subset, focused on what a host application's terminal
widget typically sends):
  task add +tag description text due:2026-04-20
  task <uuid_prefix> done
  task <uuid_prefix> delete
  task <uuid_prefix> start
  task <uuid_prefix> stop
  task <uuid_prefix> annotate This is a note
  task <uuid_prefix> modify +newtag -oldtag due:2026-04-25 description:new text
  task +tag export
  task +tag status:pending export
  task rc.gc=off +tag export           ← rc.* flags silently stripped

Returns a plain text string (the "terminal output") so a host's JS
terminal widget renders it unchanged.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Optional

from . import commands
from ._dates import resolve_date, parse_date
from .query import apply_filter
from .reports import cmd_history, cmd_ghistory, cmd_burndown, cmd_calendar
from .storage import read_tasks, assign_ids
from .urgency import compute_urgency


_INVALID_DATE = "__invalid__"


def _resolve_date_alias(val: str) -> str:
    """Resolve alias/offset to ISO date. Returns _INVALID_DATE sentinel if unrecognised."""
    resolved = resolve_date(val)
    return resolved if parse_date(resolved) is not None else _INVALID_DATE


# ── Token classifier ──────────────────────────────────────────────────────────

_UUID_RE    = re.compile(r'^[0-9a-f]{4,}(-[0-9a-f]{4}){0,3}', re.IGNORECASE)
_DATE_KEYS  = frozenset(["due", "scheduled", "wait", "until"])
_FIELD_KEYS = frozenset(["description", "status", "depends", "priority", "project"])


def _is_uuid(tok: str) -> bool:
    return bool(_UUID_RE.match(tok))


def _resolve_id(yaml_path: str, tok: str) -> Optional[str]:
    """If tok is a positive integer, return the matching task UUID; else None."""
    if not tok.isdigit():
        return None
    int_id = int(tok)
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    match = next((t for t in tasks if t.id == int_id), None)
    return match.uuid if match else None


def _parse_mod_tokens(tokens: list) -> dict:
    """
    Convert a list of tokens into a mods dict.
    Returns: {"due": "2026-04-20", "tags_add": ["render"], "tags_remove": ["draft"], ...}
    """
    mods:       dict = {}
    desc_parts: list = []

    for tok in tokens:
        # +tag  →  tags_add
        if tok.startswith("+") and len(tok) > 1:
            mods.setdefault("tags_add", []).append(tok[1:])

        # -tag  →  tags_remove
        elif tok.startswith("-") and len(tok) > 1:
            mods.setdefault("tags_remove", []).append(tok[1:])

        # key:value pairs
        elif ":" in tok and not tok.startswith("("):
            key, _, val = tok.partition(":")
            key = key.lower()
            if key in _DATE_KEYS:
                resolved = _resolve_date_alias(val)
                if resolved == _INVALID_DATE:
                    mods["__date_error__"] = val
                else:
                    mods[key] = resolved
            elif key in _FIELD_KEYS:
                # description:some text (rest of value after colon)
                mods[key] = val
            else:
                mods[key] = val   # UDA

        # bare word — accumulate as description
        else:
            desc_parts.append(tok)

    if desc_parts:
        # Only set description if not already set via description:value syntax
        mods.setdefault("description", " ".join(desc_parts))

    return mods


# ── Main parser / dispatcher ──────────────────────────────────────────────────

def execute_command(raw: str, yaml_path: str) -> str:
    """
    Parse a raw CLI string and dispatch to the correct command.
    Returns terminal output as a plain string.

    yaml_path must be the absolute path to a YAML file that TaskPeasant
    is allowed to read and write (it edits the `taskpeasant_tasks:` key).
    """
    # Contract: this function returns a string and never raises
    # (docs/BACKWARDS_COMPAT.md §5), so trap everything.
    try:
        return _execute_command(raw, yaml_path)
    except Exception as e:
        return f"Error: {e}"


def _execute_command(raw: str, yaml_path: str) -> str:
    try:
        tokens = shlex.split(raw)
    except ValueError as e:
        return f"Parse error: {e}"

    if not tokens:
        return ""

    # Strip leading 'task' keyword (host terminals typically prepend it)
    if tokens and tokens[0].lower() == "task":
        tokens = tokens[1:]

    # Strip rc.* flags silently (e.g. rc.gc=off, rc.confirmation=off)
    tokens = [t for t in tokens if not t.startswith("rc.")]

    if not tokens:
        return _cmd_list(yaml_path, [])

    first = tokens[0]

    # ── Pre-flight: catch invalid dates anywhere in the token stream ─────────
    _pre = _parse_mod_tokens(tokens)
    if "__date_error__" in _pre:
        return f"Error: '{_pre['__date_error__']}' is not a recognised date. Try: today, +3d, eom, monday, YYYY-MM-DD"

    # ── Reports ──────────────────────────────────────────────────────────────
    if first in ("history",):
        return cmd_history(read_tasks(yaml_path))
    if first in ("ghistory",):
        return cmd_ghistory(read_tasks(yaml_path))
    if first in ("burndown", "burndown.daily"):
        return cmd_burndown(read_tasks(yaml_path))
    if first in ("calendar",):
        return cmd_calendar(read_tasks(yaml_path))
    if first == "next":
        return _cmd_next(yaml_path, tokens[1:])
    if first == "all":
        return _cmd_all(yaml_path, tokens[1:])
    if first == "completed":
        return _cmd_completed(yaml_path)
    if first == "waiting":
        return _cmd_waiting(yaml_path)
    if first == "count":
        return _cmd_count(yaml_path, tokens[1:])

    # ── 'add' command ────────────────────────────────────────────────────────
    if first == "add":
        rest = tokens[1:]
        mods = _parse_mod_tokens(rest)
        desc = mods.pop("description", "").strip()
        if not desc:
            return "Error: description is required for 'add'"
        tags      = mods.pop("tags_add", [])
        due       = mods.pop("due", "")
        scheduled = mods.pop("scheduled", "")
        project   = mods.pop("project", "")
        wait      = mods.pop("wait", "")
        priority  = mods.pop("priority", "").upper()
        return commands.cmd_add(yaml_path, desc, tags=tags,
                                due=due, scheduled=scheduled, wait=wait,
                                project=project, priority=priority)

    # ── Integer ID → UUID resolution ─────────────────────────────────────────
    if first.isdigit():
        uuid = _resolve_id(yaml_path, first)
        if not uuid:
            return f"No task with ID {first}"
        tokens[0] = uuid
        first = uuid

    # ── UUID-targeted commands ────────────────────────────────────────────────
    if _is_uuid(first):
        uuid_prefix = first
        verb        = tokens[1].lower() if len(tokens) > 1 else "info"
        rest        = tokens[2:]

        if verb == "done":
            return commands.cmd_done(yaml_path, uuid_prefix)
        if verb == "delete":
            return commands.cmd_delete(yaml_path, uuid_prefix)
        if verb == "start":
            return commands.cmd_start(yaml_path, uuid_prefix)
        if verb == "stop":
            return commands.cmd_stop(yaml_path, uuid_prefix)
        if verb == "annotate":
            note = " ".join(rest)
            if not note:
                return "Error: annotation text required"
            return commands.cmd_annotate(yaml_path, uuid_prefix, note)
        if verb == "modify":
            mods = _parse_mod_tokens(rest)
            if not mods:
                return "Nothing to modify."
            return commands.cmd_modify(yaml_path, uuid_prefix, mods)
        if verb == "info":
            return _cmd_info(yaml_path, uuid_prefix)
        # Fallthrough: treat whole thing as a filter + list
        return _cmd_list(yaml_path, tokens)

    # ── 'export' or implicit list with filter tokens ──────────────────────────
    filter_tokens = [t for t in tokens if t != "export"]
    if "export" in tokens:
        return _cmd_export_text(yaml_path, filter_tokens)

    # ── Default: formatted list ───────────────────────────────────────────────
    return _cmd_list(yaml_path, filter_tokens)


# ── Output formatters ─────────────────────────────────────────────────────────

def _cmd_list(yaml_path: str, filter_tokens: list) -> str:
    """Formatted task list — mirrors `task list` output style."""
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    if filter_tokens:
        tasks = apply_filter(tasks, filter_tokens)
    pending = [t for t in tasks if t.status == "pending"]
    if not pending:
        return "No pending tasks."
    for t in pending:
        t.urgency_value = compute_urgency(t)
    pending.sort(key=lambda t: -t.urgency_value)

    lines = [f"{'ID':>3}  {'UUID':>8}  {'Urg':>5}  Description"]
    lines.append("-" * 65)
    for t in pending:
        tag_str = " ".join(f"+{tg}" for tg in t.tags)
        due_str = f"  due:{t.due[:10]}" if t.due else ""
        active  = " ▶" if t.start else ""
        lines.append(
            f"{t.id:>3}  {t.uuid[:8]:>8}  {t.urgency_value:>5.1f}  "
            f"{t.description[:34]:<34}  {tag_str}{due_str}{active}"
        )
    lines.append(f"\n{len(pending)} task(s)")
    return "\n".join(lines)


def _cmd_export_text(yaml_path: str, filter_tokens: list) -> str:
    """Return JSON string — used by terminal export commands."""
    data = commands.cmd_export(yaml_path, filter_tokens or None)
    return json.dumps(data, indent=2, default=str)


def _cmd_next(yaml_path: str, filter_tokens: list) -> str:
    """Pending tasks sorted by urgency, top 25."""
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    pending = [t for t in tasks if t.status == "pending"]
    if filter_tokens:
        from .query import apply_filter
        pending = apply_filter(pending, filter_tokens, all_tasks=tasks)
    if not pending:
        return "No pending tasks."
    for t in pending:
        t.urgency_value = compute_urgency(t)
    pending.sort(key=lambda t: -t.urgency_value)
    pending = pending[:25]

    lines = [f"{'ID':>3}  {'UUID':>8}  {'Urg':>5}  Description"]
    lines.append("-" * 65)
    for t in pending:
        tag_str = " ".join(f"+{tg}" for tg in t.tags)
        due_str = f"  due:{t.due[:10]}" if t.due else ""
        active  = " ▶" if t.start else ""
        lines.append(
            f"{t.id:>3}  {t.uuid[:8]:>8}  {t.urgency_value:>5.1f}  "
            f"{t.description[:34]:<34}  {tag_str}{due_str}{active}"
        )
    lines.append(f"\n{len(pending)} task(s)")
    return "\n".join(lines)


def _cmd_all(yaml_path: str, filter_tokens: list) -> str:
    """All tasks across all statuses."""
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    if filter_tokens:
        from .query import apply_filter
        tasks = apply_filter(tasks, filter_tokens)
    if not tasks:
        return "No tasks."
    for t in tasks:
        t.urgency_value = compute_urgency(t)
    tasks.sort(key=lambda t: (t.status != "pending", -t.urgency_value))

    lines = [f"{'ID':>3}  {'UUID':>8}  {'Status':<10}  {'Urg':>5}  Description"]
    lines.append("-" * 72)
    for t in tasks:
        lines.append(
            f"{t.id or '—':>3}  {t.uuid[:8]:>8}  {t.status:<10}  "
            f"{t.urgency_value:>5.1f}  {t.description[:34]}"
        )
    lines.append(f"\n{len(tasks)} task(s)")
    return "\n".join(lines)


def _cmd_completed(yaml_path: str) -> str:
    """Completed tasks, most recent first."""
    tasks = read_tasks(yaml_path)
    done  = [t for t in tasks if t.status == "completed"]
    if not done:
        return "No completed tasks."
    done.sort(key=lambda t: t.end or t.modified, reverse=True)

    lines = [f"{'UUID':>8}  {'Completed':<12}  Description"]
    lines.append("-" * 55)
    for t in done:
        end_str = t.end[:10] if t.end else "—"
        lines.append(f"{t.uuid[:8]:>8}  {end_str:<12}  {t.description[:40]}")
    lines.append(f"\n{len(done)} task(s)")
    return "\n".join(lines)


def _cmd_waiting(yaml_path: str) -> str:
    """Waiting tasks with their wait date."""
    tasks   = read_tasks(yaml_path)
    waiting = [t for t in tasks if t.status == "waiting"]
    if not waiting:
        return "No waiting tasks."
    waiting.sort(key=lambda t: t.wait or "")

    lines = [f"{'UUID':>8}  {'Wait until':<12}  Description"]
    lines.append("-" * 55)
    for t in waiting:
        wait_str = t.wait[:10] if t.wait else "—"
        lines.append(f"{t.uuid[:8]:>8}  {wait_str:<12}  {t.description[:40]}")
    lines.append(f"\n{len(waiting)} task(s)")
    return "\n".join(lines)


def _cmd_count(yaml_path: str, filter_tokens: list) -> str:
    """Return task count as a plain integer string."""
    tasks = read_tasks(yaml_path)
    if filter_tokens:
        from .query import apply_filter
        tasks = apply_filter(tasks, filter_tokens)
    return str(len(tasks))


def _cmd_info(yaml_path: str, uuid_prefix: str) -> str:
    """Full detail view for a single task — mirrors `task <uuid> info`."""
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)

    prefix = uuid_prefix.lower()
    matches = [t for t in tasks if t.uuid.lower().startswith(prefix)]
    if not matches:
        return f"No task matching '{uuid_prefix}'"
    t = matches[0]
    t.urgency_value = compute_urgency(t)

    def row(label: str, value: str) -> str:
        return f"{label:<16} {value}" if value else ""

    lines = [
        row("ID",          str(t.id) if t.id else "—"),
        row("UUID",        t.uuid),
        row("Description", t.description),
        row("Status",      t.status),
        row("Project",     t.project),
        row("Priority",    t.priority),
        row("Tags",        " ".join(f"+{tg}" for tg in t.tags)),
        row("Virtual tags", " ".join(f"+{v}" for v in sorted(t.virtual_tags))),
        row("Due",         t.due[:10] if t.due else ""),
        row("Scheduled",   t.scheduled[:10] if t.scheduled else ""),
        row("Depends",     ", ".join(t.depends)),
        row("Entry",       t.entry[:10] if t.entry else ""),
        row("Modified",    t.modified[:10] if t.modified else ""),
        row("Urgency",     str(t.urgency_value)),
    ]
    out = "\n".join(ln for ln in lines if ln)

    if t.annotations:
        out += "\n\nAnnotations:"
        for a in t.annotations:
            date = a.get("entry", "")[:10]
            out += f"\n  {date}  {a.get('description', '')}"

    return out
