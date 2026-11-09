"""taskpeasant/_rich.py — Rich renderers for the CLI display layer.

One section per renderer, in the same order and with the same
`# ── Section ──` banners as _rich.py itself.  The Calendar section also
covers its rule engine in _colors.py."""

from datetime import datetime, timedelta, timezone

import pytest
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from taskpeasant._colors import calendar_day_style, calendar_weeknumber_style
from taskpeasant._rich import (_due_color, _urgency_color, confirm, error,
                               render_burndown, render_calendar,
                               render_ghistory, render_history, render_info,
                               render_list, render_report)
from taskpeasant._taskrc import Taskrc
from tests.conftest import iso, now_utc


def _conf(extra=None):
    return Taskrc(extra or {})


def _spans_with_style(text, style):
    return [text.plain[s.start:s.end] for s in text.spans if s.style == style]


def _grid_spans_with_style(text, style):
    """Like _spans_with_style, but excludes the trailing "Due this
    period"/"Legend" sections — those reuse the same style strings for
    their swatch words, which would otherwise show up as false matches
    alongside the actual day/weeknumber cells."""
    boundary = text.plain.find("\n\n")
    limit = boundary if boundary != -1 else len(text.plain)
    return [text.plain[s.start:s.end] for s in text.spans
            if s.style == style and s.end <= limit]


def _header_line(plain):
    return next(ln for ln in plain.splitlines() if "Su Mo Tu We Th Fr Sa" in ln)


def _headers(table):
    return [c.header for c in table.columns]


def _column(table, header):
    """The cells of the column titled `header`, top to bottom."""
    return list(next(c for c in table.columns if c.header == header).cells)


def _plain(cell):
    return cell.plain if isinstance(cell, Text) else str(cell)


def _bucket(added=0, completed=0, deleted=0):
    return {"added": added, "completed": completed, "deleted": deleted}


# ── Shared ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("urg, style", [
    (15.0, "bold red"), (10.0, "bold red"),
    (9.99, "yellow"), (5.0, "yellow"),
    (4.99, "cyan"), (1.0, "cyan"),
    (0.99, "dim"), (0.0, "dim"),
])
def test_urgency_color_bands(urg, style):
    assert _urgency_color(urg) == style


@pytest.mark.parametrize("offset, style", [
    (timedelta(days=-2), "bold red"),       # overdue
    (timedelta(hours=6), "red"),            # within a day
    (timedelta(days=3), "yellow"),          # within a week
    (timedelta(days=30), "white"),          # far off
])
def test_due_color_bands(offset, style):
    assert _due_color(iso(now_utc() + offset)) == style


@pytest.mark.parametrize("due", ["", "not a date"])
def test_due_color_missing_or_unparseable_is_default(due):
    assert _due_color(due) == "white"


# ── Report engine table ──────────────────────────────────────────────────────

_REPORT_HEADERS = ["ID", "Description", "Due", "Urg"]
_REPORT_SPECS = ["id", "description.count", "due.relative", "urgency"]


def _report(tasks, conf=None):
    rows = [[str(i + 1), t.description, t.due[:10], f"{t.urgency_value:.1f}"]
            for i, t in enumerate(tasks)]
    return render_report(_REPORT_HEADERS, rows, _REPORT_SPECS, tasks, conf)


def test_render_report_columns(make_task):
    table = _report([make_task()])
    assert isinstance(table, Table)
    assert _headers(table) == _REPORT_HEADERS
    by_header = {c.header: c for c in table.columns}
    assert by_header["ID"].justify == "right"
    assert by_header["ID"].style == "bold cyan"
    assert by_header["Urg"].justify == "right"
    assert by_header["Description"].justify == "left"
    # only the description column may wrap
    assert [c.no_wrap for c in table.columns] == [True, False, True, True]


def test_render_report_row_content(make_task):
    tasks = [make_task(description="first"), make_task(description="second")]
    table = _report(tasks)
    assert table.row_count == 2
    assert _column(table, "Description") == ["first", "second"]
    assert _column(table, "ID") == ["1", "2"]


