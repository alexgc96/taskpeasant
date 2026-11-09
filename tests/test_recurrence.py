"""Milestone 9: opt-in recurrence — templates, spawning, masks, until."""

from datetime import datetime, timedelta, timezone

import pytest

from taskpeasant import execute_command, read_tasks
from taskpeasant.recurrence import (is_weekdays, nth_occurrence, parse_recur,
                                    synthesize_tasks)
from tests.conftest import iso, now_utc

RC_ON = "rc.recurrence=on"


def x(cmd, yaml_file):
    return execute_command(cmd, yaml_file)


# ── Duration parsing ──────────────────────────────────────────────────────────

def test_parse_named_durations():
    assert parse_recur("daily") == (0, 1)
    assert parse_recur("weekly") == (0, 7)
    assert parse_recur("biweekly") == (0, 14)
    assert parse_recur("monthly") == (1, 0)
    assert parse_recur("quarterly") == (3, 0)
    assert parse_recur("yearly") == (12, 0)
    assert parse_recur("annually") == (12, 0)


def test_parse_unit_durations():
    assert parse_recur("3d") == (0, 3)
    assert parse_recur("2w") == (0, 14)
    assert parse_recur("2wks") == (0, 14)
    assert parse_recur("1m") == (1, 0)
    assert parse_recur("10mo") == (10, 0)
    assert parse_recur("2q") == (6, 0)
    assert parse_recur("1y") == (12, 0)


def test_parse_garbage():
    assert parse_recur("whenever") is None
    assert parse_recur("") is None
    assert is_weekdays("weekdays")


def test_nth_occurrence_monthly_clamps_day():
    base = datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert nth_occurrence(base, "monthly", 1).day == 28   # Feb clamp
    assert nth_occurrence(base, "monthly", 2).day == 31   # Mar restores


def test_nth_occurrence_weekdays_skips_weekend():
    friday = datetime(2026, 7, 10, tzinfo=timezone.utc)   # a Friday
    assert nth_occurrence(friday, "weekdays", 1).weekday() == 0  # Monday


# ── Gate ──────────────────────────────────────────────────────────────────────

def test_recur_rejected_when_disabled(yaml_file):
    out = x("task add pay rent due:tomorrow recur:monthly", yaml_file)
    assert "recurrence is disabled" in out
    assert read_tasks(yaml_file) == []


def test_bad_recur_value_rejected(yaml_file):
    out = x(f"task {RC_ON} add pay rent due:tomorrow recur:whenever",
            yaml_file)
    assert "not a recognised recurrence" in out


def test_recur_requires_due(yaml_file):
    out = x(f"task {RC_ON} add pay rent recur:monthly", yaml_file)
    assert "requires a due date" in out


# ── Template creation & spawning ──────────────────────────────────────────────

def test_template_created_with_recurring_status(yaml_file):
    out = x(f"task {RC_ON} add water plants due:tomorrow recur:weekly",
            yaml_file)
    assert "recurring task" in out
    tpl = next(t for t in read_tasks(yaml_file) if t.status == "recurring")
    assert tpl.recur == "weekly" and tpl.due


def test_children_spawned_on_next_command(yaml_file):
    x(f"task {RC_ON} add water plants due:tomorrow recur:weekly", yaml_file)
    x(f"task {RC_ON} list", yaml_file)      # any command triggers synthesis
    tasks = read_tasks(yaml_file)
    tpl = next(t for t in tasks if t.status == "recurring")
    kids = [t for t in tasks if t.parent == tpl.uuid]
    assert len(kids) == 1                   # due tomorrow → 1 future child
    assert kids[0].status == "pending"
    assert kids[0].imask == "0"
    assert kids[0].recur == "weekly"
    assert tpl.mask == "-"


