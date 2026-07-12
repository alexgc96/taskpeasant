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


def _rich_list(yaml_path: str, filter_tokens: list) -> None:
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    if filter_tokens:
        tasks = apply_filter(tasks, filter_tokens)
    pending = [t for t in tasks if t.status == "pending"]
    if not pending:
        console.print("[dim]No pending tasks.[/dim]")
        return
    for t in pending:
        t.urgency_value = compute_urgency(t)
    pending.sort(key=lambda t: -t.urgency_value)
    console.print(R.render_list(pending))
    console.print(f"\n[dim]{len(pending)} task(s)[/dim]")


def _rich_next(yaml_path: str, filter_tokens: list) -> None:
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    pending = [t for t in tasks if t.status == "pending"]
    if filter_tokens:
        pending = apply_filter(pending, filter_tokens, all_tasks=tasks)
    if not pending:
        console.print("[dim]No pending tasks.[/dim]")
        return
    for t in pending:
        t.urgency_value = compute_urgency(t)
    pending.sort(key=lambda t: -t.urgency_value)
    pending = pending[:25]
    console.print(R.render_list(pending))
    console.print(f"\n[dim]{len(pending)} task(s)[/dim]")


def _rich_all(yaml_path: str, filter_tokens: list) -> None:
    tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, tasks)
    if filter_tokens:
        tasks = apply_filter(tasks, filter_tokens)
    if not tasks:
        console.print("[dim]No tasks.[/dim]")
        return
    for t in tasks:
        t.urgency_value = compute_urgency(t)
    tasks.sort(key=lambda t: (t.status != "pending", -t.urgency_value))
    console.print(R.render_list(tasks, show_status=True))
    console.print(f"\n[dim]{len(tasks)} task(s)[/dim]")


def _rich_completed(yaml_path: str) -> None:
    tasks = read_tasks(yaml_path)
    done = [t for t in tasks if t.status == "completed"]
    if not done:
        console.print("[dim]No completed tasks.[/dim]")
        return
    done.sort(key=lambda t: t.end or t.modified, reverse=True)
    for t in done:
        t.urgency_value = 0.0
    console.print(R.render_list(done, show_status=True))
    console.print(f"\n[dim]{len(done)} task(s)[/dim]")


def _rich_waiting(yaml_path: str) -> None:
    tasks = read_tasks(yaml_path)
    waiting = [t for t in tasks if t.status == "waiting"]
    if not waiting:
        console.print("[dim]No waiting tasks.[/dim]")
        return
    waiting.sort(key=lambda t: t.wait or "")
    for t in waiting:
        t.urgency_value = compute_urgency(t)
    console.print(R.render_list(waiting, show_status=True))
    console.print(f"\n[dim]{len(waiting)} task(s)[/dim]")


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
    from datetime import datetime, timedelta, timezone
    tasks = read_tasks(yaml_path)
    days  = 30
    now   = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    dates = [now - timedelta(days=i) for i in range(days - 1, -1, -1)]

    def snapshot(day):
        from datetime import timedelta as td
        day_end = day + td(days=1)
        pending = done = 0
        for t in tasks:
            entry_dt = parse_date(t.entry)
            if not entry_dt or entry_dt >= day_end:
                continue
            end_dt = parse_date(t.end) if t.end else None
            if end_dt and end_dt < day_end and t.status == "completed":
                done += 1
            else:
                pending += 1
        return pending, done

    daily = [snapshot(d) for d in dates]
    console.print(R.render_burndown(daily, dates))


def _rich_calendar(yaml_path: str) -> None:
    tasks = read_tasks(yaml_path)
    console.print(R.render_calendar(tasks))


def main() -> None:
    try:
        _main()
    except FilterError as e:
        console.print(R.error(f"Filter error: {e}"))


def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="tp",
        description="TaskPeasant — YAML-native task backend",
        add_help=True,
    )
    parser.add_argument(
        "--file", "-f",
        default=os.environ.get("TASKPEASANT_FILE", "tasks.yaml"),
        metavar="FILE",
        help="YAML file to use (default: ./tasks.yaml or $TASKPEASANT_FILE)",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="skip confirmation prompts (bulk operations)",
    )
    parser.add_argument("command", nargs="*", help="task command tokens")
    args = parser.parse_args()

    tokens = args.command or []
    yaml_path = args.file

    # Strip leading 'task' keyword
    if tokens and tokens[0].lower() == "task":
        tokens = tokens[1:]
    # Strip rc.* flags
    tokens = [t for t in tokens if not t.startswith("rc.")]

    first = tokens[0] if tokens else ""

    # ── Display commands → rich renderers ────────────────────────────────────
    if not first or first == "list":
        _rich_list(yaml_path, tokens[1:] if first == "list" else tokens)
        return

    if first == "next":
        _rich_next(yaml_path, tokens[1:])
        return

    if first == "all":
        _rich_all(yaml_path, tokens[1:])
        return

    if first == "completed":
        _rich_completed(yaml_path)
        return

    if first == "waiting":
        _rich_waiting(yaml_path)
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

    # ── Default: implicit list with filter tokens (no verb match) ────────────
    # If none of the above matched, check if it looks like filter tokens
    # and route to rich list; otherwise fall through to plain execute_command
    # for mutation verbs (add, done, delete, start, stop, annotate, modify).
    mutation_verbs = frozenset(["add", "done", "delete", "start", "stop",
                                 "annotate", "modify", "export", "count"])
    second = tokens[1].lower() if len(tokens) > 1 else ""

    # Bulk detection: a filter expression followed by a mutation verb.
    # Digit/UUID-first commands stay on the single-target path.
    bulk = None
    if first != "add" and not first.isdigit() and not _is_uuid(resolved_first):
        bulk = _split_bulk(tokens)

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
        result = execute_command(raw, yaml_path)
        if result.startswith("Error") or result.startswith("No task") or result.startswith("Parse"):
            console.print(R.error(result))
        else:
            console.print(R.confirm(result))
        return

    # Fallback: treat as filter → rich list
    _rich_list(yaml_path, tokens)


if __name__ == "__main__":
    main()