def test_render_report_styles_urgency_and_due_cells(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=2)))
    t.urgency_value = 12.0
    table = _report([t])                    # conf=None → no color rules
    urg, due = _column(table, "Urg")[0], _column(table, "Due")[0]
    assert (urg.plain, urg.style) == ("12.0", "bold red")
    assert due.style == "bold red"
    assert table.rows[0].style is None


def test_render_report_color_rule_styles_whole_row(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=2)))
    t.urgency_value = 12.0
    t.virtual_tags = {"OVERDUE"}            # color rules key off vtags
    conf = _conf({"color.overdue": "white on red"})
    table = _report([t], conf)
    assert table.rows[0].style == "white on red"
    # the rule style covers the row, so cells stay plain strings
    assert _column(table, "Urg") == ["12.0"]
    assert isinstance(_column(table, "Due")[0], str)


def test_render_report_active_task_row(make_task):
    """A started task takes color.active for the whole row, ahead of the
    overdue rule and the per-cell urgency/due styles."""
    t = make_task(due=iso(now_utc() - timedelta(days=2)),
                  start=iso(now_utc()))
    t.urgency_value = 14.94
    t.virtual_tags = {"ACTIVE", "OVERDUE"}
    table = _report([make_task(), t], _conf())
    assert table.rows[0].style is None                  # not started
    assert table.rows[1].style == "black on bright_green"
    assert _column(table, "Urg")[1] == "14.9"           # plain: row style wins
    assert isinstance(_column(table, "Due")[1], str)


def test_render_report_active_color_is_configurable(make_task):
    t = make_task(start=iso(now_utc()))
    table = _report([t], _conf({"color.active": "bold white on blue"}))
    assert table.rows[0].style == "bold white on blue"


def test_render_report_color_off_falls_back_to_cell_styles(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=2)))
    t.virtual_tags = {"OVERDUE"}
    conf = _conf({"color": "0", "color.overdue": "white on red"})
    table = _report([t], conf)
    assert table.rows[0].style is None
    assert _column(table, "Due")[0].style == "bold red"


def test_render_report_empty():
    table = render_report(_REPORT_HEADERS, [], _REPORT_SPECS, [])
    assert _headers(table) == _REPORT_HEADERS
    assert table.row_count == 0


# ── Task list (task, task next, task all) ────────────────────────────────────

def test_render_list_columns():
    table = render_list([])
    assert isinstance(table, Table)
    assert _headers(table) == ["ID", "UUID", "Urg", "Description", "Tags",
                               "Due"]
    assert table.row_count == 0


def test_render_list_show_status_adds_column(make_task):
    table = render_list([make_task(status="completed")], show_status=True)
    assert _headers(table) == ["ID", "UUID", "Urg", "Status", "Description",
                               "Tags", "Due"]
    assert _column(table, "Status") == ["completed"]


def test_render_list_row_content(make_task):
    t = make_task(description="render final shot", tags=["render", "urgent"],
                  due=iso(now_utc() + timedelta(days=3)))
    t.id = 7
    t.urgency_value = 6.25
    table = render_list([t])
    assert _column(table, "ID") == ["7"]
    assert _column(table, "UUID") == [t.uuid[:8]]
    assert _column(table, "Tags") == ["+render +urgent"]
    assert _plain(_column(table, "Description")[0]) == "render final shot"
    urg, due = _column(table, "Urg")[0], _column(table, "Due")[0]
    assert (urg.plain, urg.style) == ("6.2", "yellow")
    assert (due.plain, due.style) == (t.due[:10], "yellow")


def test_render_list_no_id_no_due(make_task):
    t = make_task(status="completed")       # id 0, no due date
    table = render_list([t])
    assert _column(table, "ID") == ["—"]
    due = _column(table, "Due")[0]
    assert (due.plain, due.style) == ("", "white")


def test_render_list_active_marker_and_truncation(make_task):
    t = make_task(description="x" * 60, start=iso(now_utc()))
    desc = _plain(_column(render_list([t]), "Description")[0])
    assert desc == "x" * 40 + " ▶"


