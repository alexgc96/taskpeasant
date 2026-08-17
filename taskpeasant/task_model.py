"""
taskpeasant/task_model.py
Task dataclass — wire-compatible with Taskwarrior JSON export format.

Date format: "YYYYMMDDTHHMMSSz"  (UTC, uppercase Z)
This matches exactly what Taskwarrior emits in `task export` and what
app.py's existing _parse_tw_date() and format_tw_date() already consume.

Status values mirror Task.h enum: pending, completed, deleted, waiting.
  (recurring is TW-only — TaskPeasant treats it as pending + a note in UDAs)
"""

from __future__ import annotations

import uuid as _uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ── Canonical field names (subset of Taskwarrior's JSON schema) ──────────────
_KNOWN_FIELDS = frozenset([
    "uuid", "description", "status", "entry", "start", "end",
    "due", "scheduled", "wait", "modified", "tags", "depends", "annotations",
    "urgency", "project", "priority",
    "recur", "until", "parent", "mask", "imask",
])

_VALID_STATUSES = frozenset(["pending", "completed", "deleted", "waiting"])

# Statuses accepted on read but NOT part of the frozen contract enum.
# "recurring" only ever appears in a file when the host opted in via the
# `recurrence=on` config (see docs/BACKWARDS_COMPAT.md §7).
_EXTENDED_STATUSES = frozenset(["recurring"])


def _now_tw() -> str:
    """Return current UTC time in Taskwarrior wire format: 20260417T143000Z"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_to_tw(iso: str) -> str:
    """
    Accept any reasonable date string and normalise to TW wire format.
    Handles:
      "YYYYMMDDTHHMMSSz"     ← already TW wire, passthrough
      "YYYY-MM-DDTHH:MM:SSZ" ← ISO with Z (what we store in YAML)
      "YYYY-MM-DDTHH:MM:SS"  ← ISO without Z
      "YYYY-MM-DDTHH:MM"     ← datetime-local input
      "YYYY-MM-DD"           ← date only
    """
    s = (iso or "").strip()
    if not s:
        return ""
    # Already TW wire format: 16 chars, no hyphens in date part, ends in Z
    # e.g. "20260417T190054Z"
    if len(s) >= 15 and "T" in s and s.upper().endswith("Z") and "-" not in s[:8]:
        return s.upper()
    # All ISO variants — try with Z suffix first, then without
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
    return s  # unknown format — pass through unchanged


def _tw_to_iso(tw: str) -> str:
    """Convert TW wire format → ISO 8601 for human-readable YAML storage."""
    s = (tw or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.strptime(s, "%Y%m%dT%H%M%SZ")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return s


@dataclass
class Task:
    """
    Single task — stored as a dict in project.yaml tasks: [] list.
    All dates are stored in ISO 8601 (human-readable) inside YAML,
    but serialised to TW wire format when exported to the UI or compared
    with real Taskwarrior data.
    """
    uuid:        str
    description: str
    status:      str = "pending"       # pending | completed | deleted | waiting

    # Dates — stored as ISO strings in YAML ("2026-04-17T14:30:00Z")
    entry:     str = ""
    start:     str = ""                # set when task is started (active)
    end:       str = ""                # set when completed or deleted
    due:       str = ""
    scheduled: str = ""
    wait:      str = ""   # hide task until this date; auto-transitions waiting→pending
    modified:  str = ""

    tags:        list = field(default_factory=list)
    depends:     list = field(default_factory=list)   # list of UUID strings
    annotations: list = field(default_factory=list)   # [{entry, description}]

    project:  str = ""   # TW-compatible project name
    priority: str = ""   # H | M | L  (Taskwarrior priority values)

    # Recurrence (only populated when the host opts in via recurrence=on)
    recur:  str = ""     # duration: weekly, 3d, monthly, ...
    until:  str = ""     # ISO date — stop recurring / expire after this
    parent: str = ""     # uuid of the recurring template (children only)
    mask:   str = ""     # per-child status chars on the template
    imask:  str = ""     # child index into the parent's mask

    # Any non-standard keys land here — preserved on round-trip
    udas: dict = field(default_factory=dict)

    # Computed at runtime — never persisted
    urgency_value: float = field(default=0.0, repr=False)
    id:            int   = field(default=0,   repr=False)
    virtual_tags:  set   = field(default_factory=set, repr=False, compare=False)

    # ── Serialisation ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """
        Produce a YAML-safe dict.  Dates stored as ISO strings.
        UDAs are merged at the top level (matching TW's flat JSON structure).
        """
        d: dict = {
            "uuid":        self.uuid,
            "description": self.description,
            "status":      self.status,
            "entry":       self.entry,
        }
        # Optional date fields — omit empties to keep YAML clean
        for key in ("start", "end", "due", "scheduled", "wait", "modified"):
            v = getattr(self, key)
            if v:
                d[key] = v
        if self.project:
            d["project"] = self.project
        if self.priority:
            d["priority"] = self.priority
        for key in ("recur", "until", "parent", "mask", "imask"):
            v = getattr(self, key)
            if v != "":
                d[key] = v
        if self.tags:
            d["tags"] = list(self.tags)
        if self.depends:
            d["depends"] = list(self.depends)
        if self.annotations:
            d["annotations"] = list(self.annotations)
        # Merge UDAs last so they never overwrite known fields
        for k, v in self.udas.items():
            if k not in _KNOWN_FIELDS:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        """
        Hydrate a Task from a YAML dict.
        Unknown keys are collected into .udas — no data is ever dropped.
        """
        known = {}
        udas  = {}
        for k, v in raw.items():
            if k in _KNOWN_FIELDS:
                known[k] = v
            elif k != "urgency":     # urgency is computed, never stored
                udas[k] = v

        # Normalise depends → list of strings (TW stores as comma-str sometimes)
        raw_deps = known.get("depends") or []
        if isinstance(raw_deps, str):
            raw_deps = [d.strip() for d in raw_deps.split(",") if d.strip()]
        elif not isinstance(raw_deps, list):
            raw_deps = []

        # Normalise tags
        raw_tags = known.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

        t = cls(
            uuid        = str(known.get("uuid") or _uuid_mod.uuid4()),
            description = str(known.get("description") or ""),
            status      = str(known.get("status") or "pending"),
            entry       = str(known.get("entry") or ""),
            start       = str(known.get("start") or ""),
            end         = str(known.get("end") or ""),
            due         = str(known.get("due") or ""),
            scheduled   = str(known.get("scheduled") or ""),
            wait        = str(known.get("wait") or ""),
            modified    = str(known.get("modified") or ""),
            tags        = raw_tags,
            depends     = raw_deps,
            annotations = list(known.get("annotations") or []),
            project     = str(known.get("project") or ""),
            priority    = str(known.get("priority") or ""),
            recur       = str(known.get("recur") or ""),
            until       = str(known.get("until") or ""),
            parent      = str(known.get("parent") or ""),
            mask        = str(known.get("mask") or ""),
            imask       = ("" if known.get("imask") is None
                           else str(known.get("imask"))),
            udas        = udas,
        )
        # Contract §7: unknown statuses coerce to pending.  The one
        # exception is an opt-in recurring TEMPLATE, which always carries
        # a recur duration; a bare "recurring" status stays coerced.
        if t.status not in _VALID_STATUSES and not (
                t.status in _EXTENDED_STATUSES and t.recur):
            t.status = "pending"
        return t

    def to_tw_export(self) -> dict:
        """
        Produce a dict in Taskwarrior JSON-export format so the existing
        UI JS (which expects TW wire dates) needs zero changes.
        """
        d: dict = {
            "id":          self.id,
            "uuid":        self.uuid,
            "description": self.description,
            "status":      self.status,
            "entry":       _iso_to_tw(self.entry) if self.entry else "",
            "urgency":     round(self.urgency_value, 2),
            # is_active mirrors TW: True when start is set
            "is_active":   bool(self.start),
        }
        for key in ("start", "end", "due", "scheduled", "wait", "modified"):
            v = getattr(self, key)
            if v:
                d[key] = _iso_to_tw(v)
        if self.project:
            d["project"] = self.project
        if self.priority:
            d["priority"] = self.priority
        if self.recur:
            d["recur"] = self.recur
        if self.until:
            d["until"] = _iso_to_tw(self.until)
        if self.parent:
            d["parent"] = self.parent
        if self.mask:
            d["mask"] = self.mask
        if self.imask != "":
            try:
                d["imask"] = int(self.imask)
            except ValueError:
                pass
        if self.tags:
            d["tags"] = list(self.tags)
        if self.depends:
            d["depends"] = ",".join(self.depends)   # TW wire: comma-separated
        if self.annotations:
            d["annotations"] = list(self.annotations)
        d.update(self.udas)
        return d
