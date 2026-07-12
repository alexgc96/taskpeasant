"""
taskpeasant/urgency.py
Simple urgency score for Kanban sorting.

Replaces Taskwarrior's polynomial with a transparent additive model.
Each factor produces a score in a human-readable range. Scores are
intentionally kept in TW's ~0-20 range so the existing UI urgency
display needs zero changes.

Coefficients live in UrgencyConfig; compute_urgency(task, config=...)
accepts a custom instance.  The legacy WEIGHTS dict is still honoured:
when no config is passed, one is built from WEIGHTS on each call, so
hosts that tune by mutating WEIGHTS keep working unchanged (WEIGHTS is
deprecated in favour of passing an UrgencyConfig explicitly).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Optional

from .task_model import Task

# ── Tunable weights (legacy knob — kept live, see module docstring) ─────────
# Mirrors Taskwarrior's default coefficients for compatibility.
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


@dataclass(frozen=True)
class UrgencyConfig:
    """All urgency coefficients, one field per factor.

    Pass a custom instance to compute_urgency()/assign_ids()/cmd_export()
    to re-weight scoring per caller without touching global state.
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
    def from_weights(cls, weights: dict) -> "UrgencyConfig":
        """Build a config from a WEIGHTS-style dict; unknown keys ignored,
        missing keys fall back to the dataclass defaults."""
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in weights.items() if k in known}
        if "priority" in kwargs:
            kwargs["priority"] = dict(kwargs["priority"])
        return cls(**kwargs)


DEFAULT_CONFIG = UrgencyConfig()


def _parse_iso(s: str):
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


def compute_urgency(task: Task, config: Optional[UrgencyConfig] = None) -> float:
    """Return a urgency score for a single task. Returns 0.0 for non-pending.

    config=None (the default) builds the config from the live WEIGHTS dict,
    preserving the legacy mutate-WEIGHTS tuning path.  Graph factors
    (blocked/blocking) use virtual tags when the task has been annotated
    (annotate_virtual_tags/assign_ids); otherwise blocked falls back to
    bool(task.depends) and no blocking bonus is applied.
    """
    if task.status != "pending":
        return 0.0

    cfg = config if config is not None else UrgencyConfig.from_weights(WEIGHTS)

    score = 0.0
    now   = datetime.now(timezone.utc)

    # ── Active ───────────────────────────────────────────────────────────────
    if task.start:
        score += cfg.active

    # ── Due date scoring ─────────────────────────────────────────────────────
    due_dt = _parse_iso(task.due)
    if due_dt:
        delta_days = (due_dt - now).total_seconds() / 86400
        if delta_days < 0:
            score += cfg.overdue
        elif delta_days < 1:
            score += cfg.due_today
        elif delta_days < 7:
            score += cfg.due_soon

    # ── Scheduled ────────────────────────────────────────────────────────────
    if task.scheduled:
        score += cfg.scheduled

    # ── Priority ─────────────────────────────────────────────────────────────
    score += cfg.priority.get(task.priority, 0.0)

    # ── Tag bonuses ──────────────────────────────────────────────────────────
    tags_lower = {tg.lower() for tg in task.tags}
    if "urgent" in tags_lower:
        score += cfg.tag_urgent
    if "next" in tags_lower:
        score += cfg.tag_next

    # ── Annotations (shows the task has been touched / discussed) ────────────
    score += min(len(task.annotations) * cfg.annotations, cfg.annotations_cap)

    # ── Age bonus — based on entry date, capped ──────────────────────────────
    entry_dt = _parse_iso(task.entry)
    if entry_dt:
        age_days = max(0, (now - entry_dt).total_seconds() / 86400)
        score += min(age_days * cfg.age_per_day, cfg.age_cap)

    # ── Dependency graph: blocked penalty / blocking bonus ──────────────────
    if task.virtual_tags:
        if "BLOCKED" in task.virtual_tags:
            score += cfg.blocked
        if "BLOCKING" in task.virtual_tags:
            score += cfg.blocking
    elif task.depends:
        # Not annotated — fall back to the pre-0.3 presence check
        score += cfg.blocked

    return round(max(score, 0.0), 2)
