"""Milestone 2: the report engine — definitions, columns, sort, filters,
custom reports, dispatch through execute_command."""

from datetime import timedelta

import pytest

from taskpeasant import execute_command
from taskpeasant._taskrc import Taskrc
from taskpeasant.report_engine import (format_duration_compact, get_formatter,
                                       get_report, parse_sort_spec,
                                       sort_tasks)
from taskpeasant.storage import write_tasks
from tests.conftest import iso, now_utc


@pytest.fixture
def report_yaml(yaml_file, make_task):
    tasks = [
        make_task(description="overdue high", priority="H",
                  due=iso(now_utc() - timedelta(days=2)),
                  project="film", tags=["work"]),
        make_task(description="active task", start=iso(now_utc()),
                  project="film.edit"),
        make_task(description="waiting task", status="waiting",
                  wait=iso(now_utc() + timedelta(days=5))),
        make_task(description="done task", status="completed",
                  end=iso(now_utc() - timedelta(hours=2))),
        make_task(description="plain future", due=iso(now_utc() +
                                                      timedelta(days=20))),
    ]
    write_tasks(yaml_file, tasks)
    return yaml_file


# ── Built-in reports through execute_command ──────────────────────────────────

def test_next_report(report_yaml):
    out = execute_command("task next", report_yaml)
    assert "overdue high" in out
    assert "done task" not in out
    assert "waiting task" not in out          # -WAITING
    assert out.rstrip().endswith("tasks")


def test_list_report(report_yaml):
    out = execute_command("task list", report_yaml)
    assert "overdue high" in out and "active task" in out
    assert "waiting task" not in out


def test_all_report_includes_everything(report_yaml):
    out = execute_command("task all", report_yaml)
    for desc in ("overdue high", "active task", "waiting task", "done task"):
        assert desc in out


def test_completed_report(report_yaml):
    out = execute_command("task completed", report_yaml)
    assert "done task" in out
    assert "overdue high" not in out


def test_waiting_report(report_yaml):
    out = execute_command("task waiting", report_yaml)
    assert "waiting task" in out
    assert "active task" not in out


def test_active_report(report_yaml):
    out = execute_command("task active", report_yaml)
    assert "active task" in out
    assert "overdue high" not in out


def test_overdue_report(report_yaml):
    out = execute_command("task overdue", report_yaml)
    assert "overdue high" in out
    assert "plain future" not in out


def test_ready_report_excludes_waiting(report_yaml):
    out = execute_command("task ready", report_yaml)
    assert "overdue high" in out
    assert "waiting task" not in out


def test_ls_minimal_long_newest_oldest_exist(report_yaml):
    for name in ("ls", "minimal", "long", "newest", "oldest",
                 "blocked", "blocking", "unblocked"):
        out = execute_command(f"task {name}", report_yaml)
        assert "Unknown report" not in out


def test_filter_before_report_name(report_yaml):
    out = execute_command("task project:film list", report_yaml)
    assert "overdue high" in out
    assert "plain future" not in out
    # hierarchy: film matches film.edit
    assert "active task" in out


def test_filter_after_report_name(report_yaml):
    out = execute_command("task list +work", report_yaml)
    assert "overdue high" in out
    assert "active task" not in out


def test_report_filter_or_isolated_from_user_filter(report_yaml):
    # minimal's filter is 'status:pending or status:waiting'; ANDing a user
    # filter must apply to the whole disjunction
    out = execute_command("task minimal +work", report_yaml)
    assert "overdue high" in out
    assert "waiting task" not in out and "active task" not in out


def test_bare_task_runs_default_command(report_yaml):
    bare = execute_command("task", report_yaml)
    listed = execute_command("task list", report_yaml)
    assert bare == listed


def test_default_command_override(report_yaml):
    out = execute_command("task rc.default.command=completed", report_yaml)
    assert "done task" in out


# ── Custom reports ────────────────────────────────────────────────────────────

def test_custom_report_via_rc_override(report_yaml):
    out = execute_command(
        "task rc.report.mine.columns=id,description.desc "
        "rc.report.mine.sort=description+ "
        "rc.report.mine.filter=status:pending mine", report_yaml)
    assert "active task" in out
    assert "done task" not in out


def test_custom_report_via_config(report_yaml):
    conf = Taskrc({"report.kanban.columns": "id,project,description.desc",
                   "report.kanban.labels": "ID,Proj,Desc",
                   "report.kanban.filter": "+ACTIVE"})
    out = execute_command("task kanban", report_yaml, config=conf)
    assert "active task" in out and "overdue high" not in out
    assert "Proj" in out


def test_unknown_report_not_hijacked(report_yaml):
    # a word that is no report stays a description search
    out = execute_command("task plain", report_yaml)
    assert "plain future" in out


# ── limit ─────────────────────────────────────────────────────────────────────