def test_overdue_template_catches_up(yaml_file, make_task):
    from taskpeasant.storage import write_tasks
    tpl = make_task(description="catch up", status="recurring",
                    recur="daily", due=iso(now_utc() - timedelta(days=3)))
    write_tasks(yaml_file, [tpl])
    x(f"task {RC_ON} rc.recurrence.catchup.limit=0 list", yaml_file)
    kids = [t for t in read_tasks(yaml_file) if t.parent == tpl.uuid]
    # uncapped: 4 arrived occurrences (-3d..today) + 1 future
    assert len(kids) == 5


def _dormant_daily(yaml_file, make_task, days=6):
    """A daily template last touched `days` ago: days+1 arrived
    occurrences (indexes 0..days) are owed, plus one future instance."""
    from taskpeasant.storage import write_tasks
    tpl = make_task(description="dormant", status="recurring",
                    recur="daily", due=iso(now_utc() - timedelta(days=days)))
    write_tasks(yaml_file, [tpl])
    return tpl


def _child_indexes(yaml_file, tpl):
    return sorted(int(t.imask) for t in read_tasks(yaml_file)
                  if t.parent == tpl.uuid)


def test_catchup_capped_per_command_by_default(yaml_file, make_task):
    tpl = _dormant_daily(yaml_file, make_task)
    x(f"task {RC_ON} list", yaml_file)
    # default recurrence.catchup.limit=2: oldest two only, no future yet
    assert _child_indexes(yaml_file, tpl) == [0, 1]
    x(f"task {RC_ON} list", yaml_file)
    assert _child_indexes(yaml_file, tpl) == [0, 1, 2, 3]


def test_catchup_converges_then_adds_future_instance(yaml_file, make_task):
    tpl = _dormant_daily(yaml_file, make_task)
    for _ in range(4):                      # 7 owed at 2 per command
        x(f"task {RC_ON} list", yaml_file)
    # indexes 0..6 have arrived, 7 is the one future instance
    assert _child_indexes(yaml_file, tpl) == list(range(8))
    x(f"task {RC_ON} list", yaml_file)      # caught up: nothing more
    assert _child_indexes(yaml_file, tpl) == list(range(8))
    template = next(t for t in read_tasks(yaml_file) if t.uuid == tpl.uuid)
    assert template.mask == "-" * 8


def test_catchup_limit_is_configurable(yaml_file, make_task):
    tpl = _dormant_daily(yaml_file, make_task)
    x(f"task {RC_ON} rc.recurrence.catchup.limit=5 list", yaml_file)
    assert _child_indexes(yaml_file, tpl) == [0, 1, 2, 3, 4]


def test_catchup_limit_garbage_falls_back_to_default(yaml_file, make_task):
    tpl = _dormant_daily(yaml_file, make_task)
    x(f"task {RC_ON} rc.recurrence.catchup.limit=abc list", yaml_file)
    assert _child_indexes(yaml_file, tpl) == [0, 1]


def test_catchup_cap_is_per_template(yaml_file, make_task):
    from taskpeasant.storage import write_tasks
    a = make_task(description="a", status="recurring", recur="daily",
                  due=iso(now_utc() - timedelta(days=6)))
    b = make_task(description="b", status="recurring", recur="daily",
                  due=iso(now_utc() - timedelta(days=6)))
    write_tasks(yaml_file, [a, b])
    x(f"task {RC_ON} list", yaml_file)
    assert _child_indexes(yaml_file, a) == [0, 1]
    assert _child_indexes(yaml_file, b) == [0, 1]


def test_synthesize_tasks_uncapped_unless_asked(make_task):
    tpl = make_task(status="recurring", recur="daily",
                    due=iso(now_utc() - timedelta(days=6)))
    kids, _ = synthesize_tasks([tpl])       # direct callers: no cap
    assert len(kids) == 8
    kids, _ = synthesize_tasks([tpl], catchup_limit=3)
    assert [int(k.imask) for k in kids] == [0, 1, 2]


def test_no_duplicate_spawning(yaml_file):
    x(f"task {RC_ON} add water due:tomorrow recur:weekly", yaml_file)
    x(f"task {RC_ON} list", yaml_file)
    x(f"task {RC_ON} list", yaml_file)
    x(f"task {RC_ON} next", yaml_file)
    kids = [t for t in read_tasks(yaml_file) if t.parent]
    assert len(kids) == 1


