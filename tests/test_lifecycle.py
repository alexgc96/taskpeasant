"""Milestone 6: undo, duplicate, purge, log, append/prepend, denotate,
import, version — single-target and bulk."""

import json
import os

import pytest

from taskpeasant import execute_command, read_tasks
from taskpeasant.storage import write_tasks
from taskpeasant.undo import undo_path


def add(yaml_file, text):
    return execute_command(f"task add {text}", yaml_file)


def uuid_of(yaml_file, word):
    return next(t.uuid for t in read_tasks(yaml_file)
                if word in t.description)


# ── undo ──────────────────────────────────────────────────────────────────────

def test_undo_add_removes_task(yaml_file):
    add(yaml_file, "ephemeral thing")
    assert len(read_tasks(yaml_file)) == 1
    out = execute_command("task undo", yaml_file)
    assert "Undid" in out
    assert read_tasks(yaml_file) == []


def test_undo_done_restores_pending(yaml_file):
    add(yaml_file, "toggle me")
    u = uuid_of(yaml_file, "toggle")
    execute_command(f"task {u} done", yaml_file)
    assert read_tasks(yaml_file)[0].status == "completed"
    execute_command("task undo", yaml_file)
    t = read_tasks(yaml_file)[0]
    assert t.status == "pending" and not t.end


def test_undo_modify_restores_fields(yaml_file):
    add(yaml_file, "original desc project:old")
    u = uuid_of(yaml_file, "original")
    execute_command(f"task {u} modify project:new +tagged", yaml_file)
    execute_command("task undo", yaml_file)
    t = read_tasks(yaml_file)[0]
    assert t.project == "old" and t.tags == []


def test_undo_stack_pops_in_order(yaml_file):
    add(yaml_file, "first")
    add(yaml_file, "second")
    execute_command("task undo", yaml_file)
    descs = [t.description for t in read_tasks(yaml_file)]
    assert descs == ["first"]


def test_undo_purge_restores_task(yaml_file):
    add(yaml_file, "victim")
    u = uuid_of(yaml_file, "victim")
    execute_command(f"task {u} delete", yaml_file)
    execute_command(f"task {u} purge", yaml_file)
    assert read_tasks(yaml_file) == []
    execute_command("task undo", yaml_file)
    assert read_tasks(yaml_file)[0].description == "victim"


def test_undo_empty_journal(yaml_file):
    assert "No operations to undo." in execute_command("task undo", yaml_file)


def test_undo_sidecar_not_in_tasks_yaml(yaml_file):
    add(yaml_file, "journal check")
    assert os.path.isfile(undo_path(yaml_file))
    import yaml as _yaml
    raw = _yaml.safe_load(open(yaml_file, encoding="utf-8"))
    assert set(raw.keys()) == {"taskpeasant_tasks"}


# ── duplicate ─────────────────────────────────────────────────────────────────

def test_duplicate(yaml_file):
    add(yaml_file, "template +work project:film due:tomorrow priority:H")
    u = uuid_of(yaml_file, "template")
    out = execute_command(f"task {u} duplicate", yaml_file)
    assert "Duplicated" in out
    tasks = read_tasks(yaml_file)
    assert len(tasks) == 2
    orig, dup = tasks
    assert dup.uuid != orig.uuid
    assert dup.description == orig.description
    assert dup.tags == orig.tags and dup.project == orig.project
    assert dup.status == "pending" and not dup.start and not dup.end


def test_duplicate_of_completed_is_pending(yaml_file):
    add(yaml_file, "recycle me")
    u = uuid_of(yaml_file, "recycle")
    execute_command(f"task {u} done", yaml_file)
    execute_command(f"task {u} duplicate", yaml_file)
    statuses = sorted(t.status for t in read_tasks(yaml_file))
    assert statuses == ["completed", "pending"]


# ── purge ─────────────────────────────────────────────────────────────────────

def test_purge_requires_deleted(yaml_file):
    add(yaml_file, "still alive")
    u = uuid_of(yaml_file, "alive")
    out = execute_command(f"task {u} purge", yaml_file)
    assert "not deleted" in out
    assert len(read_tasks(yaml_file)) == 1


def test_purge_all_deleted(yaml_file):
    add(yaml_file, "keep me")
    add(yaml_file, "trash one")
    add(yaml_file, "trash two")
    for word in ("one", "two"):
        u = uuid_of(yaml_file, word)
        execute_command(f"task {u} delete", yaml_file)
    out = execute_command("task purge", yaml_file)
    assert "Purged 2 tasks" in out
    remaining = read_tasks(yaml_file)
    assert [t.description for t in remaining] == ["keep me"]


def test_purge_clears_dangling_depends(yaml_file):
    add(yaml_file, "dep target")
    add(yaml_file, "dependent")
    dep = uuid_of(yaml_file, "target")
    d = uuid_of(yaml_file, "dependent")
    execute_command(f"task {d} modify depends:{dep}", yaml_file)
    execute_command(f"task {dep} delete", yaml_file)
    execute_command("task purge", yaml_file)
    t = read_tasks(yaml_file)[0]
    assert t.depends == []


# ── log ───────────────────────────────────────────────────────────────────────