def test_limit_page_caps_next(yaml_file, make_task):
    write_tasks(yaml_file, [make_task(description=f"t{i}")
                            for i in range(40)])
    out = execute_command("task next", yaml_file)
    assert "25 tasks" in out


def test_explicit_limit(yaml_file, make_task):
    write_tasks(yaml_file, [make_task(description=f"t{i}")
                            for i in range(10)])
    out = execute_command("task list limit:3", yaml_file)
    assert "3 tasks" in out


# ── Column formatters ─────────────────────────────────────────────────────────

def test_description_count(make_task):
    t = make_task(description="d",
                  annotations=[{"entry": "e", "description": "note"}])
    from taskpeasant.report_engine import _Ctx
    from datetime import datetime, timezone
    ctx = _Ctx(datetime.now(timezone.utc), {})
    assert get_formatter("description.count")(t, ctx) == "d [1]"
    assert get_formatter("description.desc")(t, ctx) == "d"
    assert "note" in get_formatter("description")(t, ctx)


def test_status_and_uuid_short(make_task):
    from taskpeasant.report_engine import _Ctx
    from datetime import datetime, timezone
    ctx = _Ctx(datetime.now(timezone.utc), {})
    t = make_task(status="waiting")
    assert get_formatter("status.short")(t, ctx) == "W"
    assert get_formatter("uuid.short")(t, ctx) == t.uuid[:8]


def test_tags_and_depends_indicators(make_task):
    from taskpeasant.report_engine import _Ctx
    from datetime import datetime, timezone
    dep = make_task()
    t = make_task(tags=["a", "b"], depends=[dep.uuid])
    dep.id, t.id = 1, 2
    ctx = _Ctx(datetime.now(timezone.utc), {dep.uuid: 1, t.uuid: 2})
    assert get_formatter("tags.count")(t, ctx) == "[2]"
    assert get_formatter("tags.indicator")(t, ctx) == "+"
    assert get_formatter("depends.indicator")(t, ctx) == "D"
    assert get_formatter("depends")(t, ctx) == "1"


def test_due_relative_sign(make_task):
    from taskpeasant.report_engine import _Ctx
    from datetime import datetime, timezone
    ctx = _Ctx(datetime.now(timezone.utc), {})
    overdue = make_task(due=iso(now_utc() - timedelta(days=3)))
    future  = make_task(due=iso(now_utc() + timedelta(days=3)))
    assert get_formatter("due.relative")(overdue, ctx).startswith("-")
    assert not get_formatter("due.relative")(future, ctx).startswith("-")


def test_uda_column(make_task):
    from taskpeasant.report_engine import _Ctx
    from datetime import datetime, timezone
    ctx = _Ctx(datetime.now(timezone.utc), {})
    t = make_task(udas={"size": "xl"})
    assert get_formatter("size")(t, ctx) == "xl"


def test_format_duration_compact():
    assert format_duration_compact(30) == "30s"
    assert format_duration_compact(120) == "2min"
    assert format_duration_compact(7200) == "2h"
    assert format_duration_compact(86400 * 3) == "3d"
    assert format_duration_compact(86400 * 30) == "4w"
    assert format_duration_compact(86400 * 120) == "4mo"
    assert format_duration_compact(86400 * 800) == "2.2y"
    assert format_duration_compact(-86400 * 2) == "-2d"


# ── Sorting ───────────────────────────────────────────────────────────────────

def test_parse_sort_spec():
    assert parse_sort_spec("urgency-,due+,project") == \
        [("urgency", False), ("due", True), ("project", True)]
    assert parse_sort_spec("project+/,description+") == \
        [("project", True), ("description", True)]


def test_sort_missing_values_last_both_directions(make_task):
    a = make_task(due=iso(now_utc() + timedelta(days=1)))
    b = make_task(due=iso(now_utc() + timedelta(days=9)))
    c = make_task()          # no due
    tasks = [c, b, a]
    sort_tasks(tasks, "due+")
    assert tasks == [a, b, c]
    sort_tasks(tasks, "due-")
    assert tasks == [b, a, c]


def test_sort_priority_rank(make_task):
    h = make_task(priority="H")
    m = make_task(priority="M")
    none = make_task()
    tasks = [none, m, h]
    sort_tasks(tasks, "priority-")
    assert tasks == [h, m, none]


# ── Meta commands ─────────────────────────────────────────────────────────────

def test_reports_command(yaml_file):
    out = execute_command("task reports", yaml_file)
    assert "next" in out and "Most urgent tasks" in out


def test_columns_command(yaml_file):
    out = execute_command("task columns", yaml_file)
    assert "description.count" in out and "due.relative" in out


def test_empty_columns_dropped(yaml_file, make_task):
    # No task has tags → the Tags column must not appear at all
    write_tasks(yaml_file, [make_task(description="solo")])
    out = execute_command("task list", yaml_file)
    assert "Tags" not in out
