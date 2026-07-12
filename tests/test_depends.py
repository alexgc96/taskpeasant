"""depends: wiring — ID/prefix resolution, add/remove/clear, cycle guard."""

from __future__ import annotations

from taskpeasant import execute_command, read_tasks
from taskpeasant.storage import assign_ids

from .conftest import UUID_OVERDUE, UUID_PLAIN, UUID_SOON


def get(path, uuid):
    return next(t for t in read_tasks(path) if t.uuid == uuid)


def test_add_dep_by_uuid_prefix(seeded_yaml):
    out = execute_command(
        f"task {UUID_PLAIN[:8]} modify depends:{UUID_OVERDUE[:8]}", seeded_yaml)
    assert not out.startswith("Error")
    assert get(seeded_yaml, UUID_PLAIN).depends == [UUID_OVERDUE]


def test_add_dep_by_integer_id(seeded_yaml):
    tasks = read_tasks(seeded_yaml)
    assign_ids(seeded_yaml, tasks)
    target_id = next(t.id for t in tasks if t.uuid == UUID_OVERDUE)
    out = execute_command(
        f"task {UUID_PLAIN[:8]} modify depends:{target_id}", seeded_yaml)
    assert not out.startswith("Error")
    assert get(seeded_yaml, UUID_PLAIN).depends == [UUID_OVERDUE]


def test_remove_dep(seeded_yaml):
    # UUID_SOON already depends on UUID_OVERDUE (seed graph)
    out = execute_command(
        f"task {UUID_SOON[:8]} modify depends:-{UUID_OVERDUE[:8]}", seeded_yaml)
    assert not out.startswith("Error")
    assert get(seeded_yaml, UUID_SOON).depends == []


def test_clear_all_deps(seeded_yaml):
    execute_command(f"task {UUID_SOON[:8]} modify depends:", seeded_yaml)
    assert get(seeded_yaml, UUID_SOON).depends == []


def test_self_dependency_rejected(seeded_yaml):
    out = execute_command(
        f"task {UUID_PLAIN[:8]} modify depends:{UUID_PLAIN[:8]}", seeded_yaml)
    assert out.startswith("Error")
    assert get(seeded_yaml, UUID_PLAIN).depends == []


def test_cycle_rejected(seeded_yaml):
    # SOON depends on OVERDUE; OVERDUE→SOON would close the loop
    out = execute_command(
        f"task {UUID_OVERDUE[:8]} modify depends:{UUID_SOON[:8]}", seeded_yaml)
    assert "circular" in out
    assert get(seeded_yaml, UUID_OVERDUE).depends == []


def test_unresolvable_ref_rejected_without_write(seeded_yaml):
    before = get(seeded_yaml, UUID_PLAIN).modified
    out = execute_command(
        f"task {UUID_PLAIN[:8]} modify depends:zzzz9999", seeded_yaml)
    assert out.startswith("Error")
    t = get(seeded_yaml, UUID_PLAIN)
    assert t.depends == []
    assert t.modified == before


def test_deps_feed_virtual_tags(seeded_yaml):
    execute_command(
        f"task {UUID_PLAIN[:8]} modify depends:{UUID_OVERDUE[:8]}", seeded_yaml)
    out = execute_command("task +BLOCKED", seeded_yaml)
    assert "refactor website nav" in out


def test_duplicate_dep_not_added_twice(seeded_yaml):
    execute_command(
        f"task {UUID_SOON[:8]} modify depends:{UUID_OVERDUE[:8]}", seeded_yaml)
    assert get(seeded_yaml, UUID_SOON).depends == [UUID_OVERDUE]


def test_programmatic_list_value_still_works(seeded_yaml):
    from taskpeasant import cmd_modify
    out = cmd_modify(seeded_yaml, UUID_PLAIN[:8], {"depends": [UUID_OVERDUE]})
    assert not out.startswith("Error")
    assert get(seeded_yaml, UUID_PLAIN).depends == [UUID_OVERDUE]
