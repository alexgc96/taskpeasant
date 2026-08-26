"""
taskpeasant/urgency.py
Urgency scoring — a port of Taskwarrior's polynomial model.

Since 0.4.0 the default is TW's real formula (ported from src/Task.cpp
urgency_c): each factor is a measure in [0, 1] multiplied by an
`urgency.<factor>.coefficient` from the taskrc config, summed.  The due
factor ramps linearly from 0.2 (14 days early) to 1.0 (7 days overdue).

The pre-0.4 additive model is preserved for backwards compatibility and
is selected automatically whenever a caller:
  - passes an UrgencyConfig instance (the frozen public API), or
  - has mutated the legacy WEIGHTS dict.

Passing a Taskrc instance (or nothing) selects the TW polynomial, with
coefficients read from `urgency.*` keys — including per-value UDA
coefficients (urgency.uda.priority.H.coefficient) and user bonuses
(urgency.user.tag.next.coefficient, urgency.user.project.X.coefficient,
urgency.user.keyword.X.coefficient).

The score is rounded to 2 decimals and clamped >= 0.0 (contract §6);
the range stays ~0-20 for typical tasks, same as Taskwarrior.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from ._taskrc import Taskrc

from .task_model import Task

# ── Legacy additive model (pre-0.4 default — kept live, see docstring) ──────
WEIGHTS = {
    "active":        15.0,   # task has a start timestamp (you're working on it)
    "overdue":       12.0,   # past its due date
    "due_today":      8.0,   # due within 24 hours
    "due_soon":       4.0,   # due within 7 days
    "scheduled":      2.0,   # has a scheduled date (planned work)
    "priority":      {"H": 6.0, "M": 3.9, "L": 1.8},
    "tag_urgent":     6.0,   # tagged +urgent
    "tag_next":       3.5,   # tagged +next
    "annotations":    0.5,   # per annotation (shows engagement) — max 2.0
    "age_per_day":    0.01,  # slight age bonus so old tasks don't rot — max 2.0
    "blocked":       -5.0,   # has unresolved depends (can't act on it yet)
    "blocking":       1.0,   # other tasks depend on this one (unblocks work)
}

# Pristine copy — mutating WEIGHTS is the legacy tuning knob, and doing so
# opts the default compute_urgency() path back into the additive model.
_PRISTINE_WEIGHTS = {k: (dict(v) if isinstance(v, dict) else v)
                     for k, v in WEIGHTS.items()}


@dataclass(frozen=True)
class UrgencyConfig:
    """All *legacy additive* coefficients, one field per factor.

    Passing an instance to compute_urgency()/assign_ids()/cmd_export()
    selects the pre-0.4 additive model with these weights — the seam
    that keeps old embedders' scores byte-identical.
    """
    active:          float = 15.0
    overdue:         float = 12.0
    due_today:       float = 8.0
    due_soon:        float = 4.0
    scheduled:       float = 2.0
    priority:        dict = field(
        default_factory=lambda: {"H": 6.0, "M": 3.9, "L": 1.8})
    tag_urgent:      float = 6.0
    tag_next:        float = 3.5
    annotations:     float = 0.5
    annotations_cap: float = 2.0
    age_per_day:     float = 0.01
    age_cap:         float = 2.0
    blocked:         float = -5.0
    blocking:        float = 1.0

    @classmethod
    def from_weights(cls, weights: Dict[str, Any]) -> "UrgencyConfig":
        """Build a config from a WEIGHTS-style dict; unknown keys ignored,
        missing keys fall back to the dataclass defaults."""
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in weights.items() if k in known}
        if "priority" in kwargs:
            kwargs["priority"] = dict(kwargs["priority"])
        return cls(**kwargs)


DEFAULT_CONFIG = UrgencyConfig()

# Cached default Taskrc — built lazily to avoid import-time cycles
_DEFAULT_RC = None


def _default_rc():
    global _DEFAULT_RC
    if _DEFAULT_RC is None:
        from ._taskrc import Taskrc
        _DEFAULT_RC = Taskrc()
    return _DEFAULT_RC


def _parse_iso(s: str) -> Optional[datetime]:
    """Parse ISO or TW date string → aware datetime, or None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%Y%m%dT%H%M%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ── Public entry point ────────────────────────────────────────────────────────

