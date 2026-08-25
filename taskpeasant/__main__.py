"""
python3 -m taskpeasant [--file FILE] [command tokens...]

Examples:
    python3 -m taskpeasant task add render the shot +urgent due:tomorrow
    python3 -m taskpeasant task
    python3 -m taskpeasant task 1 done
    python3 -m taskpeasant --file ~/projects/work.yaml task add something

Default YAML file: ./tasks.yaml or $TASKPEASANT_FILE env var.
"""

import argparse
import os
import shlex
import sys

from rich.console import Console
from rich.prompt import Confirm

from . import _rich as R
from ._dates import parse_date
from ._taskrc import Taskrc, extract_rc_overrides, load_taskrc
from .peasant_parser import execute_command, _resolve_id, _is_uuid, _split_bulk
from .query import FilterError, apply_filter
from .reports import _build_buckets, cmd_burndown
from .storage import read_tasks, assign_ids
from .urgency import compute_urgency

console = Console()

# Commands that produce rich table/panel output instead of plain text
_DISPLAY_VERBS = frozenset(["list", "next", "all", "info", "history", "ghistory",
                             "burndown", "burndown.daily", "calendar",
                             "completed", "waiting"])


def _rich_report(yaml_path: str, name: str, filter_tokens: list,
                 conf: Taskrc) -> None:
    """Render any engine report as a rich table."""
    from . import report_engine as RE
    from .query import FilterError as _FE

    try:
        built = RE.build_report(yaml_path, name, filter_tokens, conf)
    except FilterError as e:
        console.print(R.error(f"Filter error: {e}"))
        return
    if built is None:
        console.print(R.error(f"Unknown report '{name}'"))
        return
    report, headers, rows, tasks, specs = built
    if not rows:
        console.print("[dim]No matches.[/dim]")
        return
    console.print(R.render_report(headers, rows, specs, tasks, conf))
    n = len(tasks)
    console.print(f"\n[dim]{n} task{'s' if n != 1 else ''}[/dim]")


def _rich_info(yaml_path: str, uuid_prefix: str) -> None:
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    prefix = uuid_prefix.lower()
    matches = [t for t in tasks if t.uuid.lower().startswith(prefix)]
    if not matches:
        console.print(R.error(f"No task matching '{uuid_prefix}'"))
        return
    t = matches[0]
    t.urgency_value = compute_urgency(t)
    console.print(R.render_info(t))


def _rich_history(yaml_path: str) -> None:
    tasks = read_tasks(yaml_path)
    if not tasks:
        console.print("[dim]No tasks.[/dim]")
        return
    buckets = _build_buckets(tasks)
    if not buckets:
        console.print("[dim]No history data.[/dim]")
        return
    console.print(R.render_history(buckets))


def _rich_ghistory(yaml_path: str) -> None:
    tasks = read_tasks(yaml_path)
    if not tasks:
        console.print("[dim]No tasks.[/dim]")
        return
    buckets = _build_buckets(tasks)
    if not buckets:
        console.print("[dim]No history data.[/dim]")
        return
    console.print(R.render_ghistory(buckets))


def _rich_burndown(yaml_path: str) -> None:
    from .reports import burndown_series
    tasks = read_tasks(yaml_path)
    dates, series = burndown_series(tasks, "daily")
    console.print(R.render_burndown(series, dates))


def _rich_calendar(yaml_path: str) -> None:
    tasks = read_tasks(yaml_path)
    console.print(R.render_calendar(tasks))


_EDIT_FIELDS = ("description", "project", "priority", "status", "due",
                "scheduled", "wait", "tags", "depends")


