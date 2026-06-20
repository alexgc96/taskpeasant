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
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import commands
from .query import apply_filter
from .storage import read_tasks
from .urgency import compute_urgency


# ── Date aliases (mirrors TW's built-in shortcuts) ────────────────────────────

def _next_weekday(now: datetime, weekday: int) -> str:
    days_ahead = weekday - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def _resolve_date_alias(val: str) -> str:
    """Expand TW date shortcuts to ISO 8601. Unknown strings pass through."""
    now = datetime.now(timezone.utc)
    aliases = {
        "today":     now.strftime("%Y-%m-%d"),
        "tomorrow":  (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "eow":       (now + timedelta(days=(6 - now.weekday()))).strftime("%Y-%m-%d"),
        "eom":       (now.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m-%d"),
        "monday":    _next_weekday(now, 0),
        "tuesday":   _next_weekday(now, 1),
        "wednesday": _next_weekday(now, 2),
        "thursday":  _next_weekday(now, 3),
        "friday":    _next_weekday(now, 4),
    }
    return aliases.get(val.lower(), val)


# ── Token classifier ──────────────────────────────────────────────────────────

_UUID_RE    = re.compile(r'^[0-9a-f]{8}(-[0-9a-f]{4}){0,3}', re.IGNORECASE)
_DATE_KEYS  = frozenset(["due", "scheduled", "wait", "until"])
_FIELD_KEYS = frozenset(["description", "status", "depends", "priority"])


def _is_uuid(tok: str) -> bool:
    return bool(_UUID_RE.match(tok))


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
                mods[key] = _resolve_date_alias(val)
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
        return commands.cmd_add(yaml_path, desc, tags=tags,
                                due=due, scheduled=scheduled)

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
    if filter_tokens:
        tasks = apply_filter(tasks, filter_tokens)
    pending = [t for t in tasks if t.status == "pending"]
    if not pending:
        return "No pending tasks."
    for t in pending:
        t.urgency_value = compute_urgency(t)
    pending.sort(key=lambda t: -t.urgency_value)

    lines = [f"{'UUID':>10}  {'Urg':>5}  Description"]
    lines.append("-" * 60)
    for t in pending:
        tag_str = " ".join(f"+{tg}" for tg in t.tags)
        due_str = f"  due:{t.due[:10]}" if t.due else ""
        active  = " ▶" if t.start else ""
        lines.append(
            f"{t.uuid[:8]:>10}  {t.urgency_value:>5.1f}  "
            f"{t.description[:34]:<34}  {tag_str}{due_str}{active}"
        )
    lines.append(f"\n{len(pending)} task(s)")
    return "\n".join(lines)


def _cmd_export_text(yaml_path: str, filter_tokens: list) -> str:
    """Return JSON string — used by terminal export commands."""
    data = commands.cmd_export(yaml_path, filter_tokens or None)
    return json.dumps(data, indent=2, default=str)
