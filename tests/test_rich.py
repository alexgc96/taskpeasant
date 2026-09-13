"""taskpeasant/_rich.py — Rich renderers for the CLI display layer.

This pass covers the Calendar section only (color shading, week numbers,
legend). Other renderers in that module (render_report, render_list,
render_info, ...) are untested here and get their own sections as
coverage is added — see _rich.py's own `# ── Section ──` banners."""

from datetime import timedelta

import pytest

from taskpeasant._colors import calendar_day_style, calendar_weeknumber_style
from taskpeasant._rich import render_calendar
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