def _cli_edit(yaml_path: str, uuid_prefix: str) -> None:
    """`task <id> edit` — round-trip one task through $EDITOR as YAML."""
    import subprocess
    import tempfile

    import yaml as _yaml

    from .storage import write_tasks
    from .undo import record_undo

    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    prefix = uuid_prefix.lower()
    matches = [t for t in tasks if t.uuid.lower().startswith(prefix)]
    if len(matches) != 1:
        console.print(R.error(f"No task matching '{uuid_prefix}'"))
        return
    t = matches[0]
    before = [t.to_dict()]

    editable = {k: getattr(t, k) for k in _EDIT_FIELDS}
    editable.update(t.udas)
    header = (f"# Editing task {t.uuid}\n"
              "# Save and quit to apply; empty a value to clear it.\n")
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                     encoding="utf-8") as f:
        f.write(header + _yaml.dump(editable, default_flow_style=False,
                                    sort_keys=False, allow_unicode=True))
        tmp = f.name

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    try:
        subprocess.call([editor, tmp])
        edited = _yaml.safe_load(open(tmp, encoding="utf-8").read())
    except Exception as e:
        console.print(R.error(f"Edit failed: {e}"))
        return
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    if not isinstance(edited, dict) or not str(
            edited.get("description", "")).strip():
        console.print(R.error("Edit aborted — description cannot be empty."))
        return

    for k in _EDIT_FIELDS:
        if k in ("tags", "depends"):
            v = edited.get(k) or []
            setattr(t, k, [str(x) for x in v] if isinstance(v, list)
                    else [s.strip() for s in str(v).split(",") if s.strip()])
        else:
            setattr(t, k, str(edited.get(k) or ""))
    known = set(_EDIT_FIELDS)
    t.udas = {k: v for k, v in edited.items()
              if k not in known and v not in (None, "")}
    from .commands import _now_iso
    t.modified = _now_iso()
    write_tasks(yaml_path, tasks)
    record_undo(yaml_path, "edit", before, [t.to_dict()])
    console.print(R.confirm(f"Edited task {t.uuid[:8]}  '{t.description}'"))


def main() -> None:
    try:
        _main()
    except FilterError as e:
        console.print(R.error(f"Filter error: {e}"))


