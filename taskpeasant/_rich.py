"""
taskpeasant/_rich.py
Rich renderers for the CLI display layer (__main__.py only).
Never called from execute_command() or any programmatic API path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ._dates import parse_date
from .task_model import Task
from .urgency import compute_urgency


# ── Shared ────────────────────────────────────────────────────────────────────

def _urgency_color(urg: float) -> str:
    if urg >= 10:
        return "bold red"
    if urg >= 5:
        return "yellow"
    if urg >= 1:
        return "cyan"
    return "dim"


def _due_color(due: str) -> str:
    if not due:
        return "white"
    now = datetime.now(timezone.utc)
    dt  = parse_date(due)
    if not dt:
        return "white"
    delta = (dt - now).total_seconds() / 86400
    if delta < 0:
        return "bold red"
    if delta < 1:
        return "red"
    if delta < 7:
        return "yellow"
    return "white"


# ── Task list (task, task next, task all) ─────────────────────────────────────

def render_list(tasks: List[Task], show_status: bool = False) -> Table:
    """Rich Table for task list views."""
    table = Table(box=None, show_header=True, header_style="bold white",
                  padding=(0, 1), expand=False)
    table.add_column("ID",  style="bold cyan",  justify="right", width=4)
    table.add_column("UUID", style="dim",        width=9)
    table.add_column("Urg",  justify="right",    width=5)
    if show_status:
        table.add_column("Status", width=10)
    table.add_column("Description", min_width=20, max_width=40)
    table.add_column("Tags",   style="blue",      no_wrap=True)
    table.add_column("Due",                       no_wrap=True)

    for t in tasks:
        urg_str  = f"{t.urgency_value:.1f}"
        tag_str  = " ".join(f"+{tg}" for tg in t.tags)
        due_str  = t.due[:10] if t.due else ""
        active   = " ▶" if t.start else ""
        id_str   = str(t.id) if t.id else "—"
        desc     = Text(t.description[:40] + active)

        row = [
            id_str,
            t.uuid[:8],
            Text(urg_str, style=_urgency_color(t.urgency_value)),
        ]
        if show_status:
            row.append(t.status)
        row += [
            desc,
            tag_str,
            Text(due_str, style=_due_color(t.due)),
        ]
        table.add_row(*row)

    return table


# ── Info view ─────────────────────────────────────────────────────────────────

def render_info(t: Task) -> Panel:
    """Rich Panel for single task detail."""
    from rich.table import Table as RTable

    grid = RTable.grid(padding=(0, 2))
    grid.add_column(style="dim",        width=14)
    grid.add_column(style="bold white")

    def row(label, value):
        if value:
            grid.add_row(label, str(value))

    row("ID",          str(t.id) if t.id else "—")
    row("UUID",        t.uuid)
    row("Status",      t.status)
    row("Project",     t.project)
    row("Priority",    t.priority)
    row("Tags",        " ".join(f"+{tg}" for tg in t.tags))
    row("Due",         Text(t.due[:10] if t.due else "", style=_due_color(t.due)))
    row("Scheduled",   t.scheduled[:10] if t.scheduled else "")
    row("Wait",        t.wait[:10] if t.wait else "")
    row("Depends",     ", ".join(t.depends))
    row("Entry",       t.entry[:10] if t.entry else "")
    row("Modified",    t.modified[:10] if t.modified else "")
    row("Urgency",     Text(f"{t.urgency_value:.2f}", style=_urgency_color(t.urgency_value)))

    if t.annotations:
        grid.add_row("", "")
        grid.add_row("[dim]Annotations[/dim]", "")
        for a in t.annotations:
            date = a.get("entry", "")[:10]
            grid.add_row(f"  [dim]{date}[/dim]", a.get("description", ""))

    return Panel(grid, title=f"[bold]{t.description}[/bold]",
                 border_style="cyan", expand=False)


# ── History ───────────────────────────────────────────────────────────────────

def render_history(buckets: dict) -> Table:
    table = Table(box=None, show_header=True, header_style="bold white", padding=(0, 1))
    table.add_column("Year",  width=6)
    table.add_column("Month", width=10)
    table.add_column("Added",     justify="right", style="green",  width=7)
    table.add_column("Completed", justify="right", style="blue",   width=10)
    table.add_column("Deleted",   justify="right", style="red",    width=8)
    table.add_column("Net",       justify="right",                 width=6)

    import calendar as _cal
    prev_year = None
    for (year, month) in sorted(buckets):
        b        = buckets[(year, month)]
        net      = b["added"] - b["completed"] - b["deleted"]
        year_str = str(year) if year != prev_year else ""
        prev_year = year
        net_text = Text(str(net), style="green" if net >= 0 else "red")
        table.add_row(year_str, _cal.month_name[month],
                      str(b["added"]), str(b["completed"]), str(b["deleted"]), net_text)
    return table


# ── Ghistory ──────────────────────────────────────────────────────────────────

def render_ghistory(buckets: dict) -> Table:
    import calendar as _cal
    bar_width = 54
    max_val   = max(b["added"] + b["completed"] + b["deleted"] for b in buckets.values()) or 1

    table = Table(box=None, show_header=True, header_style="bold white", padding=(0, 1))
    table.add_column("Year",  width=6)
    table.add_column("Month", width=6)
    table.add_column("Activity", width=bar_width + 2)

    prev_year = None
    for (year, month) in sorted(buckets):
        b         = buckets[(year, month)]
        year_str  = str(year) if year != prev_year else ""
        prev_year = year
        scale     = bar_width / max_val
        bar       = Text()
        bar.append("+" * round(b["added"]     * scale), style="green")
        bar.append("X" * round(b["completed"] * scale), style="blue")
        bar.append("-" * round(b["deleted"]   * scale), style="red")
        table.add_row(year_str, _cal.month_name[month][:3], bar)

    return table


# ── Burndown ──────────────────────────────────────────────────────────────────

def render_burndown(daily: list, dates: list) -> Text:
    """Color the burndown chart: X=red (pending), .=green (done)."""
    from .reports import cmd_burndown as _plain_burndown
    # Re-render using plain text then colorize
    plain = _plain_burndown.__doc__   # fallback not used — we rebuild inline

    height    = 15
    max_count = max((p + d for p, d in daily), default=1) or 1
    y_step    = max_count / height

    out = Text()
    out.append(f"{'Daily Burndown':^{len(dates) * 3 + 6}}\n\n", style="bold white")

    for row in range(height, -1, -1):
        threshold = row * y_step
        y_label   = f"{round(threshold):>3} |" if row % (height // 3) == 0 else "    |"
        out.append(y_label, style="dim")
        for (pending, done) in daily:
            if done >= threshold:
                out.append(".  ", style="green")
            elif (pending + done) >= threshold:
                out.append("X  ", style="red")
            else:
                out.append("   ")
        out.append("\n")

    width = len(dates)
    out.append("    +" + "-" * (width * 3 - 1) + "\n", style="dim")
    out.append("      " + "  ".join(d.strftime("%d") for d in dates) + "\n", style="dim")
    month_parts = [d.strftime("%b") if d.day == 1 else "   " for d in dates]
    if any(d.day == 1 for d in dates):
        out.append("      " + "  ".join(month_parts).rstrip() + "\n", style="dim")
    out.append("\n")
    out.append(". Done", style="green")
    out.append("   ")
    out.append("X Pending", style="red")
    out.append("\n")
    return out


# ── Calendar ──────────────────────────────────────────────────────────────────

def render_calendar(tasks: List[Task]) -> Text:
    """Calendar with today highlighted and due dates in red."""
    import calendar as _cal
    from collections import defaultdict
    from datetime import datetime as dt_

    now   = datetime.now(timezone.utc)
    today = now.date()

    due_map: dict = defaultdict(list)
    for t in tasks:
        if t.due and t.status == "pending":
            d = parse_date(t.due)
            if d:
                due_map[d.date()].append(t)

    def render_month_text(year: int, month: int) -> list[str]:
        header = f"{_cal.month_name[month]} {year}".center(20)
        lines  = [header, "Su Mo Tu We Th Fr Sa"]
        for week in _cal.monthcalendar(year, month):
            parts = []
            for day in week:
                parts.append("  " if day == 0 else f"{day:2d}")
            lines.append(" ".join(parts))
        while len(lines) < 8:
            lines.append("")
        return lines

    months, y, m = [], now.year, now.month
    for _ in range(3):
        months.append(render_month_text(y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    max_rows = max(len(b) for b in months)
    for b in months:
        while len(b) < max_rows:
            b.append("")

    out = Text()
    for i in range(max_rows):
        row_parts = "   ".join(f"{blk[i]:<20}" for blk in months)
        out.append(row_parts.rstrip() + "\n",
                   style="bold white" if i == 0 else ("dim" if i == 1 else "white"))

    upcoming = sorted(d for d in due_map if d >= today)
    if upcoming:
        out.append("\nDue this period:\n", style="bold white")
        for d in upcoming[:10]:
            for t in due_map[d]:
                color = "red" if d == today else "yellow" if (d - today).days < 7 else "white"
                out.append(f"  {d.strftime('%Y-%m-%d')}  ", style=f"bold {color}")
                out.append(t.description + "\n")

    return out


# ── Confirmation / error lines ────────────────────────────────────────────────

def confirm(msg: str) -> Text:
    t = Text()
    t.append("✓ ", style="bold green")
    t.append(msg)
    return t


def error(msg: str) -> Text:
    t = Text()
    t.append("✗ ", style="bold red")
    t.append(msg)
    return t
