"""Virtual tags: computation truth table, graph tags, and non-persistence."""

from __future__ import annotations

from datetime import timedelta

import yaml

from taskpeasant import execute_command, read_tasks, write_tasks
from taskpeasant._vtags import (VIRTUAL_TAG_NAMES, annotate_virtual_tags,
                                compute_virtual_tags)
from taskpeasant.storage import _TP_KEY, assign_ids

from .conftest import (UUID_DONE, UUID_OVERDUE, UUID_PLAIN, UUID_SOON,
                       UUID_WAITING, iso, now_utc, seed_tasks)


def test_status_tags(make_task):
    assert "PENDING" in compute_virtual_tags(make_task())
    assert "COMPLETED" in compute_virtual_tags(make_task(status="completed"))
    assert "DELETED" in compute_virtual_tags(make_task(status="deleted"))
    assert "WAITING" in compute_virtual_tags(make_task(status="waiting"))


def test_active_requires_pending(make_task):
    started = make_task(start=iso(now_utc()))
    assert "ACTIVE" in compute_virtual_tags(started)
    done = make_task(status="completed", start=iso(now_utc()))
    assert "ACTIVE" not in compute_virtual_tags(done)


def test_due_family(make_task):
    overdue = make_task(due=iso(now_utc() - timedelta(days=1)))
    v = compute_virtual_tags(overdue)
    assert "OVERDUE" in v and "DUE" in v

    later_today = make_task(due=iso(now_utc() + timedelta(minutes=30)))
    v = compute_virtual_tags(later_today)
    # +30min may cross midnight UTC; TODAY only asserted when same date
    if (now_utc() + timedelta(minutes=30)).date() == now_utc().date():
        assert "TODAY" in v
    assert "DUE" in v
    assert "OVERDUE" not in v

    far = make_task(due=iso(now_utc() + timedelta(days=30)))
    v = compute_virtual_tags(far)
    assert not {"DUE", "TODAY", "OVERDUE"} & v

    undated = make_task()
    assert not {"DUE", "TODAY", "OVERDUE"} & compute_virtual_tags(undated)


def test_simple_presence_tags(make_task):
    t = make_task(scheduled=iso(now_utc()), tags=["x"], project="p",
                  annotations=[{"entry": "e", "description": "d"}])
    v = compute_virtual_tags(t)
    assert {"SCHEDULED", "TAGGED", "ANNOTATED", "PROJECT"} <= v
    assert not {"SCHEDULED", "TAGGED", "ANNOTATED", "PROJECT"} & \
        compute_virtual_tags(make_task())


def test_blocked_and_blocking_graph(make_task):
    a = make_task(description="blocker")
    b = make_task(description="blocked", depends=[a.uuid])
    c = make_task(description="bystander")
    annotate_virtual_tags([a, b, c])
    assert "BLOCKING" in a.virtual_tags
    assert "BLOCKED" not in a.virtual_tags
    assert "BLOCKED" in b.virtual_tags
    assert "BLOCKING" not in b.virtual_tags
    assert not {"BLOCKED", "BLOCKING"} & c.virtual_tags


def test_completed_dep_does_not_block(make_task):
    a = make_task(status="completed")
    b = make_task(depends=[a.uuid])
    annotate_virtual_tags([a, b])
    assert "BLOCKED" not in b.virtual_tags
    assert "BLOCKING" not in a.virtual_tags


def test_dangling_dep_does_not_block(make_task):
    b = make_task(depends=["00000000-dead-4000-8000-000000000000"])
    annotate_virtual_tags([b])
    assert "BLOCKED" not in b.virtual_tags


def test_completed_task_never_blocked_or_blocking(make_task):
    a = make_task()
    b = make_task(status="completed", depends=[a.uuid])
    annotate_virtual_tags([a, b])
    assert not {"BLOCKED", "BLOCKING"} & b.virtual_tags


def test_assign_ids_annotates(seeded_yaml):
    tasks = read_tasks(seeded_yaml)
    assign_ids(seeded_yaml, tasks)
    by_uuid = {t.uuid: t for t in tasks}
    assert "OVERDUE" in by_uuid[UUID_OVERDUE].virtual_tags
    assert "BLOCKING" in by_uuid[UUID_OVERDUE].virtual_tags
    assert "BLOCKED" in by_uuid[UUID_SOON].virtual_tags
    assert "COMPLETED" in by_uuid[UUID_DONE].virtual_tags


def test_virtual_tags_never_persisted(seeded_yaml, make_task):
    tasks = read_tasks(seeded_yaml)
    annotate_virtual_tags(tasks)
    write_tasks(seeded_yaml, tasks)
    # Round-trip through a modify as well
    execute_command(f"task {UUID_PLAIN[:8]} modify +real", seeded_yaml)
    raw = open(seeded_yaml, encoding="utf-8").read()
    for name in VIRTUAL_TAG_NAMES:
        assert name not in raw, f"virtual tag {name} leaked into YAML"
    assert "virtual_tags" not in raw

    doc = yaml.safe_load(raw)
    for rec in doc[_TP_KEY]:
        assert "virtual_tags" not in rec
        for tag in rec.get("tags", []):
            assert tag not in VIRTUAL_TAG_NAMES


def test_virtual_tags_not_in_dict_or_export(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=1)))
    annotate_virtual_tags([t])
    assert "virtual_tags" not in t.to_dict()
    d = t.to_tw_export()
    assert "virtual_tags" not in d
    assert "tags" not in d  # no real tags → key omitted entirely


def test_add_virtual_tag_rejected(yaml_file):
    out = execute_command("task add sneaky +OVERDUE", yaml_file)
    assert out.startswith("Error")
    assert read_tasks(yaml_file) == []


def test_modify_virtual_tag_rejected(seeded_yaml):
    out = execute_command(f"task {UUID_PLAIN[:8]} modify +BLOCKED", seeded_yaml)
    assert out.startswith("Error")
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert "BLOCKED" not in t.tags


def test_remove_virtual_tag_is_noop(seeded_yaml):
    out = execute_command(f"task {UUID_PLAIN[:8]} modify -OVERDUE", seeded_yaml)
    assert not out.startswith("Error")
    t = next(t for t in read_tasks(seeded_yaml) if t.uuid == UUID_PLAIN)
    assert "next" in t.tags  # untouched


def test_info_shows_virtual_tags(seeded_yaml):
    out = execute_command(f"task {UUID_OVERDUE[:8]} info", seeded_yaml)
    assert "Virtual tags" in out
    assert "+OVERDUE" in out