def test_log_creates_completed(yaml_file):
    out = execute_command("task log emergency fix +ops project:infra",
                          yaml_file)
    assert "Logged" in out
    t = read_tasks(yaml_file)[0]
    assert t.status == "completed" and t.end
    assert t.tags == ["ops"] and t.project == "infra"


# ── append / prepend / denotate ───────────────────────────────────────────────

def test_append_prepend(yaml_file):
    add(yaml_file, "core")
    u = uuid_of(yaml_file, "core")
    execute_command(f"task {u} append tail", yaml_file)
    execute_command(f"task {u} prepend head", yaml_file)
    assert read_tasks(yaml_file)[0].description == "head core tail"


def test_append_requires_text(yaml_file):
    add(yaml_file, "core")
    u = uuid_of(yaml_file, "core")
    assert "Error" in execute_command(f"task {u} append", yaml_file)


def test_denotate_pattern(yaml_file):
    add(yaml_file, "noted")
    u = uuid_of(yaml_file, "noted")
    execute_command(f"task {u} annotate first note", yaml_file)
    execute_command(f"task {u} annotate second note", yaml_file)
    execute_command(f"task {u} denotate first", yaml_file)
    anns = read_tasks(yaml_file)[0].annotations
    assert len(anns) == 1 and "second" in anns[0]["description"]


def test_denotate_all_without_pattern(yaml_file):
    add(yaml_file, "noted")
    u = uuid_of(yaml_file, "noted")
    execute_command(f"task {u} annotate a", yaml_file)
    execute_command(f"task {u} annotate b", yaml_file)
    execute_command(f"task {u} denotate", yaml_file)
    assert read_tasks(yaml_file)[0].annotations == []


# ── bulk forms ────────────────────────────────────────────────────────────────

def test_bulk_append(yaml_file):
    add(yaml_file, "one +batch")
    add(yaml_file, "two +batch")
    out = execute_command("task +batch append (reviewed)", yaml_file)
    assert "2 task" in out
    for t in read_tasks(yaml_file):
        assert t.description.endswith("(reviewed)")


def test_bulk_duplicate(yaml_file):
    add(yaml_file, "a +copy")
    add(yaml_file, "b +copy")
    execute_command("task +copy duplicate", yaml_file)
    assert len(read_tasks(yaml_file)) == 4


def test_bulk_purge_skips_undeleted(yaml_file):
    add(yaml_file, "alive +x")
    add(yaml_file, "dead +x")
    u = uuid_of(yaml_file, "dead")
    execute_command(f"task {u} delete", yaml_file)
    out = execute_command("task +x purge", yaml_file)
    assert "1 task" in out and "skipped" in out
    remaining = read_tasks(yaml_file)
    assert [t.description for t in remaining] == ["alive"]


# ── import ────────────────────────────────────────────────────────────────────

def test_import_tw_wire_json(yaml_file):
    payload = json.dumps([{
        "uuid": "11111111-2222-3333-4444-555555555555",
        "description": "imported from TW",
        "status": "pending",
        "entry": "20260101T120000Z",
        "due": "20260201T000000Z",
        "tags": ["migrated"],
        "urgency": 3.2,
        "id": 7,
    }])
    out = execute_command(f"task import {payload}", yaml_file)
    assert "1 new" in out
    t = read_tasks(yaml_file)[0]
    assert t.description == "imported from TW"
    assert t.entry == "2026-01-01T12:00:00Z"      # wire → ISO storage
    assert t.due == "2026-02-01T00:00:00Z"
    assert t.tags == ["migrated"]
    assert "urgency" not in t.udas and "id" not in t.udas


def test_import_updates_existing_by_uuid(yaml_file):
    add(yaml_file, "old version")
    u = read_tasks(yaml_file)[0].uuid
    payload = json.dumps([{"uuid": u, "description": "new version",
                           "status": "pending",
                           "entry": "20260101T120000Z"}])
    out = execute_command(f"task import {payload}", yaml_file)
    assert "1 updated" in out
    tasks = read_tasks(yaml_file)
    assert len(tasks) == 1 and tasks[0].description == "new version"


def test_import_line_delimited(yaml_file):
    lines = "\n".join(json.dumps({"uuid": f"aaaaaaa{i}-1111-2222-3333-444444444444",
                                  "description": f"line {i}",
                                  "status": "pending",
                                  "entry": "20260101T120000Z"})
                      for i in range(3))
    out = execute_command(f"task import {lines}", yaml_file)
    assert "3 new" in out


def test_import_invalid_json(yaml_file):
    assert "Error" in execute_command("task import {nope", yaml_file)


def test_import_undoable(yaml_file):
    payload = json.dumps([{"uuid": "99999999-1111-2222-3333-444444444444",
                           "description": "temp import",
                           "status": "pending",
                           "entry": "20260101T120000Z"}])
    execute_command(f"task import {payload}", yaml_file)
    execute_command("task undo", yaml_file)
    assert read_tasks(yaml_file) == []


# ── version ───────────────────────────────────────────────────────────────────

def test_version(yaml_file):
    out = execute_command("task version", yaml_file)
    assert out.startswith("taskpeasant ")
