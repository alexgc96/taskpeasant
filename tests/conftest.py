"""Shared fixtures for the TaskPeasant test suite."""

from __future__ import annotations

import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from taskpeasant import storage
from taskpeasant.task_model import Task


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_task(**kw) -> Task:
    defaults = dict(
        uuid=str(_uuid_mod.uuid4()),
        description="a task",
        status="pending",
        entry=iso(now_utc() - timedelta(days=1)),
        modified=iso(now_utc() - timedelta(days=1)),
    )
    defaults.update(kw)
    return Task(**defaults)


@pytest.fixture(autouse=True)
def _clear_id_cache():
    """The ephemeral-ID cache is keyed by (path, mtime); clear it between
    tests so one test's ordering can never leak into another."""
    storage._id_cache.clear()
    yield
    storage._id_cache.clear()


@pytest.fixture
def yaml_file(tmp_path):
    """Path to a not-yet-existing tasks YAML inside a temp dir."""
    return str(tmp_path / "tasks.yaml")


@pytest.fixture
def make_task():
    return _make_task


# Sibling top-level keys that TaskPeasant must never touch.  `tasks:` as a
# mapping is the load-bearing case from BACKWARDS_COMPAT.md §2.
SIBLING_KEYS = {
    "studio_meta": {"name": "test project", "version": 3},
    "tasks": {"context": "work", "labels": ["a", "b"]},
}

# Stable UUIDs so tests can address tasks by prefix.
UUID_OVERDUE = "aaaa1111-0000-4000-8000-000000000001"
UUID_SOON = "bbbb2222-0000-4000-8000-000000000002"
UUID_PLAIN = "cccc3333-0000-4000-8000-000000000003"
UUID_DONE = "dddd4444-0000-4000-8000-000000000004"
UUID_WAITING = "eeee5555-0000-4000-8000-000000000005"
UUID_DELETED = "ffff6666-0000-4000-8000-000000000006"


def seed_tasks() -> list:
    """A known task graph with mixed statuses, tags, projects, dates and a
    depends chain (UUID_SOON depends on UUID_OVERDUE)."""
    now = now_utc()
    return [
        _make_task(
            uuid=UUID_OVERDUE,
            description="ship overdue report",
            due=iso(now - timedelta(days=2)),
            tags=["urgent"],
            project="film",
            priority="H",
        ),
        _make_task(
            uuid=UUID_SOON,
            description="colour grade reel",
            due=iso(now + timedelta(days=1)),
            depends=[UUID_OVERDUE],
            project="film",
        ),
        _make_task(
            uuid=UUID_PLAIN,
            description="refactor website nav",
            tags=["next"],
            project="web",
        ),
        _make_task(
            uuid=UUID_DONE,
            description="book studio time",
            status="completed",
            end=iso(now - timedelta(days=1)),
        ),
        _make_task(
            uuid=UUID_WAITING,
            description="follow up with lab",
            status="waiting",
            wait=iso(now + timedelta(days=30)),
        ),
        _make_task(
            uuid=UUID_DELETED,
            description="cancelled shoot",
            status="deleted",
            end=iso(now - timedelta(days=3)),
        ),
    ]


@pytest.fixture
def seeded_yaml(tmp_path):
    """YAML file pre-populated with the seed graph plus sibling keys."""
    path = tmp_path / "seeded.yaml"
    doc = dict(SIBLING_KEYS)
    doc["taskpeasant_tasks"] = [t.to_dict() for t in seed_tasks()]
    path.write_text(yaml.dump(doc, default_flow_style=False, sort_keys=False),
                    encoding="utf-8")
    return str(path)