def _main() -> None:
    # Config file is a CLI-only concern — the library path never reads it.
    from ._config import load_cli_config
    cfg = load_cli_config()

    parser = argparse.ArgumentParser(
        prog="tp",
        description="TaskPeasant — YAML-native task backend",
        add_help=True,
    )
    parser.add_argument(
        "--file", "-f",
        default=None,
        metavar="FILE",
        help="YAML file to use (default: ./tasks.yaml, $TASKPEASANT_FILE, "
             "or data.location from the config file)",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="skip confirmation prompts (bulk operations)",
    )
    parser.add_argument("command", nargs="*", help="task command tokens")
    args = parser.parse_args()

    tokens = args.command or []
    # Precedence: --file > $TASKPEASANT_FILE > config data.location > default
    yaml_path = (args.file
                 or os.environ.get("TASKPEASANT_FILE", "")
                 or cfg.data_location
                 or "tasks.yaml")

    # Urgency overrides go into the live WEIGHTS dict — the one knob the
    # frozen execute_command path (which mutations delegate to) can see.
    if cfg.urgency_overrides:
        from .urgency import WEIGHTS
        WEIGHTS.update(cfg.urgency_overrides)

    # Strip leading 'task' keyword
    if tokens and tokens[0].lower() == "task":
        tokens = tokens[1:]

    # Taskrc config: file layered under rc.key=value command-line overrides.
    # rc:<path> selects an alternate taskrc.
    tokens, rc_overrides = extract_rc_overrides(tokens)
    alt_rc = rc_overrides.pop("__taskrc_path__", "")
    conf = load_taskrc(alt_rc or None)
    conf.update(rc_overrides)

    # Opt-in recurrence: materialise children before any display command
    if conf.get_bool("recurrence"):
        from .recurrence import synthesize
        synthesize(yaml_path, conf)

    first = tokens[0] if tokens else ""

    # ── Plain-text commands (config, aggregates, helpers) ────────────────────
    _plain_cmds = {"show", "config", "context", "reports", "columns",
                   "colors", "summary", "stats",
                   "timesheet", "projects", "tags", "udas", "ids", "uuids",
                   "_ids", "_uuids", "_projects", "_tags", "_commands",
                   "_get", "count"}
    _graphical_bases = {"history", "ghistory", "burndown"}
    _base = first.partition(".")[0]
    if first in _plain_cmds or \
            (_base in _graphical_bases and "." in first) or \
            (first == "calendar" and len(tokens) > 1):
        raw = "task " + " ".join(shlex.quote(t) for t in tokens)
        console.print(execute_command(raw, yaml_path, config=conf),
                      highlight=False, markup=False)
        return

    # ── Display commands → rich renderers ────────────────────────────────────
    from .peasant_parser import _context_read_tokens
    report_names = set(conf.report_names())
    ctx = _context_read_tokens(conf)

    if not first:
        _rich_report(yaml_path, conf.get("default.command", "list"), ctx,
                     conf)
        return

    if first == "history":
        _rich_history(yaml_path)
        return

    if first == "ghistory":
        _rich_ghistory(yaml_path)
        return

    if first in ("burndown", "burndown.daily"):
        _rich_burndown(yaml_path)
        return

    if first == "calendar":
        _rich_calendar(yaml_path)
        return

    if first == "sync":
        console.print(
            "[bold yellow]sync[/bold yellow] is intentionally not implemented "
            "in taskpeasant.\n\n"
            "taskpeasant is local-first and never transfers data over a "
            "network. Suggested alternatives:\n"
            "  [dim]•[/dim] [cyan]git[/cyan]          — version-control your "
            "tasks.yaml and push/pull normally\n"
            "  [dim]•[/dim] [cyan]rsync / cp[/cyan]   — copy the YAML file "
            "to another machine manually\n"
            "  [dim]•[/dim] [cyan]network share[/cyan]— mount a shared drive "
            "and point [bold]--file[/bold] at the shared path"
        )
        return

    # ── Report engine: `task [filter] <report> [filter]` ─────────────────────
    for i, tok in enumerate(tokens):
        if tok in report_names:
            _rich_report(yaml_path, tok, ctx + tokens[:i] + tokens[i + 1:],
                         conf)
            return

    # ── Lifecycle commands routed straight through execute_command ───────────
    if first in ("undo", "log", "version") or \
            (first == "purge" and len(tokens) == 1):
        raw = "task " + " ".join(shlex.quote(t) for t in tokens)
        result = execute_command(raw, yaml_path, config=conf)
        if result.startswith("Error") or result.startswith("No "):
            console.print(R.error(result))
        else:
            console.print(R.confirm(result))
        return

    if first == "import":
        # tp import <file.json> — or JSON inline
        payload = " ".join(tokens[1:])
        if len(tokens) == 2 and os.path.isfile(tokens[1]):
            with open(tokens[1], encoding="utf-8") as f:
                payload = f.read()
        result = execute_command("task import " + payload, yaml_path,
                                 config=conf)
        console.print(R.error(result) if result.startswith("Error")
                      else R.confirm(result))
        return

    # ── UUID / integer-targeted: info → rich panel ────────────────────────────
    resolved_first = first
    if first.isdigit():
        uuid = _resolve_id(yaml_path, first)
        if uuid:
            resolved_first = uuid
        else:
            console.print(R.error(f"No task with ID {first}"))
            return

    if _is_uuid(resolved_first):
        verb = tokens[1].lower() if len(tokens) > 1 else "info"
        if verb == "info" or (len(tokens) == 1 and _is_uuid(resolved_first)):
            _rich_info(yaml_path, resolved_first)
            return
        if verb == "edit":
            _cli_edit(yaml_path, resolved_first)
            return

    # ── Default: implicit list with filter tokens (no verb match) ────────────
    # If none of the above matched, check if it looks like filter tokens
    # and route to rich list; otherwise fall through to plain execute_command
    # for mutation verbs (add, done, delete, start, stop, annotate, modify).
    mutation_verbs = frozenset(["add", "done", "delete", "start", "stop",
                                 "annotate", "modify", "export", "count",
                                 "duplicate", "purge", "append", "prepend",
                                 "denotate"])
    second = tokens[1].lower() if len(tokens) > 1 else ""

    # Bulk detection: a filter expression followed by a mutation verb.
    # Digit/UUID-first commands stay on the single-target path.
    bulk = None
    if first != "add" and not first.isdigit() and not _is_uuid(resolved_first):
        bulk = _split_bulk(tokens)

    # Config default project: only for `add`, only when none was given
    if (first == "add" and cfg.default_project
            and not any(t.startswith("project:") for t in tokens)):
        tokens = tokens + [f"project:{cfg.default_project}"]

    if first == "add" or bulk or (second in mutation_verbs) or (
            _is_uuid(resolved_first) and second in mutation_verbs):
        if bulk and not args.yes and sys.stdin.isatty():
            filter_tokens, verb, _rest = bulk
            tasks = read_tasks(yaml_path)
            assign_ids(yaml_path, tasks)
            count = len(apply_filter(tasks, filter_tokens))
            if count > 1 and not Confirm.ask(
                    f"This will {verb} {count} tasks. Proceed?"):
                console.print("[dim]Aborted.[/dim]")
                return
        # Mutation path — run through execute_command, pretty-print result
        raw = "task " + " ".join(shlex.quote(t) for t in tokens)
        result = execute_command(raw, yaml_path, config=conf)
        if result.startswith("Error") or result.startswith("No task") or result.startswith("Parse"):
            console.print(R.error(result))
        else:
            console.print(R.confirm(result))
        return

    # Fallback: treat as filter → default report
    _rich_report(yaml_path, conf.get("default.command", "list"),
                 ctx + tokens, conf)


if __name__ == "__main__":
    main()
