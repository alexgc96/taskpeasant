"""UrgencyConfig: defaults, legacy WEIGHTS path, blocking bonus, cache key."""

from __future__ import annotations

from datetime import timedelta

from taskpeasant import (DEFAULT_CONFIG, UrgencyConfig, compute_urgency,
                         read_tasks)
from taskpeasant._vtags import annotate_virtual_tags
from taskpeasant.storage import assign_ids
from taskpeasant.urgency import WEIGHTS

from .conftest import iso, now_utc


def test_default_config_matches_weights():
    assert UrgencyConfig.from_weights(WEIGHTS) == DEFAULT_CONFIG


def test_explicit_urgency_config_selects_legacy_model(make_task):
    # Since 0.4.0 the *default* call runs the TW polynomial; passing an
    # UrgencyConfig instance is the frozen seam that pins the pre-0.4
    # additive model.
    t = make_task(due=iso(now_utc() - timedelta(days=1)), priority="H",
                  tags=["urgent"])
    legacy = compute_urgency(t, DEFAULT_CONFIG)
    # additive: overdue 12 + H 6 + urgent 6 + age 0.01/day
    assert 24.0 <= legacy <= 24.1
    assert compute_urgency(t) != legacy   # default = TW polynomial


def test_live_weights_mutation_still_honoured(make_task):
    # Mutating WEIGHTS opts the *default* call back into the additive model
    t = make_task(tags=["urgent"])
    legacy_base = compute_urgency(t, UrgencyConfig.from_weights(WEIGHTS))
    old = WEIGHTS["tag_urgent"]
    try:
        WEIGHTS["tag_urgent"] = old + 10.0
        assert compute_urgency(t) == round(legacy_base + 10.0, 2)
    finally:
        WEIGHTS["tag_urgent"] = old


def test_explicit_config_overrides(make_task):
    t = make_task(priority="H")
    custom = UrgencyConfig(priority={"H": 10.0, "M": 3.9, "L": 1.8})
    assert compute_urgency(t, custom) - compute_urgency(t, DEFAULT_CONFIG) \
        == 4.0


def test_blocking_bonus_only_when_annotated(make_task):
    blocker = make_task(description="blocker")
    blocked = make_task(description="blocked", depends=[blocker.uuid])

    # Un-annotated: legacy behavior — no blocking bonus, presence penalty
    plain = compute_urgency(blocker, DEFAULT_CONFIG)
    assert compute_urgency(blocked, DEFAULT_CONFIG) == max(
        0.0, round(plain + WEIGHTS["blocked"], 2))

    annotate_virtual_tags([blocker, blocked])
    assert compute_urgency(blocker, DEFAULT_CONFIG) == \
        round(plain + WEIGHTS["blocking"], 2)


def test_blocked_uses_graph_not_presence_when_annotated(make_task):
    done_dep = make_task(status="completed")
    t = make_task(depends=[done_dep.uuid])
    unblocked_score = compute_urgency(make_task(), DEFAULT_CONFIG)
    annotate_virtual_tags([done_dep, t])
    # dep completed → not BLOCKED → no penalty
    assert compute_urgency(t, DEFAULT_CONFIG) == unblocked_score


def test_clamped_at_zero(make_task):
    blocker = make_task()
    t = make_task(depends=[blocker.uuid])
    annotate_virtual_tags([blocker, t])
    assert compute_urgency(t, UrgencyConfig(blocked=-100.0)) == 0.0


def test_assign_ids_cache_keyed_per_config(seeded_yaml):
    tasks = read_tasks(seeded_yaml)
    assign_ids(seeded_yaml, tasks)
    default_order = {t.uuid: t.id for t in tasks if t.id}

    # A config that inverts priorities should be able to produce a
    # different ordering — and must not reuse the default cache entry.
    flipped = UrgencyConfig(active=0.0, overdue=-12.0, tag_urgent=-6.0,
                            priority={"H": -6.0, "M": 0.0, "L": 6.0})
    tasks2 = read_tasks(seeded_yaml)
    assign_ids(seeded_yaml, tasks2, flipped)
    flipped_order = {t.uuid: t.id for t in tasks2 if t.id}
    assert default_order != flipped_order


def test_from_weights_ignores_unknown_keys():
    cfg = UrgencyConfig.from_weights({"tag_urgent": 9.0, "bogus": 1.0})
    assert cfg.tag_urgent == 9.0
    assert cfg.overdue == DEFAULT_CONFIG.overdue
