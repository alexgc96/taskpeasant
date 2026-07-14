"""Milestone 5: graphical/aggregate reports — burndown, history variants,
calendar, summary, stats, timesheet, projects/tags/udas, helper commands."""

from datetime import timedelta

import pytest

from taskpeasant import execute_command
from taskpeasant.storage import write_tasks
from tests.conftest import iso, now_utc


@pytest.fixture
def rich_yaml(yaml_file, make_task):
    tasks = [
        make_task(description="old done", status="completed",
                  entry=iso(now_utc() - timedelta(days=40)),
                  end=iso(now_utc() - timedelta(days=35)),
                  project="film"),
        make_task(description="recent done", status="completed",
                  entry=iso(now_utc() - timedelta(days=3)),
                  end=iso(now_utc() - timedelta(days=1)),
                  project="film"),
        make_task(description="working on it", start=iso(now_utc()),
                  entry=iso(now_utc() - timedelta(days=5)),
                  project="film", tags=["studio"]),
        make_task(description="due soon", due=iso(now_utc() +
                                                  timedelta(days=2)),
                  project="reno", tags=["home"]),
        make_task(description="deleted one", status="deleted",
                  end=iso(now_utc() - timedelta(days=2))),
    ]
    write_tasks(yaml_file, tasks)
    return yaml_file


# ── history / ghistory periods ────────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["history", "history.monthly",
                                     "history.daily", "history.weekly",
                                     "history.annual"])
def test_history_variants(rich_yaml, variant):
    out = execute_command(f"task {variant}", rich_yaml)
    assert "Added" in out and "Completed" in out
    assert "Average" in out


@pytest.mark.parametrize("variant", ["ghistory", "ghistory.monthly",
                                     "ghistory.annual", "ghistory.daily",
                                     "ghistory.weekly"])
def test_ghistory_variants(rich_yaml, variant):
    out = execute_command(f"task {variant}", rich_yaml)
    assert "Legend" in out and "+" in out


def test_history_respects_filter(rich_yaml):
    filtered = execute_command("task history project:film", rich_yaml)
    full = execute_command("task history", rich_yaml)
    assert filtered != full


# ── burndown ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("variant,title", [
    ("burndown", "Daily Burndown"),
    ("burndown.daily", "Daily Burndown"),
    ("burndown.weekly", "Weekly Burndown"),
    ("burndown.monthly", "Monthly Burndown"),
])
def test_burndown_variants(rich_yaml, variant, title):
    out = execute_command(f"task {variant}", rich_yaml)
    assert title in out
    assert ". Done" in out and "o Started" in out and "X Pending" in out
    assert "Net Fix Rate" in out


def test_burndown_shows_started_band(rich_yaml):
    out = execute_command("task burndown", rich_yaml)
    assert "o" in out.split("Net Fix Rate")[0]


# ── calendar ──────────────────────────────────────────────────────────────────

def test_calendar_default_three_months(rich_yaml):
    out = execute_command("task calendar", rich_yaml)
    import calendar as _cal
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assert _cal.month_name[now.month] in out
    assert "Due this period:" in out
    assert "due soon" in out


def test_calendar_year(rich_yaml):
    out = execute_command("task calendar 2027", rich_yaml)
    assert "January 2027" in out and "December 2027" in out


def test_calendar_due(rich_yaml):
    out = execute_command("task calendar due", rich_yaml)
    assert "due soon" in out


def test_calendar_weekstart_config(rich_yaml):
    sunday = execute_command("task calendar", rich_yaml)
    monday = execute_command("task rc.weekstart=monday calendar", rich_yaml)
    assert "Su Mo" in sunday
    assert "Mo Tu" in monday


def test_calendar_details_none(rich_yaml):
    out = execute_command("task rc.calendar.details=none calendar", rich_yaml)
    assert "Due this period:" not in out


# ── summary ───────────────────────────────────────────────────────────────────

def test_summary(rich_yaml):
    out = execute_command("task summary", rich_yaml)
    assert "film" in out and "reno" in out
    assert "Remaining" in out and "Complete" in out
    # film: 2 done, 1 pending → 67%
    film_line = next(ln for ln in out.splitlines() if ln.startswith("film"))
    assert "67%" in film_line and "=" in film_line
    reno_line = next(ln for ln in out.splitlines() if ln.startswith("reno"))
    assert "0%" in reno_line


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats(rich_yaml):
    out = execute_command("task stats", rich_yaml)
    assert "Pending" in out and "Total" in out
    lines = {ln.split()[0]: ln for ln in out.splitlines() if ln}
    assert lines["Total"].endswith("5")
    assert lines["Completed"].endswith("2")
    assert lines["Deleted"].endswith("1")
    assert "Oldest" in out


# ── timesheet ─────────────────────────────────────────────────────────────────

def test_timesheet(rich_yaml):
    out = execute_command("task timesheet", rich_yaml)
    assert "Week starting" in out
    assert "recent done" in out
    assert "working on it" in out          # started this period
    assert "old done" not in out           # 5 weeks ago


# ── projects / tags / udas ────────────────────────────────────────────────────

def test_projects_command(rich_yaml):
    out = execute_command("task projects", rich_yaml)
    assert "film" in out and "reno" in out
    assert "2 projects" in out or "3 projects" in out


def test_tags_command(rich_yaml):
    out = execute_command("task tags", rich_yaml)
    assert "studio" in out and "home" in out


def test_udas_command(yaml_file, make_task):
    write_tasks(yaml_file, [make_task(udas={"size": "xl"})])
    out = execute_command(
        "task rc.uda.size.type=string rc.uda.size.label=Size udas", yaml_file)
    assert "size" in out and "Size" in out


# ── helper commands ───────────────────────────────────────────────────────────

def test_ids_compact_ranges(rich_yaml):
    # two open tasks → ids 1 and 2 → compact range "1-2"
    out = execute_command("task ids", rich_yaml)
    assert out == "1-2"


def test_ids_with_filter(rich_yaml):
    out = execute_command("task ids project:reno", rich_yaml)
    assert out.isdigit()


def test_uuids_and_private_variants(rich_yaml):
    out = execute_command("task uuids project:reno", rich_yaml)
    assert len(out.split()) == 1
    out2 = execute_command("task _uuids project:film", rich_yaml)
    assert len(out2.splitlines()) == 3


def test_private_projects_tags(rich_yaml):
    assert execute_command("task _projects", rich_yaml).splitlines() == \
        ["film", "reno"]
    tags = execute_command("task _tags", rich_yaml).splitlines()
    assert "home" in tags and "studio" in tags


def test_commands_listing(rich_yaml):
    out = execute_command("task _commands", rich_yaml).splitlines()
    for cmd in ("add", "done", "next", "burndown", "summary", "undo"):
        assert cmd in out


def test_get_dom(rich_yaml):
    desc = execute_command("task _get 1.description", rich_yaml)
    assert desc
    urg = execute_command("task _get 1.urgency", rich_yaml)
    assert float(urg) >= 0.0
    assert execute_command("task _get 999.due", rich_yaml) == ""
