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
from ._taskrc import Taskrc, extract_rc_overrides, write_taskrc_value, \
    default_taskrc_write_path
from .query import apply_filter
from .reports import (cmd_burndown, cmd_calendar, cmd_ghistory, cmd_history,
                      cmd_projects, cmd_stats, cmd_summary, cmd_tags,
                      cmd_timesheet, cmd_udas)
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

# Verbs that may follow a filter expression: `task +urgent done`
_MUTATION_VERBS = frozenset(["done", "delete", "start", "stop",
                             "modify", "annotate"])


def _split_bulk(tokens: list):
    """Split `<filter...> <verb> <rest...>` at the first mutation verb.

    The verb must be an exact lowercase token at index >= 1 — a leading
    verb (`task done`) stays a description search, which guards against
    an accidental filterless "complete everything".  Returns
    (filter_tokens, verb, rest) or None.
    """
    for i, tok in enumerate(tokens):
        if i >= 1 and tok in _MUTATION_VERBS:
            return tokens[:i], tok, tokens[i + 1:]
    return None


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
                if val == "":
                    mods[key] = ""          # empty value clears the field (TW)
                else:
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

def execute_command(raw: str, yaml_path: str, config: Taskrc = None) -> str:
    """
    Parse a raw CLI string and dispatch to the correct command.
    Returns terminal output as a plain string.

    yaml_path must be the absolute path to a YAML file that TaskPeasant
    is allowed to read and write (it edits the `taskpeasant_tasks:` key).

    config (optional, added 0.4.0): a Taskrc instance carrying rc-style
    settings (report definitions, urgency coefficients, aliases, ...).
    When omitted, built-in defaults apply.  rc.key=value tokens in `raw`
    override it per-call; unknown keys are ignored, so hosts that send
    rc.* noise (the pre-0.4 "silently stripped" contract) keep working.
    """
    # Contract: this function returns a string and never raises
    # (docs/BACKWARDS_COMPAT.md §5), so trap everything.
    try:
        return _execute_command(raw, yaml_path, config)
    except Exception as e:
        return f"Error: {e}"