# ── Info view ────────────────────────────────────────────────────────────────

def _info_rows(panel):
    """{label: value cell} for the Panel's two-column grid."""
    labels, values = (list(c.cells) for c in panel.renderable.columns)
    return dict(zip(labels, values))


def test_render_info_panel(make_task):
    t = make_task(description="colour grade reel")
    panel = render_info(t)
    assert isinstance(panel, Panel)
    assert panel.title == "[bold]colour grade reel[/bold]"
    assert panel.border_style == "cyan"


def test_render_info_fields(make_task):
    t = make_task(project="film", priority="H", tags=["urgent"],
                  due=iso(now_utc() - timedelta(days=1)),
                  depends=["aaaa1111", "bbbb2222"])
    t.id = 3
    t.urgency_value = 11.5
    t.virtual_tags = {"OVERDUE", "BLOCKED"}
    rows = _info_rows(render_info(t))
    assert rows["ID"] == "3"
    assert rows["UUID"] == t.uuid
    assert rows["Status"] == "pending"
    assert rows["Project"] == "film"
    assert rows["Priority"] == "H"
    assert rows["Tags"] == "+urgent"
    assert rows["Virtual"] == "+BLOCKED +OVERDUE"       # sorted
    assert rows["Due"] == t.due[:10]
    assert rows["Depends"] == "aaaa1111, bbbb2222"
    assert rows["Entry"] == t.entry[:10]
    assert rows["Urgency"] == "11.50"


def test_render_info_omits_empty_fields(make_task):
    rows = _info_rows(render_info(make_task()))
    assert rows["ID"] == "—"
    for label in ("Project", "Priority", "Tags", "Virtual", "Due",
                  "Scheduled", "Wait", "Depends"):
        assert label not in rows


def test_render_info_annotations(make_task):
    t = make_task(annotations=[
        {"entry": "2026-05-01T10:00:00Z", "description": "blocked on review"},
    ])
    rows = _info_rows(render_info(t))
    assert "[dim]Annotations[/dim]" in rows
    assert rows["  [dim]2026-05-01[/dim]"] == "blocked on review"


# ── History ──────────────────────────────────────────────────────────────────

def test_render_history_rows():
    buckets = {(2026, 2): _bucket(added=1, completed=3, deleted=1),
               (2026, 1): _bucket(added=5, completed=2),
               (2025, 12): _bucket(added=2)}
    table = render_history(buckets)
    assert isinstance(table, Table)
    assert _headers(table) == ["Year", "Month", "Added", "Completed",
                               "Deleted", "Net"]
    # chronological; the year prints once per run of months
    assert _column(table, "Year") == ["2025", "2026", ""]
    assert _column(table, "Month") == ["December", "January", "February"]
    assert _column(table, "Added") == ["2", "5", "1"]
    assert _column(table, "Completed") == ["0", "2", "3"]
    assert _column(table, "Deleted") == ["0", "0", "1"]


def test_render_history_net_sign_styling():
    buckets = {(2026, 1): _bucket(added=5, completed=2),
               (2026, 2): _bucket(added=1, completed=3, deleted=1),
               (2026, 3): _bucket(added=2, completed=2)}
    net = _column(render_history(buckets), "Net")
    assert [(n.plain, n.style) for n in net] == [
        ("3", "green"), ("-3", "red"), ("0", "green")]


def test_render_history_empty():
    assert render_history({}).row_count == 0


# ── Ghistory ─────────────────────────────────────────────────────────────────

def test_render_ghistory_bars_scale_to_busiest_month():
    buckets = {(2026, 1): _bucket(added=3, completed=2, deleted=1),
               (2026, 2): _bucket(added=3)}
    table = render_ghistory(buckets)
    assert isinstance(table, Table)
    assert _headers(table) == ["Year", "Month", "Activity"]
    assert _column(table, "Year") == ["2026", ""]
    assert _column(table, "Month") == ["Jan", "Feb"]
    busiest, quiet = _column(table, "Activity")
    # busiest month (6 events) fills the 54-char bar: 27 + 18 + 9
    assert busiest.plain == "+" * 27 + "X" * 18 + "-" * 9
    assert _spans_with_style(busiest, "green") == ["+" * 27]
    assert _spans_with_style(busiest, "blue") == ["X" * 18]
    assert _spans_with_style(busiest, "red") == ["-" * 9]
    assert quiet.plain == "+" * 27


