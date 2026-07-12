"""Tests for the frozen floor in docs/BACKWARDS_COMPAT.md.

Every test here encodes behavior that cannot change without a MAJOR
version bump.  This file must stay green through every feature phase.
"""

from __future__ import annotations

import inspect
import json

import pytest
import yaml

import taskpeasant
from taskpeasant import Task, execute_command, read_tasks, write_tasks
from taskpeasant.storage import _TP_KEY

from .conftest import (
    SIBLING_KEYS,
    UUID_DONE,
    UUID_OVERDUE,
    UUID_PLAIN,
    seed_tasks,
)


# ── §1 Public symbols ────────────────────────────────────────────────────────

FROZEN_SYMBOLS = [
    "Task", "read_tasks", "write_tasks",
    "cmd_add", "cmd_done", "cmd_delete", "cmd_start", "cmd_stop",
    "cmd_annotate", "cmd_modify", "cmd_export",
    "compute_urgency", "execute_command",
]


def test_frozen_symbols_importable():
    for name in FROZEN_SYMBOLS:
        assert hasattr(taskpeasant, name), f"missing public symbol {name}"


@pytest.mark.parametrize("func,leading_params", [
    ("read_tasks", ["yaml_path"]),
    ("write_tasks", ["yaml_path", "tasks"]),
    ("execute_command", ["raw", "yaml_path"]),
    ("compute_urgency", ["task"]),
    ("cmd_add", ["yaml_path", "description"]),
    ("cmd_done", ["yaml_path", "uuid_prefix"]),
    ("cmd_delete", ["yaml_path", "uuid_prefix"]),
    ("cmd_start", ["yaml_path", "uuid_prefix"]),
    ("cmd_stop", ["yaml_path", "uuid_prefix"]),
    ("cmd_annotate", ["yaml_path", "uuid_prefix", "note"]),
    ("cmd_modify", ["yaml_path", "uuid_prefix", "mods"]),
    ("cmd_export", ["yaml_path"]),
])
def test_frozen_signatures(func, leading_params):
    """Existing positional parameter names and order may not change."""
    sig = inspect.signature(getattr(taskpeasant, func))
    names = list(sig.parameters)
    assert names[:len(leading_params)] == leading_params


# ── §5 CLI grammar floor ─────────────────────────────────────────────────────

def test_add_with_tag_and_dates(yaml_file):
    out = execute_command(
        "task add render the shot +render due:tomorrow scheduled:eom", yaml_file)
    assert "render the shot" in out
    tasks = read_tasks(yaml_file)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.tags == ["render"]
    assert t.due and t.scheduled
    assert t.status == "pending"


@pytest.mark.parametrize("alias", ["today", "tomorrow", "yesterday",
                                   "eow", "eom", "monday"])
def test_required_date_aliases(yaml_file, alias):
    out = execute_command(f"task add alias check due:{alias}", yaml_file)
    assert "Error" not in out
    assert read_tasks(yaml_file)[0].due


def test_uuid_prefix_done(seeded_yaml):
    out = execute_command(f"task {UUID_OVERDUE[:8]} done", seeded_yaml)
    assert "Completed" in out
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_OVERDUE)
    assert t.status == "completed"
    assert t.end
    assert t.start == ""


def test_uuid_prefix_delete(seeded_yaml):
    execute_command(f"task {UUID_PLAIN[:8]} delete", seeded_yaml)
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert t.status == "deleted"
    assert t.end


def test_uuid_prefix_start_stop(seeded_yaml):
    execute_command(f"task {UUID_PLAIN[:8]} start", seeded_yaml)
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert t.start
    execute_command(f"task {UUID_PLAIN[:8]} stop", seeded_yaml)
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert t.start == ""


def test_uuid_prefix_annotate(seeded_yaml):
    execute_command(f"task {UUID_PLAIN[:8]} annotate check the CSS", seeded_yaml)
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert len(t.annotations) == 1
    assert t.annotations[0]["description"] == "check the CSS"
    assert t.annotations[0]["entry"]


def test_uuid_prefix_modify(seeded_yaml):
    execute_command(
        f"task {UUID_PLAIN[:8]} modify +extra -next due:2030-01-01", seeded_yaml)
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert "extra" in t.tags
    assert "next" not in t.tags
    assert t.due.startswith("2030-01-01")


def test_implicit_list_with_filter(seeded_yaml):
    out = execute_command("task +urgent", seeded_yaml)
    assert "ship overdue report" in out
    assert "refactor website nav" not in out


def test_filtered_export_is_tw_wire_json(seeded_yaml):
    out = execute_command("task +urgent export", seeded_yaml)
    data = json.loads(out)
    assert len(data) == 1
    rec = data[0]
    assert rec["uuid"] == UUID_OVERDUE
    assert isinstance(rec["urgency"], float)
    assert rec["is_active"] is False
    # Wire dates: YYYYMMDDTHHMMSSZ
    assert "-" not in rec["entry"]
    assert rec["entry"].endswith("Z")


def test_rc_flags_silently_stripped(seeded_yaml):
    with_rc = execute_command("task rc.gc=off rc.confirmation=off +urgent export",
                              seeded_yaml)
    without = execute_command("task +urgent export", seeded_yaml)
    assert json.loads(with_rc)[0]["uuid"] == json.loads(without)[0]["uuid"]