def compute_urgency(task: Task, config: Union[UrgencyConfig, "Taskrc", None] = None) -> float:
    """Urgency score for a single task; 0.0 for completed/deleted.

    config selects the model:
      None          → TW polynomial with default coefficients — unless the
                      legacy WEIGHTS dict was mutated, which re-selects the
                      pre-0.4 additive model (old tuning path keeps working)
      UrgencyConfig → pre-0.4 additive model with those weights
      Taskrc        → TW polynomial with urgency.* coefficient overrides

    Graph factors (blocked/blocking) use virtual tags when the task has
    been annotated (annotate_virtual_tags/assign_ids); otherwise blocked
    falls back to bool(task.depends) and no blocking bonus is applied.
    """
    if isinstance(config, UrgencyConfig):
        return _legacy_urgency(task, config)
    if config is None:
        if WEIGHTS != _PRISTINE_WEIGHTS:
            return _legacy_urgency(task, UrgencyConfig.from_weights(WEIGHTS))
        conf = _default_rc()
    else:
        conf = config
    return _tw_urgency(task, conf)


# ── TW polynomial (port of Task::urgency_c) ──────────────────────────────────

def _tiered_measure(count: int) -> float:
    """TW's 1→0.8, 2→0.9, 3+→1.0 measure for tags and annotations."""
    if count >= 3:
        return 1.0
    if count == 2:
        return 0.9
    if count == 1:
        return 0.8
    return 0.0


def _due_measure(due_dt: datetime, now: datetime) -> float:
    """Linear ramp: 0.2 at 14 days early → 1.0 at 7 days overdue."""
    days_overdue = (now - due_dt).total_seconds() / 86400
    if days_overdue >= 7.0:
        return 1.0
    if days_overdue >= -14.0:
        return ((days_overdue + 14.0) * 0.8 / 21.0) + 0.2
    return 0.2


def _tw_urgency(task: Task, conf) -> float:
    if task.status not in ("pending", "waiting"):
        return 0.0

    c = conf.get_float
    now = datetime.now(timezone.utc)
    score = 0.0

    if task.start:
        score += c("urgency.active.coefficient", 4.0)

    if task.scheduled:
        sched_dt = _parse_iso(task.scheduled)
        if sched_dt and sched_dt < now:      # TW: only once the date arrives
            score += c("urgency.scheduled.coefficient", 5.0)

    if task.status == "waiting":
        score += c("urgency.waiting.coefficient", -3.0)

    if task.project:
        score += c("urgency.project.coefficient", 1.0)

    score += _tiered_measure(len(task.tags)) * \
        c("urgency.tags.coefficient", 1.0)
    score += _tiered_measure(len(task.annotations)) * \
        c("urgency.annotations.coefficient", 1.0)

    if task.due:
        due_dt = _parse_iso(task.due)
        if due_dt:
            score += _due_measure(due_dt, now) * \
                c("urgency.due.coefficient", 12.0)

    # Age: measure = age / urgency.age.max, capped at 1.0 (TW gives tasks
    # with no entry the full measure)
    age_max = c("urgency.age.max", 365.0)
    entry_dt = _parse_iso(task.entry)
    if entry_dt is None or age_max <= 0:
        age_measure = 1.0
    else:
        age_days = max(0.0, (now - entry_dt).total_seconds() / 86400)
        age_measure = min(age_days / age_max, 1.0)
    score += age_measure * c("urgency.age.coefficient", 2.0)

    # Dependency graph
    if task.virtual_tags:
        if "BLOCKED" in task.virtual_tags:
            score += c("urgency.blocked.coefficient", -5.0)
        if "BLOCKING" in task.virtual_tags:
            score += c("urgency.blocking.coefficient", 8.0)
    elif task.depends:
        score += c("urgency.blocked.coefficient", -5.0)

    # UDA coefficients — urgency.uda.<name>[.<value>].coefficient.
    # priority rides this mechanism, exactly like TW.
    for key, raw in conf.subtree("urgency.uda.").items():
        if not key.endswith(".coefficient"):
            continue
        try:
            coef = float(raw)
        except (TypeError, ValueError):
            continue
        body = key[: -len(".coefficient")]
        name, dot, wanted = body.partition(".")
        actual = task.priority if name == "priority" \
            else str(task.udas.get(name, "") or "")
        if dot:                              # value-specific
            if actual == wanted:
                score += coef
        elif actual:                         # presence
            score += coef

    # User bonuses
    for key, raw in conf.subtree("urgency.user.tag.").items():
        if key.endswith(".coefficient") and \
                key[: -len(".coefficient")] in task.tags:
            try:
                score += float(raw)
            except (TypeError, ValueError):
                pass
    for key, raw in conf.subtree("urgency.user.project.").items():
        if key.endswith(".coefficient") and \
                key[: -len(".coefficient")] == task.project:
            try:
                score += float(raw)
            except (TypeError, ValueError):
                pass
    desc_lower = task.description.lower()
    for key, raw in conf.subtree("urgency.user.keyword.").items():
        if key.endswith(".coefficient") and \
                key[: -len(".coefficient")].lower() in desc_lower:
            try:
                score += float(raw)
            except (TypeError, ValueError):
                pass

    return round(max(score, 0.0), 2)