def test_render_ghistory_all_zero_buckets():
    table = render_ghistory({(2026, 1): _bucket()})
    assert _column(table, "Activity")[0].plain == ""


# ── Burndown ─────────────────────────────────────────────────────────────────

def _days(n, start=datetime(2026, 3, 30, tzinfo=timezone.utc)):
    return [start + timedelta(days=i) for i in range(n)]


def _chart_rows(text):
    """The plotted rows only: lines with a y-axis bar, labels stripped."""
    return [ln.split("|", 1)[1] for ln in text.plain.splitlines()
            if "|" in ln]


def test_render_burndown_structure():
    dates = _days(3)                        # Mar 30, Mar 31, Apr 1
    text = render_burndown([(2, 1, 0), (1, 1, 1), (0, 0, 3)], dates)
    assert isinstance(text, Text)
    assert "Daily Burndown" in text.plain
    assert len(_chart_rows(text)) == 16     # height 15 + the zero row
    assert "30 31 01" in text.plain         # day-of-month axis
    assert "Apr" in text.plain              # month label on the 1st
    assert text.plain.rstrip().endswith(". Done   o Started   X Pending")


def test_render_burndown_band_colors():
    text = render_burndown([(2, 1, 0), (1, 1, 1), (0, 0, 3)], _days(3))
    bottom = _chart_rows(text)[-1]
    # bottom row: day 1 has only pending/started, days 2-3 have done work
    assert bottom.split() == ["o", ".", "."]
    top = _chart_rows(text)[0]
    assert top.split() == ["X", "X", "."]
    assert set(_spans_with_style(text, "red")) == {"X  ", "X Pending"}
    assert set(_spans_with_style(text, "yellow")) == {"o  ", "o Started"}
    assert set(_spans_with_style(text, "green")) == {".  ", ". Done"}


def test_render_burndown_no_month_row_without_a_first():
    text = render_burndown([(1, 0, 0)] * 2, _days(2))    # Mar 30, Mar 31
    assert "Mar" not in text.plain and "Apr" not in text.plain


def test_render_burndown_empty_and_all_zero():
    assert _chart_rows(render_burndown([], [])) == [""] * 16
    rows = _chart_rows(render_burndown([(0, 0, 0)], _days(1)))
    assert all(r.strip() == "" for r in rows)


# ── Calendar: rule engine (_colors.py) ──────────────────────────────────────

def test_calendar_overdue_beats_everything():
    flags = {"OVERDUE", "DUE", "TODAY", "DUE_TODAY", "SCHEDULED", "WEEKEND"}
    assert calendar_day_style(flags, _conf()) == "white on red"


def test_calendar_due_today_beats_due_and_today():
    flags = {"DUE", "TODAY", "DUE_TODAY"}
    assert calendar_day_style(flags, _conf()) == "black on bright_yellow"


def test_calendar_due_beats_scheduled():
    assert calendar_day_style({"DUE", "SCHEDULED"}, _conf()) == \
        "black on yellow"


def test_calendar_scheduled_beats_today():
    assert calendar_day_style({"SCHEDULED", "TODAY"}, _conf()) == \
        "black on cyan"


def test_calendar_today_beats_weekend():
    assert calendar_day_style({"TODAY", "WEEKEND"}, _conf()) == \
        "bold white on blue"


def test_calendar_weekend_alone():
    assert calendar_day_style({"WEEKEND"}, _conf()) == "bright_black"


def test_calendar_no_flags_is_default():
    assert calendar_day_style(set(), _conf()) == ""


def test_calendar_color_off_disables_shading():
    conf = _conf({"color": "0"})
    assert calendar_day_style({"OVERDUE"}, conf) == ""


