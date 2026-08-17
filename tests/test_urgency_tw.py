"""Milestone 4: the TW urgency polynomial (port of Task::urgency_c)."""

from datetime import timedelta

import pytest

from taskpeasant import compute_urgency
from taskpeasant._taskrc import Taskrc
from taskpeasant._vtags import annotate_virtual_tags
from taskpeasant.urgency import (_due_measure, _tiered_measure,
                                 apply_inherited_urgency)
from tests.conftest import iso, now_utc


def fresh_task(make_task, **kw):
    """A task with zero age contribution (entry=now)."""
    kw.setdefault("entry", iso(now_utc()))
    return make_task(**kw)


# ── Individual factors ────────────────────────────────────────────────────────

def test_baseline_is_near_zero(make_task):
    assert compute_urgency(fresh_task(make_task)) == 0.0


def test_active_coefficient(make_task):
    t = fresh_task(make_task, start=iso(now_utc()))
    assert compute_urgency(t) == pytest.approx(4.0, abs=0.02)


def test_priority_coefficients(make_task):
    assert compute_urgency(fresh_task(make_task, priority="H")) == \
        pytest.approx(6.0, abs=0.02)
    assert compute_urgency(fresh_task(make_task, priority="M")) == \
        pytest.approx(3.9, abs=0.02)
    assert compute_urgency(fresh_task(make_task, priority="L")) == \
        pytest.approx(1.8, abs=0.02)


def test_next_tag_is_15(make_task):
    t = fresh_task(make_task, tags=["next"])
    # 15.0 (user.tag.next) + 0.8 (one tag measure × tags coefficient)
    assert compute_urgency(t) == pytest.approx(15.8, abs=0.02)


def test_tags_tiered_measure(make_task):
    one   = fresh_task(make_task, tags=["a"])
    two   = fresh_task(make_task, tags=["a", "b"])
    three = fresh_task(make_task, tags=["a", "b", "c"])
    four  = fresh_task(make_task, tags=["a", "b", "c", "d"])
    assert compute_urgency(one) == pytest.approx(0.8, abs=0.02)
    assert compute_urgency(two) == pytest.approx(0.9, abs=0.02)
    assert compute_urgency(three) == pytest.approx(1.0, abs=0.02)
    assert compute_urgency(four) == compute_urgency(three)


def test_annotations_tiered(make_task):
    ann = [{"entry": "e", "description": "d"}]
    assert compute_urgency(fresh_task(make_task, annotations=ann * 1)) == \
        pytest.approx(0.8, abs=0.02)
    assert compute_urgency(fresh_task(make_task, annotations=ann * 5)) == \
        pytest.approx(1.0, abs=0.02)


def test_project_coefficient(make_task):
    t = fresh_task(make_task, project="film")
    assert compute_urgency(t) == pytest.approx(1.0, abs=0.02)


def test_waiting_negative(make_task):
    t = fresh_task(make_task, status="waiting",
                   wait=iso(now_utc() + timedelta(days=5)), priority="H")
    # 6.0 (H) - 3.0 (waiting) = 3.0
    assert compute_urgency(t) == pytest.approx(3.0, abs=0.02)


def test_scheduled_counts_only_once_arrived(make_task):
    future = fresh_task(make_task,
                        scheduled=iso(now_utc() + timedelta(days=2)))
    past   = fresh_task(make_task,
                        scheduled=iso(now_utc() - timedelta(days=2)))
    assert compute_urgency(future) == 0.0
    assert compute_urgency(past) == pytest.approx(5.0, abs=0.02)


# ── Due ramp ──────────────────────────────────────────────────────────────────

def test_due_measure_ramp():
    now = now_utc()
    assert _due_measure(now - timedelta(days=10), now) == 1.0     # way overdue
    assert _due_measure(now - timedelta(days=7), now) == 1.0      # 7d overdue
    assert _due_measure(now, now) == pytest.approx(0.7333, abs=0.01)
    assert _due_measure(now + timedelta(days=14), now) == \
        pytest.approx(0.2, abs=0.01)
    assert _due_measure(now + timedelta(days=30), now) == 0.2     # far future


def test_due_urgency_scales_with_coefficient(make_task):
    overdue = fresh_task(make_task, due=iso(now_utc() - timedelta(days=10)))
    assert compute_urgency(overdue) == pytest.approx(12.0, abs=0.05)


# ── Graph factors ─────────────────────────────────────────────────────────────