def test_mask_tracks_child_status(yaml_file):
    x(f"task {RC_ON} add chore due:today recur:daily", yaml_file)
    x(f"task {RC_ON} list", yaml_file)
    kids = [t for t in read_tasks(yaml_file) if t.parent]
    first = min(kids, key=lambda t: int(t.imask))
    x(f"task {first.uuid} done", yaml_file)
    x(f"task {RC_ON} list", yaml_file)      # re-sync masks
    tpl = next(t for t in read_tasks(yaml_file) if t.status == "recurring")
    assert tpl.mask.startswith("+")


def test_until_stops_spawning(yaml_file, make_task):
    from taskpeasant.storage import write_tasks
    tpl = make_task(description="short lived", status="recurring",
                    recur="daily", due=iso(now_utc() - timedelta(days=2)),
                    until=iso(now_utc() - timedelta(days=1)))
    write_tasks(yaml_file, [tpl])
    x(f"task {RC_ON} list", yaml_file)
    kids = [t for t in read_tasks(yaml_file) if t.parent == tpl.uuid]
    assert len(kids) == 2      # -2d and -1d only; nothing past until


def test_until_expires_pending_tasks(yaml_file, make_task):
    from taskpeasant.storage import write_tasks
    t = make_task(description="offer expires",
                  until=iso(now_utc() - timedelta(hours=1)))
    write_tasks(yaml_file, [t])
    x(f"task {RC_ON} list", yaml_file)
    assert read_tasks(yaml_file)[0].status == "deleted"


def test_no_synthesis_when_disabled(yaml_file, make_task):
    from taskpeasant.storage import write_tasks
    tpl = make_task(description="frozen", status="recurring",
                    recur="daily", due=iso(now_utc() - timedelta(days=2)))
    write_tasks(yaml_file, [tpl])
    x("task list", yaml_file)               # no rc.recurrence=on
    assert len(read_tasks(yaml_file)) == 1


def test_recurring_status_survives_round_trip(yaml_file, make_task):
    from taskpeasant.storage import write_tasks
    tpl = make_task(description="keeper", status="recurring",
                    recur="weekly", due=iso(now_utc()))
    write_tasks(yaml_file, [tpl])
    t = read_tasks(yaml_file)[0]
    assert t.status == "recurring"          # not coerced to pending
    assert t.recur == "weekly"


def test_recurring_report_and_vtags(yaml_file):
    x(f"task {RC_ON} add rent due:tomorrow recur:monthly", yaml_file)
    x(f"task {RC_ON} list", yaml_file)
    out = x(f"task {RC_ON} recurring", yaml_file)
    assert "rent" in out
    # children carry the CHILD vtag, template PARENT
    kids = x(f"task {RC_ON} +CHILD count", yaml_file)
    assert kids == "1"


def test_synthesized_children_visible_in_next(yaml_file):
    x(f"task {RC_ON} add water plants due:today recur:weekly", yaml_file)
    out = x(f"task {RC_ON} next", yaml_file)
    assert "water plants" in out


def test_cli_catchup_cap_is_per_invocation(tmp_path, monkeypatch, make_task):
    """The CLI runs its own recurrence pass before handing some commands
    to the parser; the two must not add up to double the cap."""
    import taskpeasant.__main__ as M
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("XDG_CONFIG_HOME", "TASKPEASANT_CONFIG", "TASKPEASANT_TASKRC",
                "TASKRC", "TASKPEASANT_FILE"):
        monkeypatch.delenv(var, raising=False)
    path = str(tmp_path / "tasks.yaml")
    tpl = _dormant_daily(path, make_task)
    # `count` is delegated to the parser, `list` is rendered by the CLI
    for i, cmd in enumerate(("count", "list"), start=1):
        monkeypatch.setattr("sys.argv", ["tp", "--file", path, RC_ON, cmd])
        M.main()
        assert _child_indexes(path, tpl) == list(range(2 * i))