def test_calendar_custom_precedence():
    conf = _conf({"rule.precedence.calendar.color": "weekend,overdue"})
    assert calendar_day_style({"OVERDUE", "WEEKEND"}, conf) == "bright_black"


def test_calendar_weeknumber_style():
    assert calendar_weeknumber_style(_conf()) == "black on white"


# ── Calendar: render_calendar wiring ─────────────────────────────────────────

def test_render_calendar_today_highlighted():
    today = now_utc().date()
    text = render_calendar([], _conf())
    assert _grid_spans_with_style(text, "bold white on blue") == \
        [f"{today.day:2d}"]


def test_render_calendar_due_today_wins(make_task):
    today = now_utc().date()
    t = make_task(due=iso(now_utc()))
    text = render_calendar([t], _conf())
    assert _grid_spans_with_style(text, "black on bright_yellow") == \
        [f"{today.day:2d}"]
    assert _grid_spans_with_style(text, "bold white on blue") == []


def test_render_calendar_future_due(make_task):
    due_date = (now_utc() + timedelta(days=3)).date()
    t = make_task(due=iso(now_utc() + timedelta(days=3)))
    text = render_calendar([t], _conf())
    assert _grid_spans_with_style(text, "black on yellow") == \
        [f"{due_date.day:2d}"]


def test_render_calendar_overdue(make_task):
    today = now_utc().date()
    if today.day == 1:
        # An overdue fixture needs "yesterday" to fall in the same
        # currently-displayed month (padding-month cells are blanked, not
        # colored) — skip on the 1st rather than flake once a month.
        pytest.skip("month-boundary: no 'yesterday' in the displayed month")
    due_date = today - timedelta(days=1)
    t = make_task(due=iso(now_utc() - timedelta(days=1)))
    text = render_calendar([t], _conf())
    assert _grid_spans_with_style(text, "white on red") == \
        [f"{due_date.day:2d}"]


def test_render_calendar_scheduled(make_task):
    sched_date = (now_utc() + timedelta(days=5)).date()
    t = make_task(scheduled=iso(now_utc() + timedelta(days=5)))
    text = render_calendar([t], _conf())
    assert _grid_spans_with_style(text, "black on cyan") == \
        [f"{sched_date.day:2d}"]


def test_render_calendar_weekend_headers_sunday_first():
    text = render_calendar([], _conf())
    hits = _spans_with_style(text, "bright_black")
    assert "Su" in hits and "Sa" in hits


def test_render_calendar_weekend_headers_monday_first():
    conf = _conf({"weekstart": "monday"})
    text = render_calendar([], conf)
    assert "Mo Tu We Th Fr Sa Su" in text.plain
    hits = _spans_with_style(text, "bright_black")
    assert "Sa" in hits and "Su" in hits


def test_render_calendar_weeknumber_column():
    text = render_calendar([], _conf())
    assert _header_line(text.plain).startswith("   Su Mo")
    hits = _grid_spans_with_style(text, "black on white")
    assert hits and all(h.strip().isdigit() for h in hits)


def test_render_calendar_displayweeknumber_off():
    conf = _conf({"displayweeknumber": "0"})
    text = render_calendar([], conf)
    assert _header_line(text.plain).startswith("Su Mo")
    assert _grid_spans_with_style(text, "black on white") == []


def test_render_calendar_legend_present():
    text = render_calendar([], _conf())
    for label in ("Legend:", "today", "weekend", "due", "due-today",
                 "overdue", "scheduled", "weeknumber"):
        assert label in text.plain


def test_render_calendar_legend_off():
    conf = _conf({"calendar.legend": "0"})
    text = render_calendar([], conf)
    assert "Legend:" not in text.plain


# ── Confirmation / error lines ───────────────────────────────────────────────

def test_confirm_line():
    text = confirm("Task added.")
    assert isinstance(text, Text)
    assert text.plain == "✓ Task added."
    assert _spans_with_style(text, "bold green") == ["✓ "]


def test_error_line():
    text = error("No task matching 'abc'")
    assert isinstance(text, Text)
    assert text.plain == "✗ No task matching 'abc'"
    assert _spans_with_style(text, "bold red") == ["✗ "]
