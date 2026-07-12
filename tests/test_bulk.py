"""Bulk filter operations: `task <filter> <verb>`."""

from __future__ import annotations

import pytest

from taskpeasant import commands, execute_command, read_tasks

from .conftest import UUID_DONE, UUID_OVERDUE, UUID_PLAIN, UUID_SOON


def by_uuid(path):
    return {t.uuid: t for t in read_tasks(path)}


def test_bulk_done_by_project(seeded_yaml):
    out = execute_command("task project:film done", seeded_yaml)
    assert out.startswith("Completed 2 task(s)")
    tasks = by_uuid(seeded_yaml)
    assert tasks[UUID_OVERDUE].status == "completed"
    assert tasks[UUID_SOON].status == "completed"
    assert tasks[UUID_PLAIN].status == "pending"


def test_bulk_done_by_tag(seeded_yaml):
    out = execute_command("task +urgent done", seeded_yaml)
    assert "Completed 1 task(s)" in out
    assert by_uuid(seeded_yaml)[UUID_OVERDUE].status == "completed"


def test_bulk_with_expression_filter(seeded_yaml):
    out = execute_command("task (+urgent or +next) done", seeded_yaml)
    assert "Completed 2 task(s)" in out


def test_bulk_virtual_tag_filter(seeded_yaml):
    out = execute_command("task +OVERDUE done", seeded_yaml)
    assert "Completed 1 task(s)" in out
    assert by_uuid(seeded_yaml)[UUID_OVERDUE].status == "completed"


def test_bare_verb_is_not_bulk(seeded_yaml):
    # `task done` must stay a description search, never a filterless bulk
    before = {u: t.status for u, t in by_uuid(seeded_yaml).items()}
    out = execute_command("task done", seeded_yaml)
    assert not out.startswith("Completed")
    after = {u: t.status for u, t in by_uuid(seeded_yaml).items()}
    assert before == after


def test_single_id_path_unchanged(seeded_yaml):
    out = execute_command(f"task {UUID_OVERDUE[:8]} done", seeded_yaml)
    assert out.startswith("Completed task")   # single-target message shape


def test_skip_counts(seeded_yaml):
    # UUID_DONE is already completed; status-wide bulk skips it
    out = execute_command("task status:completed done", seeded_yaml)
    assert "0 task" in out and "skipped" in out


def test_zero_matches_no_write(seeded_yaml, monkeypatch):
    writes = []
    monkeypatch.setattr(commands, "write_tasks",
                        lambda *a, **k: writes.append(a))
    out = execute_command("task +nosuchtag done", seeded_yaml)
    assert out == "No matching tasks."
    assert writes == []


def test_bulk_uses_single_write(seeded_yaml, monkeypatch):
    from taskpeasant.storage import write_tasks as real_write
    calls = []

    def counting_write(path, tasks):
        calls.append(1)
        real_write(path, tasks)

    monkeypatch.setattr(commands, "write_tasks", counting_write)
    execute_command("task project:film done", seeded_yaml)
    assert len(calls) == 1


def test_bulk_modify(seeded_yaml):
    out = execute_command("task project:film modify +reviewed priority:L",
                          seeded_yaml)
    assert out.startswith("Modified 2 task(s)")
    tasks = by_uuid(seeded_yaml)
    for u in (UUID_OVERDUE, UUID_SOON):
        assert "reviewed" in tasks[u].tags
        assert tasks[u].priority == "L"


def test_bulk_annotate(seeded_yaml):
    out = execute_command("task project:film annotate needs colour pass",
                          seeded_yaml)
    assert out.startswith("Annotated 2 task(s)")
    t = by_uuid(seeded_yaml)[UUID_SOON]
    assert t.annotations[-1]["description"] == "needs colour pass"


def test_bulk_start_stop(seeded_yaml):
    execute_command("task project:film start", seeded_yaml)
    assert all(by_uuid(seeded_yaml)[u].start for u in (UUID_OVERDUE, UUID_SOON))
    out = execute_command("task project:film start", seeded_yaml)
    assert "skipped" in out   # already active
    execute_command("task project:film stop", seeded_yaml)
    assert not any(by_uuid(seeded_yaml)[u].start
                   for u in (UUID_OVERDUE, UUID_SOON))


def test_trailing_args_after_simple_verb_error(seeded_yaml):
    out = execute_command("task +urgent done extra words", seeded_yaml)
    assert out.startswith("Error")
    assert by_uuid(seeded_yaml)[UUID_OVERDUE].status == "pending"


def test_unrecognised_filter_token_refused(seeded_yaml):
    # 'due:2030' compiles to no predicate; bulk must refuse, not match all
    out = execute_command("task due:2030 done", seeded_yaml)
    assert out.startswith("Error")
    statuses = {t.status for t in read_tasks(seeded_yaml)}
    assert "pending" in statuses


def test_bulk_modify_error_aborts_all(seeded_yaml, monkeypatch):
    writes = []
    monkeypatch.setattr(commands, "write_tasks",
                        lambda *a, **k: writes.append(a))
    out = execute_command("task project:film modify depends:zzzz", seeded_yaml)
    assert out.startswith("Error")
    assert writes == []


def test_bulk_delete(seeded_yaml):
    out = execute_command("task project:web delete", seeded_yaml)
    assert out.startswith("Deleted 1 task(s)")
    assert by_uuid(seeded_yaml)[UUID_PLAIN].status == "deleted"
