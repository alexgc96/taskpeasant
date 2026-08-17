"""Empty-value clearing semantics in modify (TW convention)."""

from __future__ import annotations

from taskpeasant import execute_command, read_tasks

from .conftest import UUID_OVERDUE, UUID_PLAIN, UUID_WAITING


def get(seeded_yaml, uuid):
    return next(t for t in read_tasks(seeded_yaml) if t.uuid == uuid)


def test_clear_due(seeded_yaml):
    out = execute_command(f"task {UUID_OVERDUE[:8]} modify due:", seeded_yaml)
    assert not out.startswith("Error")
    assert get(seeded_yaml, UUID_OVERDUE).due == ""


def test_clear_scheduled(seeded_yaml):
    execute_command(f"task {UUID_PLAIN[:8]} modify scheduled:2030-01-01",
                    seeded_yaml)
    assert get(seeded_yaml, UUID_PLAIN).scheduled
    execute_command(f"task {UUID_PLAIN[:8]} modify scheduled:", seeded_yaml)
    assert get(seeded_yaml, UUID_PLAIN).scheduled == ""


def test_clear_wait_releases_waiting_task(seeded_yaml):
    assert get(seeded_yaml, UUID_WAITING).status == "waiting"
    execute_command(f"task {UUID_WAITING[:8]} modify wait:", seeded_yaml)
    t = get(seeded_yaml, UUID_WAITING)
    assert t.wait == ""
    assert t.status == "pending"


def test_clear_project_and_priority(seeded_yaml):
    execute_command(f"task {UUID_OVERDUE[:8]} modify project: priority:",
                    seeded_yaml)
    t = get(seeded_yaml, UUID_OVERDUE)
    assert t.project == ""
    assert t.priority == ""


def test_blank_description_rejected(seeded_yaml):
    before = get(seeded_yaml, UUID_PLAIN).description
    out = execute_command(f'task {UUID_PLAIN[:8]} modify description:""',
                          seeded_yaml)
    assert out.startswith("Error")
    assert get(seeded_yaml, UUID_PLAIN).description == before


def test_empty_uda_value_deletes_key(seeded_yaml):
    execute_command(f"task {UUID_PLAIN[:8]} modify studio_scene:s04",
                    seeded_yaml)
    assert get(seeded_yaml, UUID_PLAIN).udas["studio_scene"] == "s04"
    execute_command(f"task {UUID_PLAIN[:8]} modify studio_scene:", seeded_yaml)
    assert "studio_scene" not in get(seeded_yaml, UUID_PLAIN).udas


def test_nonempty_dates_still_validated(seeded_yaml):
    out = execute_command(f"task {UUID_PLAIN[:8]} modify due:garbage",
                          seeded_yaml)
    assert "not a recognised date" in out