def _execute_command(raw: str, yaml_path: str, config: Taskrc = None) -> str:
    try:
        tokens = shlex.split(raw)
    except ValueError as e:
        return f"Parse error: {e}"

    if not tokens:
        return ""

    # Strip leading 'task' keyword (host terminals typically prepend it)
    if tokens and tokens[0].lower() == "task":
        tokens = tokens[1:]

    # rc.key=value / rc.key:value overrides — applied to a per-call copy
    # of the config (pre-0.4 these were stripped; honoring known keys is
    # a superset, unknown keys still have no effect).
    tokens, rc_overrides = extract_rc_overrides(tokens)
    rc_overrides.pop("__taskrc_path__", None)   # CLI-only concern
    conf = Taskrc(dict(config._values), config.source_path) if config \
        else Taskrc()
    conf.update(rc_overrides)

    if not tokens:
        from .report_engine import run_report
        default_report = conf.get("default.command", "list")
        if conf.get(f"report.{default_report}.columns"):
            return run_report(yaml_path, default_report, [], conf)
        return _cmd_list(yaml_path, [])

    first = tokens[0]

    # ── Pre-flight: catch invalid dates anywhere in the token stream ─────────
    _pre = _parse_mod_tokens(tokens)
    if "__date_error__" in _pre:
        return f"Error: '{_pre['__date_error__']}' is not a recognised date. Try: today, +3d, eom, monday, YYYY-MM-DD"

    # ── Configuration commands ───────────────────────────────────────────────
    if first == "show":
        return _cmd_show(conf, " ".join(tokens[1:]))
    if first == "config":
        return _cmd_config(conf, tokens[1:])
    if first == "reports":
        from .report_engine import list_reports
        return list_reports(conf)
    if first == "columns":
        from .report_engine import list_columns
        return list_columns()

    # ── Graphical / aggregate reports ─────────────────────────────────────────
    base, _, sub = first.partition(".")
    _hist_periods = {"": "monthly", "monthly": "monthly", "annual": "annual",
                     "daily": "daily", "weekly": "weekly"}
    if base == "history" and sub in _hist_periods:
        return cmd_history(_filtered_tasks(yaml_path, tokens[1:]),
                           _hist_periods[sub])
    if base == "ghistory" and sub in _hist_periods:
        return cmd_ghistory(_filtered_tasks(yaml_path, tokens[1:]),
                            _hist_periods[sub])
    if base == "burndown" and (sub or "daily") in ("daily", "weekly",
                                                   "monthly"):
        return cmd_burndown(_filtered_tasks(yaml_path, tokens[1:]),
                            sub or "daily")
    if first == "calendar":
        return cmd_calendar(read_tasks(yaml_path), tokens[1:], conf)
    if first == "summary":
        return cmd_summary(_filtered_tasks(yaml_path, tokens[1:]))
    if first == "stats":
        return cmd_stats(_filtered_tasks(yaml_path, tokens[1:]))
    if first == "timesheet":
        weeks = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() \
            else 4
        return cmd_timesheet(read_tasks(yaml_path), weeks)
    if first == "projects":
        return cmd_projects(_filtered_tasks(yaml_path, tokens[1:]))
    if first == "tags":
        return cmd_tags(_filtered_tasks(yaml_path, tokens[1:]))
    if first == "udas":
        return cmd_udas(read_tasks(yaml_path), conf)
    if first in ("ids", "uuids", "_ids", "_uuids", "_projects", "_tags",
                 "_commands"):
        return _cmd_helpers(yaml_path, first, tokens[1:], conf)
    if first == "_get":
        return _cmd_get(yaml_path, tokens[1:])
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

    # ── Report engine: `task [filter] <report> [filter]` ─────────────────────
    report_names = set(conf.report_names())
    for i, tok in enumerate(tokens):
        if tok in report_names:
            from .report_engine import run_report
            return run_report(yaml_path, tok,
                              tokens[:i] + tokens[i + 1:], conf)

    # ── Bulk: `<filter...> <verb>` — any filter may precede a mutation verb ──
    bulk = _split_bulk(tokens)
    if bulk:
        filter_tokens, verb, rest = bulk
        if verb in ("done", "delete", "start", "stop") and rest:
            return f"Error: unexpected arguments after '{verb}'"
        if verb == "annotate":
            note = " ".join(rest)
            if not note:
                return "Error: annotation text required"
            return commands.cmd_bulk(yaml_path, filter_tokens, verb, note=note)
        if verb == "modify":
            mods = _parse_mod_tokens(rest)
            if not mods:
                return "Nothing to modify."
            return commands.cmd_bulk(yaml_path, filter_tokens, verb, mods=mods)
        return commands.cmd_bulk(yaml_path, filter_tokens, verb)

    # ── 'export' or implicit list with filter tokens ──────────────────────────
    filter_tokens = [t for t in tokens if t != "export"]
    if "export" in tokens:
        return _cmd_export_text(yaml_path, filter_tokens)

    # ── Default: implicit list via the report engine (default.command) ───────
    from .report_engine import run_report
    default_report = conf.get("default.command", "list")
    if default_report in report_names:
        return run_report(yaml_path, default_report, filter_tokens, conf)
    return _cmd_list(yaml_path, filter_tokens)


# ── Filter / helper commands ──────────────────────────────────────────────────

def _filtered_tasks(yaml_path: str, filter_tokens: list) -> list:
    """Read + assign ids/vtags + apply an optional filter."""
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    if filter_tokens:
        return apply_filter(tasks, filter_tokens, all_tasks=tasks)
    return tasks