def test_blocking_is_8_blocked_is_minus_5(make_task):
    blocker = fresh_task(make_task, priority="H")
    blocked = fresh_task(make_task, priority="H", depends=[blocker.uuid])
    annotate_virtual_tags([blocker, blocked])
    assert compute_urgency(blocker) == pytest.approx(6.0 + 8.0, abs=0.05)
    assert compute_urgency(blocked) == pytest.approx(6.0 - 5.0, abs=0.05)


# ── Config-driven coefficients ────────────────────────────────────────────────

def test_taskrc_coefficient_override(make_task):
    t = fresh_task(make_task, start=iso(now_utc()))
    conf = Taskrc({"urgency.active.coefficient": "20.0"})
    assert compute_urgency(t, conf) == pytest.approx(20.0, abs=0.02)


def test_user_tag_coefficient(make_task):
    t = fresh_task(make_task, tags=["mytag"])
    conf = Taskrc({"urgency.user.tag.mytag.coefficient": "9.0"})
    assert compute_urgency(t, conf) == pytest.approx(9.8, abs=0.02)


def test_user_project_coefficient(make_task):
    t = fresh_task(make_task, project="film")
    conf = Taskrc({"urgency.user.project.film.coefficient": "5.0"})
    # 1.0 project presence + 5.0 user bonus
    assert compute_urgency(t, conf) == pytest.approx(6.0, abs=0.02)


def test_user_keyword_coefficient(make_task):
    t = fresh_task(make_task, description="fix the boiler")
    conf = Taskrc({"urgency.user.keyword.boiler.coefficient": "4.0"})
    assert compute_urgency(t, conf) == pytest.approx(4.0, abs=0.02)


def test_uda_value_coefficient(make_task):
    t = fresh_task(make_task, udas={"size": "xl"})
    conf = Taskrc({"urgency.uda.size.xl.coefficient": "3.0"})
    assert compute_urgency(t, conf) == pytest.approx(3.0, abs=0.02)
    other = fresh_task(make_task, udas={"size": "s"})
    assert compute_urgency(other, conf) == 0.0


def test_uda_presence_coefficient(make_task):
    t = fresh_task(make_task, udas={"estimate": "3h"})
    conf = Taskrc({"urgency.uda.estimate.coefficient": "2.5"})
    assert compute_urgency(t, conf) == pytest.approx(2.5, abs=0.02)


# ── Age ───────────────────────────────────────────────────────────────────────

def test_age_full_measure_at_max(make_task):
    old = make_task(entry=iso(now_utc() - timedelta(days=400)))
    assert compute_urgency(old) == pytest.approx(2.0, abs=0.02)


def test_age_partial(make_task):
    t = make_task(entry=iso(now_utc() - timedelta(days=182)))
    assert compute_urgency(t) == pytest.approx(1.0, abs=0.05)


# ── Clamping / rounding (contract §6) ─────────────────────────────────────────

def test_clamped_at_zero(make_task):
    blocker = fresh_task(make_task)
    t = fresh_task(make_task, depends=[blocker.uuid])
    annotate_virtual_tags([blocker, t])
    assert compute_urgency(t) == 0.0     # -5 blocked clamps to 0


def test_completed_deleted_zero(make_task):
    assert compute_urgency(make_task(status="completed")) == 0.0
    assert compute_urgency(make_task(status="deleted")) == 0.0


# ── urgency.inherit ───────────────────────────────────────────────────────────

def test_inherit_propagates_max_urgency(make_task):
    urgent  = fresh_task(make_task, priority="H",
                         due=iso(now_utc() - timedelta(days=10)))
    blocker = fresh_task(make_task, depends=[])
    urgent.depends = [blocker.uuid]
    tasks = [urgent, blocker]
    annotate_virtual_tags(tasks)

    conf_off = Taskrc()
    apply_inherited_urgency(tasks, conf_off)
    assert blocker.urgency_value < urgent.urgency_value

    conf_on = Taskrc({"urgency.inherit": "1"})
    apply_inherited_urgency(tasks, conf_on)
    assert blocker.urgency_value >= urgent.urgency_value


def test_tiered_measure_helper():
    assert _tiered_measure(0) == 0.0
    assert _tiered_measure(1) == 0.8
    assert _tiered_measure(2) == 0.9
    assert _tiered_measure(3) == 1.0
    assert _tiered_measure(9) == 1.0
