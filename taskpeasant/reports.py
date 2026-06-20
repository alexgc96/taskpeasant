"""
taskpeasant/reports.py
Terminal reports — history, ghistory, burndown, calendar.
Mirrors the output style of the equivalent Taskwarrior reports.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List

from ._dates import parse_date
from .task_model import Task


# ── Shared helpers ────────────────────────────────────────────────────────────

def _month_key(dt: datetime) -> tuple:
    return (dt.year, dt.month)


def _build_buckets(tasks: List[Task]) -> dict:
    """Bucket tasks by month into added/completed/deleted counts."""
    buckets: dict = defaultdict(lambda: {"added": 0, "completed": 0, "deleted": 0})
    for t in tasks:
        entry_dt = parse_date(t.entry)
        if entry_dt:
            buckets[_month_key(entry_dt)]["added"] += 1
        if t.end:
            end_dt = parse_date(t.end)
            if end_dt:
                key = "completed" if t.status == "completed" else "deleted" if t.status == "deleted" else None
                if key:
                    buckets[_month_key(end_dt)][key] += 1
    return buckets


# ── history ───────────────────────────────────────────────────────────────────

def cmd_history(tasks: List[Task]) -> str:
    """Tabular monthly history: Added / Completed / Deleted / Net."""
    if not tasks:
        return "No tasks."
    buckets = _build_buckets(tasks)
    if not buckets:
        return "No history data."

    lines     = [f"{'Year':<6} {'Month':<10} {'Added':>6} {'Completed':>10} {'Deleted':>8} {'Net':>5}"]
    lines.append("-" * 50)
    total     = {"added": 0, "completed": 0, "deleted": 0}
    prev_year = None

    for (year, month) in sorted(buckets):
        b         = buckets[(year, month)]
        net       = b["added"] - b["completed"] - b["deleted"]
        year_str  = str(year) if year != prev_year else ""
        prev_year = year
        lines.append(
            f"{year_str:<6} {calendar.month_name[month]:<10} {b['added']:>6} "
            f"{b['completed']:>10} {b['deleted']:>8} {net:>5}"
        )
        for k in total:
            total[k] += b[k]

    n = len(buckets)
    lines.append("-" * 50)
    lines.append(
        f"{'':6} {'Average':<10} {total['added']//n:>6} "
        f"{total['completed']//n:>10} {total['deleted']//n:>8} "
        f"{(total['added']-total['completed']-total['deleted'])//n:>5}"
    )
    return "\n".join(lines)


# ── ghistory ──────────────────────────────────────────────────────────────────

def cmd_ghistory(tasks: List[Task]) -> str:
    """Graphical monthly history using +/X/- bars."""
    if not tasks:
        return "No tasks."
    buckets = _build_buckets(tasks)
    if not buckets:
        return "No history data."

    bar_width = 54
    max_val   = max(b["added"] + b["completed"] + b["deleted"] for b in buckets.values()) or 1
    lines     = [f"{'Year':<6} {'Month':<6} {'Number Added/Completed/Deleted':<{bar_width}}"]
    prev_year = None

    for (year, month) in sorted(buckets):
        b         = buckets[(year, month)]
        year_str  = str(year) if year != prev_year else ""
        prev_year = year
        scale     = bar_width / max_val
        bar       = ("+" * round(b["added"]     * scale) +
                     "X" * round(b["completed"] * scale) +
                     "-" * round(b["deleted"]   * scale))
        lines.append(f"{year_str:<6} {calendar.month_name[month][:3]:<6} {bar}")

    lines.append("\nLegend: + Added, X Completed, - Deleted")
    return "\n".join(lines)


# ── burndown ──────────────────────────────────────────────────────────────────

def cmd_burndown(tasks: List[Task], days: int = 30) -> str:
    """Daily burndown chart for the last N days."""
    now   = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    dates = [now - timedelta(days=i) for i in range(days - 1, -1, -1)]

    def snapshot(day: datetime):
        day_end = day + timedelta(days=1)
        pending = done = 0
        for t in tasks:
            entry_dt = parse_date(t.entry)
            if not entry_dt or entry_dt >= day_end:
                continue
            end_dt = parse_date(t.end) if t.end else None
            if end_dt and end_dt < day_end:
                if t.status == "completed":
                    done += 1
            else:
                pending += 1
        return pending, done

    daily     = [snapshot(d) for d in dates]
    max_count = max((p + d for p, d in daily), default=1) or 1
    height    = 15
    y_step    = max_count / height

    chart_rows = []
    for row in range(height, -1, -1):
        threshold = row * y_step
        y_label   = f"{round(threshold):>3} |" if row % (height // 3) == 0 else "    |"
        cells     = [
            "." if done >= threshold else "X" if (pending + done) >= threshold else " "
            for (pending, done) in daily
        ]
        chart_rows.append(y_label + "  ".join(cells))

    width      = len(dates)
    header     = f"{'Daily Burndown':^{width * 3 + 6}}"
    day_labels = "    +" + "-" * (width * 3 - 1)
    date_row   = "      " + "  ".join(d.strftime("%d") for d in dates)
    month_row  = "      " + "  ".join(d.strftime("%b") if d.day == 1 else "   " for d in dates).rstrip()

    lines = [header, ""] + chart_rows + [day_labels, date_row]
    if any(d.day == 1 for d in dates):
        lines.append(month_row)
    lines.append("\n   . Done    X Pending")

    if len(daily) >= 2:
        net_rate = (daily[0][0] - daily[-1][0]) / max(len(daily) - 1, 1)
        lines.append(f"\nNet Fix Rate: {net_rate:+.1f}/d")

    return "\n".join(lines)


# ── calendar ──────────────────────────────────────────────────────────────────

def cmd_calendar(tasks: List[Task], months_ahead: int = 3) -> str:
    """Three-month calendar view with due dates marked."""
    now   = datetime.now(timezone.utc)
    today = now.date()

    # due date → task list for pending tasks only
    due_map: dict = defaultdict(list)
    for t in tasks:
        if t.due and t.status == "pending":
            dt = parse_date(t.due)
            if dt:
                due_map[dt.date()].append(t)

    def render_month(year: int, month: int) -> list:
        header = f"{calendar.month_name[month]} {year}".center(20)
        rows   = [header, "Su Mo Tu We Th Fr Sa"]
        for week in calendar.monthcalendar(year, month):
            cells = []
            for day in week:
                if day == 0:
                    cells.append("  ")
                else:
                    d = datetime(year, month, day).date()
                    cells.append(f"{day:2d}")
            rows.append(" ".join(cells))
        while len(rows) < 8:
            rows.append("")
        return rows

    months = []
    y, m = now.year, now.month
    for _ in range(months_ahead):
        months.append(render_month(y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    max_rows = max(len(blk) for blk in months)
    for blk in months:
        while len(blk) < max_rows:
            blk.append("")

    lines = ["   ".join(f"{blk[i]:<20}" for blk in months).rstrip() for i in range(max_rows)]

    upcoming = sorted((d for d in due_map if d >= today))
    if upcoming:
        lines.append("")
        lines.append("Due this period:")
        for d in upcoming[:10]:
            for t in due_map[d]:
                lines.append(f"  {d.strftime('%Y-%m-%d')}  {t.description}")

    return "\n".join(lines)