def _compact_id_ranges(ids: list) -> str:
    """[1,2,3,5] → '1-3 5' (TW `task ids` output form)."""
    if not ids:
        return ""
    ids = sorted(set(ids))
    parts, run_start, prev = [], ids[0], ids[0]
    for i in ids[1:]:
        if i == prev + 1:
            prev = i
            continue
        parts.append(f"{run_start}-{prev}" if prev > run_start
                     else str(run_start))
        run_start = prev = i
    parts.append(f"{run_start}-{prev}" if prev > run_start
                 else str(run_start))
    return " ".join(parts)


def _cmd_helpers(yaml_path: str, cmd: str, filter_tokens: list, conf) -> str:
    """ids / uuids / _ids / _uuids / _projects / _tags / _commands."""
    if cmd == "_commands":
        names = sorted(set(conf.report_names()) | {
            "add", "annotate", "append", "burndown", "calendar", "columns",
            "config", "count", "delete", "denotate", "done", "duplicate",
            "edit", "export", "ghistory", "history", "ids", "import", "info",
            "log", "modify", "prepend", "projects", "purge", "reports",
            "show", "start", "stats", "stop", "summary", "tags", "timesheet",
            "udas", "undo", "uuids", "version"})
        return "\n".join(names)

    tasks = _filtered_tasks(yaml_path, filter_tokens)
    if cmd == "ids":
        return _compact_id_ranges([t.id for t in tasks if t.id])
    if cmd == "_ids":
        return "\n".join(str(t.id) for t in tasks if t.id)
    if cmd == "uuids":
        return " ".join(t.uuid for t in tasks)
    if cmd == "_uuids":
        return "\n".join(t.uuid for t in tasks)
    if cmd == "_projects":
        return "\n".join(sorted({t.project for t in tasks if t.project}))
    if cmd == "_tags":
        return "\n".join(sorted({tag for t in tasks for tag in t.tags}))
    return ""


def _cmd_get(yaml_path: str, args: list) -> str:
    """`task _get <id|uuid>.<attribute>` — minimal DOM support."""
    if not args or "." not in args[0]:
        return ""
    ref, _, attr = args[0].partition(".")
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    task = None
    if ref.isdigit():
        task = next((t for t in tasks if t.id == int(ref)), None)
    else:
        matches = [t for t in tasks if t.uuid.lower().startswith(ref.lower())]
        task = matches[0] if len(matches) == 1 else None
    if task is None:
        return ""
    from .query import _attr_str
    if attr == "urgency":
        return str(compute_urgency(task))
    return _attr_str(task, attr)


# ── Configuration commands ────────────────────────────────────────────────────

def _cmd_show(conf: Taskrc, pattern: str) -> str:
    """`task show [pattern]` — effective configuration, TW-style."""
    pattern = pattern.strip().lower()
    rows = [(k, v) for k, v in conf.items()
            if not pattern or pattern in k.lower()]
    if not rows:
        return f"No configuration settings match '{pattern}'"

    width = max(len(k) for k, _ in rows)
    lines = [f"{'Config Variable':<{width}}  Value", "-" * (width + 30)]
    modified = 0
    for k, v in rows:
        marker = ""
        if not conf.is_default(k):
            marker = " *"
            modified += 1
        lines.append(f"{k:<{width}}  {v}{marker}")
    lines.append("")
    lines.append(f"{len(rows)} settings shown"
                 + (f", {modified} changed from default (*)" if modified else "")
                 + (f".  Config read from {conf.source_path}"
                    if conf.source_path else "."))
    return "\n".join(lines)


def _cmd_config(conf: Taskrc, args: list) -> str:
    """`task config <key> [value]` — set/unset a taskrc value.

    Writes to the loaded taskrc when one exists; falls back to the
    default XDG path so first-time `task config` bootstraps a file.
    """
    if not args:
        return "Specify the name of a config variable to modify."
    key = args[0]
    value = " ".join(args[1:]) if len(args) > 1 else None
    path = conf.source_path or default_taskrc_write_path()
    return write_taskrc_value(path, key, value)


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
