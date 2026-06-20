"""
taskpeasant/urgency.py
Simple urgency score for Kanban sorting.

Replaces Taskwarrior's polynomial with a transparent additive model.
Each factor produces a score in a human-readable range. Scores are
intentionally kept in TW's ~0-20 range so the existing UI urgency
display needs zero changes.

Factor weights are defined in WEIGHTS — tune here or expose in config.yaml.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .task_model import Task

# ── Tunable weights ─────────────────────────────────────────────────────────
# Mirrors Taskwarrior's default coefficients for compatibility.
WEIGHTS = {
    "active":      15.0,   # task has a start timestamp (you're working on it)
    "overdue":     12.0,   # past its due date
    "due_today":    8.0,   # due within 24 hours
    "due_soon":     4.0,   # due within 7 days
    "scheduled":    2.0,   # has a scheduled date (planned work)
    "tag_urgent":   6.0,   # tagged +urgent
    "tag_next":     3.5,   # tagged +next
    "annotations":  0.5,   # per annotation (shows engagement) — max 2.0
    "age_per_day":  0.01,  # slight age bonus so old tasks don't rot — max 2.0
    "blocked":     -5.0,   # has unresolved depends (can't act on it yet)
}


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


def compute_urgency(task: Task) -> float:
    """Return a urgency score for a single task. Returns 0.0 for non-pending."""
    if task.status != "pending":
        return 0.0

    score = 0.0
    now   = datetime.now(timezone.utc)

    # ── Active ───────────────────────────────────────────────────────────────
    if task.start:
        score += WEIGHTS["active"]

    # ── Due date scoring ─────────────────────────────────────────────────────
    due_dt = _parse_iso(task.due)
    if due_dt:
        delta_days = (due_dt - now).total_seconds() / 86400
        if delta_days < 0:
            score += WEIGHTS["overdue"]
        elif delta_days < 1:
            score += WEIGHTS["due_today"]
        elif delta_days < 7:
            score += WEIGHTS["due_soon"]

    # ── Scheduled ────────────────────────────────────────────────────────────
    if task.scheduled:
        score += WEIGHTS["scheduled"]

    # ── Tag bonuses ──────────────────────────────────────────────────────────
    tags_lower = {tg.lower() for tg in task.tags}
    if "urgent" in tags_lower:
        score += WEIGHTS["tag_urgent"]
    if "next" in tags_lower:
        score += WEIGHTS["tag_next"]

    # ── Annotations (shows the task has been touched / discussed) ────────────
    score += min(len(task.annotations) * WEIGHTS["annotations"], 2.0)

    # ── Age bonus — based on entry date, capped at 2 pts ────────────────────
    entry_dt = _parse_iso(task.entry)
    if entry_dt:
        age_days = max(0, (now - entry_dt).total_seconds() / 86400)
        score += min(age_days * WEIGHTS["age_per_day"], 2.0)

    # ── Blocked penalty ──────────────────────────────────────────────────────
    if task.depends:
        score += WEIGHTS["blocked"]

    return round(max(score, 0.0), 2)