def test_status_pending_filter_includes_waiting(seeded_yaml):
    # status:pending matching waiting is TW behavior the filter engine must keep
    from taskpeasant.query import apply_filter
    tasks = read_tasks(seeded_yaml)
    matched = apply_filter(tasks, ["status:pending"])
    assert {t.status for t in matched} == {"pending", "waiting"}


@pytest.mark.parametrize("raw", [
    "",
    "task",
    'task add "unclosed quote',
    "task ??? !!! ###",
    "task add",
    "task deadbeef done",
    "task 999 done",
    "task \x00\x01 weird",
    "task modify",
    "task due:not-a-date add thing",
])
def test_execute_command_never_raises(yaml_file, raw):
    out = execute_command(raw, yaml_file)
    assert isinstance(out, str)


# ── §2 Storage key ───────────────────────────────────────────────────────────

def test_sibling_keys_never_touched(seeded_yaml):
    execute_command("task add sibling probe", seeded_yaml)
    execute_command(f"task {UUID_OVERDUE[:8]} done", seeded_yaml)
    doc = yaml.safe_load(open(seeded_yaml, encoding="utf-8"))
    for key, val in SIBLING_KEYS.items():
        assert doc[key] == val, f"sibling key {key!r} was modified"
    assert set(doc) == set(SIBLING_KEYS) | {_TP_KEY}


def test_legacy_tasks_list_read_fallback(tmp_path):
    path = tmp_path / "legacy.yaml"
    legacy = [t.to_dict() for t in seed_tasks()[:2]]
    path.write_text(yaml.dump({"tasks": legacy}), encoding="utf-8")
    tasks = read_tasks(str(path))
    assert {t.uuid for t in tasks} == {d["uuid"] for d in legacy}


def test_legacy_tasks_list_migration_on_write(tmp_path):
    path = tmp_path / "legacy.yaml"
    legacy = [t.to_dict() for t in seed_tasks()[:2]]
    path.write_text(yaml.dump({"tasks": legacy, "other": 1}), encoding="utf-8")
    tasks = read_tasks(str(path))
    write_tasks(str(path), tasks)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["tasks"] == {}, "legacy tasks: must be restored as empty dict"
    assert doc["other"] == 1
    assert {t["uuid"] for t in doc[_TP_KEY]} == {t.uuid for t in tasks}


def test_read_missing_file_returns_empty(yaml_file):
    assert read_tasks(yaml_file) == []


# ── §3 to_dict shape ─────────────────────────────────────────────────────────

def test_to_dict_shape_and_omissions(make_task):
    t = make_task(description="shape check", tags=["a"], depends=["x"],
                  annotations=[{"entry": "2026-01-01T00:00:00Z",
                                "description": "note"}],
                  udas={"custom_field": "kept"})
    d = t.to_dict()
    assert d["uuid"] == t.uuid
    assert d["description"] == "shape check"
    assert d["status"] == "pending"
    assert d["entry"]
    assert d["tags"] == ["a"]
    assert d["depends"] == ["x"]
    assert d["annotations"][0]["description"] == "note"
    assert d["custom_field"] == "kept"       # UDA at top level
    # Empty optionals omitted
    for absent in ("start", "end", "due", "scheduled", "wait",
                   "project", "priority"):
        assert absent not in d
    # ISO with Z, not wire format
    assert "-" in d["entry"] and d["entry"].endswith("Z")


def test_uda_round_trip(make_task):
    t = make_task(udas={"studio_scene": "s04"})
    t2 = Task.from_dict(t.to_dict())
    assert t2.udas == {"studio_scene": "s04"}


def test_unknown_status_coerced_to_pending():
    t = Task.from_dict({"uuid": "u", "description": "d", "status": "recurring"})
    assert t.status == "pending"


# ── §4 to_tw_export shape ────────────────────────────────────────────────────

def test_tw_export_shape(make_task):
    t = make_task(depends=["u1", "u2"], start="2026-01-02T03:04:05Z",
                  udas={"studio_scene": "s04"})
    t.urgency_value = 3.14159
    d = t.to_tw_export()
    assert d["depends"] == "u1,u2"           # comma-string, NOT a list
    assert d["urgency"] == 3.14
    assert d["is_active"] is True
    assert d["start"] == "20260102T030405Z"  # wire format
    assert d["studio_scene"] == "s04"


# ── §6 Urgency range ─────────────────────────────────────────────────────────

def test_urgency_clamped_and_in_range(make_task):
    from taskpeasant import compute_urgency
    from .conftest import iso, now_utc
    from datetime import timedelta

    blocked = make_task(depends=["other"])
    assert compute_urgency(blocked) >= 0.0

    heavy = make_task(
        start=iso(now_utc()),
        due=iso(now_utc() - timedelta(days=3)),
        priority="H",
        tags=["urgent", "next"],
        annotations=[{"entry": "e", "description": "d"}] * 5,
    )
    score = compute_urgency(heavy)
    assert 0.0 <= score <= 50.0
    assert score > 20.0  # active+overdue+H+urgent stack near the top of range

    done = make_task(status="completed")
    assert compute_urgency(done) == 0.0


# ── §7 Status enum ───────────────────────────────────────────────────────────

def test_valid_statuses_frozen():
    from taskpeasant.task_model import _VALID_STATUSES
    assert _VALID_STATUSES == frozenset(
        ["pending", "completed", "deleted", "waiting"])
