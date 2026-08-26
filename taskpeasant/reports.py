"""
taskpeasant/reports.py
Graphical / aggregate reports — a port of Taskwarrior's:

  history.daily|weekly|monthly|annual     tabular add/done/delete counts
  ghistory.daily|weekly|monthly|annual    bar-chart variant
  burndown.daily|weekly|monthly           stacked pending/started/done chart
  calendar [due | <year> | <month> <year>]
  summary                                 per-project completion bars
  stats                                   database statistics
  timesheet [weeks]                       completed/started by week
  projects / tags / udas                  aggregate listings
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from ._taskrc import Taskrc

from ._dates import parse_date
from .task_model import Task

_PERIODS = ("daily", "weekly", "monthly", "annual")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _month_key(dt: datetime) -> tuple:
    return (dt.year, dt.month)


def _period_key(dt: datetime, period: str) -> tuple:
    if period == "daily":
        return (dt.year, dt.month, dt.day)
    if period == "weekly":
        iso = dt.isocalendar()
        return (iso[0], iso[1])
    if period == "annual":
        return (dt.year,)
    return (dt.year, dt.month)


def _period_label(key: tuple, period: str) -> tuple:
    """(group_label, sub_label) e.g. ('2026', 'July')."""
    if period == "daily":
        return (f"{key[0]}-{key[1]:02d}", f"{key[2]:02d}")
    if period == "weekly":
        return (str(key[0]), f"W{key[1]:02d}")
    if period == "annual":
        return (str(key[0]), "")
    return (str(key[0]), calendar.month_name[key[1]])


def _build_period_buckets(tasks: List[Task], period: str) -> dict:
    """Bucket tasks by period into added/completed/deleted counts."""
    buckets: dict = defaultdict(
        lambda: {"added": 0, "completed": 0, "deleted": 0})
    for t in tasks:
        entry_dt = parse_date(t.entry)
        if entry_dt:
            buckets[_period_key(entry_dt, period)]["added"] += 1
        if t.end:
            end_dt = parse_date(t.end)
            if end_dt and t.status in ("completed", "deleted"):
                buckets[_period_key(end_dt, period)][t.status] += 1
    return buckets


def _build_buckets(tasks: List[Task]) -> dict:
    """Monthly buckets — kept for the CLI rich renderers."""
    return _build_period_buckets(tasks, "monthly")


# ── history ───────────────────────────────────────────────────────────────────

_PERIOD_HEADINGS = {"daily": ("Month", "Day"), "weekly": ("Year", "Week"),
                    "monthly": ("Year", "Month"), "annual": ("Year", "")}


def cmd_history(tasks: List[Task], period: str = "monthly") -> str:
    """Tabular history: Added / Completed / Deleted / Net per period."""
    if not tasks:
        return "No tasks."
    buckets = _build_period_buckets(tasks, period)
    if not buckets:
        return "No history data."

    g_head, s_head = _PERIOD_HEADINGS[period]
    lines = [f"{g_head:<8} {s_head:<10} {'Added':>6} {'Completed':>10} "
             f"{'Deleted':>8} {'Net':>5}"]
    lines.append("-" * 52)
    total = {"added": 0, "completed": 0, "deleted": 0}
    prev_group = None

    for key in sorted(buckets):
        b = buckets[key]
        net = b["added"] - b["completed"] - b["deleted"]
        group, sub = _period_label(key, period)
        group_str = group if group != prev_group else ""
        prev_group = group
        lines.append(
            f"{group_str:<8} {sub:<10} {b['added']:>6} "
            f"{b['completed']:>10} {b['deleted']:>8} {net:>5}"
        )
        for k in total:
            total[k] += b[k]

    n = len(buckets)
    lines.append("-" * 52)
    lines.append(
        f"{'':8} {'Average':<10} {total['added'] // n:>6} "
        f"{total['completed'] // n:>10} {total['deleted'] // n:>8} "
        f"{(total['added'] - total['completed'] - total['deleted']) // n:>5}"
    )
    return "\n".join(lines)


# ── ghistory ──────────────────────────────────────────────────────────────────

def cmd_ghistory(tasks: List[Task], period: str = "monthly") -> str:
    """Graphical history using +/X/- bars."""
    if not tasks:
        return "No tasks."
    buckets = _build_period_buckets(tasks, period)
    if not buckets:
        return "No history data."

    bar_width = 54
    max_val = max(b["added"] + b["completed"] + b["deleted"]
                  for b in buckets.values()) or 1
    g_head, s_head = _PERIOD_HEADINGS[period]
    lines = [f"{g_head:<8} {s_head:<6} "
             f"{'Number Added/Completed/Deleted':<{bar_width}}"]
    prev_group = None

    for key in sorted(buckets):
        b = buckets[key]
        group, sub = _period_label(key, period)
        group_str = group if group != prev_group else ""
        prev_group = group
        scale = bar_width / max_val
        bar = ("+" * round(b["added"] * scale) +
               "X" * round(b["completed"] * scale) +
               "-" * round(b["deleted"] * scale))
        lines.append(f"{group_str:<8} {sub[:6]:<6} {bar}")

    lines.append("\nLegend: + Added, X Completed, - Deleted")
    return "\n".join(lines)


# ── burndown ──────────────────────────────────────────────────────────────────

_BURNDOWN_SPANS = {"daily": (30, timedelta(days=1), "%d", "%b"),
                   "weekly": (26, timedelta(weeks=1), "%d", "%b"),
                   "monthly": (24, None, "%m", "%Y")}


def burndown_series(tasks: List[Task], period: str = "daily") -> Tuple[List, List[Tuple[int, int, int]]]:
    """(dates, [(pending, started, done)]) snapshots for the chart."""
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                             microsecond=0)
    count, step, _, _ = _BURNDOWN_SPANS[period]
    if step is not None:
        dates = [now - step * i for i in range(count - 1, -1, -1)]
    else:                                       # monthly
        dates = []
        y, m = now.year, now.month
        for _ in range(count):
            dates.append(datetime(y, m, 1, tzinfo=timezone.utc))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        dates.reverse()

    def snapshot(day: datetime):
        day_end = day + (step or timedelta(days=31))
        pending = started = done = 0
        for t in tasks:
            entry_dt = parse_date(t.entry)
            if not entry_dt or entry_dt >= day_end:
                continue
            end_dt = parse_date(t.end) if t.end else None
            if end_dt and end_dt < day_end:
                if t.status == "completed":
                    done += 1
            elif t.start and (parse_date(t.start) or day_end) < day_end:
                started += 1
            else:
                pending += 1
        return pending, started, done

    return dates, [snapshot(d) for d in dates]


def cmd_burndown(tasks: List[Task], period: str = "daily") -> str:
    """Stacked burndown chart: done (.), started (o), pending (X)."""
    dates, series = burndown_series(tasks, period)
    max_count = max((p + s + d for p, s, d in series), default=1) or 1
    height = 15
    y_step = max_count / height

    def band(value: float, threshold: float) -> bool:
        return value >= threshold if threshold > 0 else value > 0

    chart_rows = []
    for row in range(height, -1, -1):
        threshold = row * y_step
        y_label = f"{round(threshold):>3} |" if row % (height // 3) == 0 \
            else "    |"
        cells = []
        for (pending, started, done) in series:
            if band(done, threshold):
                cells.append(".")
            elif band(done + started, threshold):
                cells.append("o")
            elif band(done + started + pending, threshold):
                cells.append("X")
            else:
                cells.append(" ")
        chart_rows.append(y_label + "".join(f"{c}  " for c in cells).rstrip())

    _, _, tick_fmt, group_fmt = _BURNDOWN_SPANS[period]
    width = len(dates)
    title = {"daily": "Daily", "weekly": "Weekly",
             "monthly": "Monthly"}[period]
    header = f"{title + ' Burndown':^{width * 3 + 6}}"
    day_labels = "    +" + "-" * (width * 3 - 1)
    date_row = "     " + "".join(f"{d.strftime(tick_fmt):<3}" for d in dates)

    lines = [header, ""] + chart_rows + [day_labels, date_row]
    lines.append("\n   . Done   o Started   X Pending")

    # Trend: net change in open tasks per bucket → estimated completion
    open_counts = [p + s for p, s, _ in series]
    if len(open_counts) >= 2:
        rate = (open_counts[0] - open_counts[-1]) / max(len(open_counts) - 1, 1)
        unit = {"daily": "d", "weekly": "w", "monthly": "mo"}[period]
        lines.append(f"\nNet Fix Rate: {rate:+.1f}/{unit}")
        if rate > 0 and open_counts[-1] > 0:
            buckets_left = open_counts[-1] / rate
            step = _BURNDOWN_SPANS[period][1] or timedelta(days=30)
            eta = datetime.now(timezone.utc) + step * buckets_left
            lines.append(f"Estimated completion: {eta.strftime('%Y-%m-%d')}")

    return "\n".join(lines)


# ── calendar ──────────────────────────────────────────────────────────────────

def _months_for_calendar(tasks: List[Task], args: List[str]) -> List[Tuple[int, int]]:
    """Resolve `task calendar [due | <year> | <month> <year>]` args to a
    list of (year, month) pairs."""
    now = datetime.now(timezone.utc)

    if args and args[0].lower() == "due":
        due_dates = sorted(parse_date(t.due) for t in tasks
                           if t.due and t.status == "pending"
                           and parse_date(t.due))
        due_dates = [d for d in due_dates
                     if d >= now.replace(hour=0, minute=0, second=0,
                                         microsecond=0)]
        if not due_dates:
            return [(now.year, now.month)]
        first, last = due_dates[0], due_dates[-1]
        months, y, m = [], first.year, first.month
        while (y, m) <= (last.year, last.month) and len(months) < 12:
            months.append((y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return months

    if len(args) == 1 and args[0].isdigit() and len(args[0]) == 4:
        year = int(args[0])
        return [(year, m) for m in range(1, 13)]

    if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        return [(int(args[1]), int(args[0]))]

    months, y, m = [], now.year, now.month
    for _ in range(3):
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def cmd_calendar(tasks: List[Task], args: Optional[List[str]] = None,
                 conf: Optional["Taskrc"] = None) -> str:
    """Month-grid calendar with a due-task legend (calendar.details)."""
    now = datetime.now(timezone.utc)
    today = now.date()
    monday_first = bool(conf) and \
        conf.get("weekstart", "sunday").lower() == "monday"

    due_map: dict = defaultdict(list)
    for t in tasks:
        if t.due and t.status == "pending":
            dt = parse_date(t.due)
            if dt:
                due_map[dt.date()].append(t)

    cal = calendar.Calendar(firstweekday=0 if monday_first else 6)
    day_header = "Mo Tu We Th Fr Sa Su" if monday_first \
        else "Su Mo Tu We Th Fr Sa"

    def render_month(year: int, month: int) -> list:
        header = f"{calendar.month_name[month]} {year}".center(20)
        rows = [header, day_header]
        for week in cal.monthdayscalendar(year, month):
            cells = []
            for day in week:
                cells.append("  " if day == 0 else f"{day:2d}")
            rows.append(" ".join(cells))
        while len(rows) < 8:
            rows.append("")
        return rows

    month_list = _months_for_calendar(tasks, list(args or []))
    blocks = [render_month(y, m) for (y, m) in month_list]

    lines: List[str] = []
    for row_start in range(0, len(blocks), 3):
        chunk = blocks[row_start:row_start + 3]
        max_rows = max(len(b) for b in chunk)
        for b in chunk:
            while len(b) < max_rows:
                b.append("")
        lines.extend("   ".join(f"{b[i]:<20}" for b in chunk).rstrip()
                     for i in range(max_rows))

    details = conf.get("calendar.details", "sparse") if conf else "sparse"
    if details != "none":
        shown_months = set(month_list)
        upcoming = sorted(d for d in due_map
                          if (d.year, d.month) in shown_months
                          and d >= today)
        if upcoming:
            lines.append("")
            lines.append("Due this period:")
            for d in upcoming[:20]:
                for t in due_map[d]:
                    lines.append(f"  {d.strftime('%Y-%m-%d')}  "
                                 f"{t.description}")

    return "\n".join(lines)


# ── summary ───────────────────────────────────────────────────────────────────

def cmd_summary(tasks: List[Task]) -> str:
    """Per-project progress: remaining, avg age, % complete, bar."""
    now = datetime.now(timezone.utc)
    groups: dict = defaultdict(lambda: {"pending": 0, "done": 0, "ages": []})
    for t in tasks:
        if t.status == "deleted":
            continue
        name = t.project or "(none)"
        g = groups[name]
        if t.status == "completed":
            g["done"] += 1
        else:
            g["pending"] += 1
            entry_dt = parse_date(t.entry)
            if entry_dt:
                g["ages"].append((now - entry_dt).total_seconds())

    if not groups:
        return "No projects."

    from .report_engine import format_duration_compact
    bar_width = 24
    name_w = max(len("Project"), max(len(n) for n in groups))
    lines = [f"{'Project':<{name_w}} {'Remaining':>9} {'Avg age':>8} "
             f"{'Complete':>9} {'0%':<{bar_width - 2}}100%"]
    lines.append("-" * (name_w + 34 + bar_width))

    for name in sorted(groups):
        g = groups[name]
        total = g["pending"] + g["done"]
        pct = g["done"] / total if total else 0.0
        avg_age = format_duration_compact(
            sum(g["ages"]) / len(g["ages"])) if g["ages"] else ""
        filled = round(pct * bar_width)
        bar = "=" * filled + " " * (bar_width - filled)
        lines.append(f"{name:<{name_w}} {g['pending']:>9} {avg_age:>8} "
                     f"{round(pct * 100):>8}% {bar}")

    n = len(groups)
    lines.append("")
    lines.append(f"{n} project{'s' if n != 1 else ''}")
    return "\n".join(lines)


# ── stats ─────────────────────────────────────────────────────────────────────

def cmd_stats(tasks: List[Task]) -> str:
    """Database statistics — a port of `task stats`."""
    from .report_engine import format_duration_compact

    now = datetime.now(timezone.utc)
    by_status = defaultdict(int)
    for t in tasks:
        by_status[t.status] += 1

    annotations = sum(len(t.annotations) for t in tasks)
    tags = {tag for t in tasks for tag in t.tags}
    projects = {t.project for t in tasks if t.project}
    tagged = sum(1 for t in tasks if t.tags)
    blocked = sum(1 for t in tasks if "BLOCKED" in t.virtual_tags)
    blocking = sum(1 for t in tasks if "BLOCKING" in t.virtual_tags)

    entries = sorted(parse_date(t.entry) for t in tasks
                     if t.entry and parse_date(t.entry))
    rows = [
        ("Pending", by_status["pending"]),
        ("Waiting", by_status["waiting"]),
        ("Recurring", by_status["recurring"]),
        ("Completed", by_status["completed"]),
        ("Deleted", by_status["deleted"]),
        ("Total", len(tasks)),
        ("Annotations", annotations),
        ("Unique tags", len(tags)),
        ("Projects", len(projects)),
        ("Blocked tasks", blocked),
        ("Blocking tasks", blocking),
        ("Tagged tasks", tagged),
    ]
    if entries:
        rows.append(("Oldest task", entries[0].strftime("%Y-%m-%d")))
        rows.append(("Newest task", entries[-1].strftime("%Y-%m-%d")))
        span = (now - entries[0]).total_seconds()
        rows.append(("Task used for", format_duration_compact(span)))
        if len(entries) > 1:
            rows.append(("Task added every",
                         format_duration_compact(span / (len(entries) - 1))))
        done_count = by_status["completed"]
        if done_count:
            rows.append(("Task completed every",
                         format_duration_compact(span / done_count)))
    if tasks:
        avg_len = sum(len(t.description) for t in tasks) / len(tasks)
        rows.append(("Average desc length", f"{avg_len:.0f} characters"))

    width = max(len(label) for label, _ in rows)
    lines = [f"{'Category':<{width}}  Data", "-" * (width + 20)]
    for label, value in rows:
        lines.append(f"{label:<{width}}  {value}")
    return "\n".join(lines)


# ── timesheet ─────────────────────────────────────────────────────────────────

def cmd_timesheet(tasks: List[Task], weeks: int = 4) -> str:
    """Completed and started tasks grouped by week, most recent first."""
    now = datetime.now(timezone.utc)
    sow = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)

    lines: List[str] = []
    total = 0
    for w in range(weeks):
        week_start = sow - timedelta(weeks=w)
        week_end = week_start + timedelta(weeks=1)

        completed = [t for t in tasks if t.status == "completed" and t.end
                     and parse_date(t.end)
                     and week_start <= parse_date(t.end) < week_end]
        started = [t for t in tasks
                   if t.status in ("pending", "waiting") and t.start
                   and parse_date(t.start)
                   and week_start <= parse_date(t.start) < week_end]
        if not completed and not started and w > 0:
            continue

        lines.append(f"Week starting {week_start.strftime('%Y-%m-%d')}")
        if completed:
            lines.append("  Completed:")
            for t in sorted(completed, key=lambda x: x.end):
                proj = f" [{t.project}]" if t.project else ""
                lines.append(f"    {t.end[:10]}  {t.description}{proj}")
        if started:
            lines.append("  Started:")
            for t in sorted(started, key=lambda x: x.start):
                proj = f" [{t.project}]" if t.project else ""
                lines.append(f"    {t.start[:10]}  {t.description}{proj}")
        if not completed and not started:
            lines.append("  (no activity)")
        lines.append("")
        total += len(completed) + len(started)

    lines.append(f"{total} task{'s' if total != 1 else ''} shown")
    return "\n".join(lines)


# ── projects / tags / udas ────────────────────────────────────────────────────

def cmd_projects(tasks: List[Task]) -> str:
    """Pending-task counts per project (TW `task projects`)."""
    counts: dict = defaultdict(int)
    for t in tasks:
        if t.status in ("pending", "waiting"):
            counts[t.project or "(none)"] += 1
    if not counts:
        return "No projects."
    width = max(len("Project"), max(len(p) for p in counts))
    lines = [f"{'Project':<{width}}  Tasks", "-" * (width + 7)]
    for name in sorted(counts):
        lines.append(f"{name:<{width}} {counts[name]:>6}")
    n = len(counts)
    lines.append("")
    lines.append(f"{n} project{'s' if n != 1 else ''}")
    return "\n".join(lines)


def cmd_tags(tasks: List[Task]) -> str:
    """Tag usage counts across open tasks (TW `task tags`)."""
    counts: dict = defaultdict(int)
    for t in tasks:
        if t.status in ("pending", "waiting"):
            for tag in t.tags:
                counts[tag] += 1
    if not counts:
        return "No tags."
    width = max(len("Tag"), max(len(tag) for tag in counts))
    lines = [f"{'Tag':<{width}}  Count", "-" * (width + 7)]
    for tag in sorted(counts):
        lines.append(f"{tag:<{width}} {counts[tag]:>6}")
    n = len(counts)
    lines.append("")
    lines.append(f"{n} tag{'s' if n != 1 else ''}")
    return "\n".join(lines)


def cmd_udas(tasks: List[Task], conf: Optional["Taskrc"] = None) -> str:
    """UDAs: config-defined (uda.<name>.*) plus orphans found in tasks."""
    defined: dict = {}
    if conf is not None:
        for key, val in conf.subtree("uda.").items():
            name, _, prop = key.partition(".")
            if prop:
                defined.setdefault(name, {})[prop] = val

    seen: dict = defaultdict(int)
    for t in tasks:
        for k in t.udas:
            seen[k] += 1

    names = sorted(set(defined) | set(seen))
    if not names:
        return "No UDAs defined."
    width = max(len("Name"), max(len(n) for n in names))
    lines = [f"{'Name':<{width}}  {'Type':<8} {'Label':<12} Usage",
             "-" * (width + 32)]
    for n in names:
        d = defined.get(n, {})
        lines.append(f"{n:<{width}}  {d.get('type', 'string'):<8} "
                     f"{d.get('label', n):<12} {seen.get(n, 0)}")
    k = len(names)
    lines.append("")
    lines.append(f"{k} UDA{'s' if k != 1 else ''}")
    return "\n".join(lines)