def apply_inherited_urgency(tasks: List[Task], conf: Union[UrgencyConfig, "Taskrc", None] = None) -> None:
    """TW's urgency.inherit: a blocking task takes on the largest urgency
    among the tasks it blocks.  Sets t.urgency_value in place for every
    task.  No-op propagation when urgency.inherit is off (values are
    still computed and stored)."""
    conf = conf or _default_rc()
    for t in tasks:
        t.urgency_value = compute_urgency(t, conf)
    if not conf.get_bool("urgency.inherit"):
        return

    dependents: Dict[str, List[Task]] = {}
    for t in tasks:
        if t.status in ("pending", "waiting"):
            for dep in t.depends:
                dependents.setdefault(dep, []).append(t)

    memo: Dict[str, float] = {}

    def effective(t: Task, seen: frozenset) -> float:
        if t.uuid in memo:
            return memo[t.uuid]
        if t.uuid in seen:               # cycle guard (shouldn't happen)
            return t.urgency_value
        val = t.urgency_value
        for d in dependents.get(t.uuid, []):
            val = max(val, effective(d, seen | {t.uuid}))
        memo[t.uuid] = val
        return val

    for t in tasks:
        t.urgency_value = effective(t, frozenset())


# ── Legacy additive model (pre-0.4 default) ──────────────────────────────────

def _legacy_urgency(task: Task, cfg: UrgencyConfig) -> float:
    """The 0.1-0.3 additive scoring, selected via UrgencyConfig/WEIGHTS."""
    if task.status != "pending":
        return 0.0

    score = 0.0
    now   = datetime.now(timezone.utc)

    if task.start:
        score += cfg.active

    due_dt = _parse_iso(task.due)
    if due_dt:
        delta_days = (due_dt - now).total_seconds() / 86400
        if delta_days < 0:
            score += cfg.overdue
        elif delta_days < 1:
            score += cfg.due_today
        elif delta_days < 7:
            score += cfg.due_soon

    if task.scheduled:
        score += cfg.scheduled

    score += cfg.priority.get(task.priority, 0.0)

    tags_lower = {tg.lower() for tg in task.tags}
    if "urgent" in tags_lower:
        score += cfg.tag_urgent
    if "next" in tags_lower:
        score += cfg.tag_next

    score += min(len(task.annotations) * cfg.annotations, cfg.annotations_cap)

    entry_dt = _parse_iso(task.entry)
    if entry_dt:
        age_days = max(0, (now - entry_dt).total_seconds() / 86400)
        score += min(age_days * cfg.age_per_day, cfg.age_cap)

    if task.virtual_tags:
        if "BLOCKED" in task.virtual_tags:
            score += cfg.blocked
        if "BLOCKING" in task.virtual_tags:
            score += cfg.blocking
    elif task.depends:
        # Not annotated — fall back to the pre-0.3 presence check
        score += cfg.blocked

    return round(max(score, 0.0), 2)
