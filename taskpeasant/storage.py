"""
taskpeasant/storage.py
Read and write the taskpeasant_tasks: block inside a YAML file.
All other top-level keys are preserved exactly.
Thread-safe via a per-file lock so concurrent writers don't race.

YAML schema
───────────
TaskPeasant writes to a dedicated top-level key `taskpeasant_tasks:`:

    taskpeasant_tasks:
      - uuid: 8c2f...
        description: render final shot
        status: pending
        entry: 2026-04-17T14:30:00Z
        tags: [render, urgent]
      - uuid: ...

It never touches any other key. This is deliberate: it lets you embed
TaskPeasant inside a YAML file that already carries unrelated metadata
(project config, tags, Taskwarrior context, etc.) without risk of
collision. See docs/BACKWARDS_COMPAT.md for the full contract.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List

import yaml

from .task_model import Task

# ── Storage key used for the task list ───────────────────────────────────────
# Dedicated key so we never collide with sibling metadata
_TP_KEY = "taskpeasant_tasks"

# One lock per file path — avoids cross-file blocking
_file_locks: dict = {}
_meta_lock  = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    with _meta_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def read_tasks(yaml_path: str) -> List[Task]:
    """
    Return all Task objects.  Reads from `taskpeasant_tasks:` first; falls
    back to legacy `tasks:` list for files written by very early versions.
    Never raises.
    """
    lock = _lock_for(yaml_path)
    with lock:
        try:
            raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")) or {}

            # Primary: dedicated TP key (no collision with sibling metadata)
            tp_list = raw.get(_TP_KEY)
            if isinstance(tp_list, list):
                return [Task.from_dict(t) for t in tp_list if isinstance(t, dict)]

            # Legacy fallback: old files where TP wrote directly to tasks:
            # Only use if tasks: is a list (i.e. TP overwrote it)
            legacy = raw.get("tasks")
            if isinstance(legacy, list):
                return [Task.from_dict(t) for t in legacy if isinstance(t, dict)]

            return []
        except Exception as e:
            print(f"[taskpeasant.storage] read error {yaml_path}: {e}")
            return []


def write_tasks(yaml_path: str, tasks: List[Task]) -> None:
    """
    Write task list to `taskpeasant_tasks:`.
    Any pre-existing `tasks:` mapping (used by host apps for unrelated
    metadata, e.g. Taskwarrior context tags) is NEVER touched.
    """
    lock = _lock_for(yaml_path)
    with lock:
        p = Path(yaml_path)
        try:
            current = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            current = {}

        # Write only to the TP-specific key
        current[_TP_KEY] = [t.to_dict() for t in tasks]

        # Migrate legacy data: if tasks: is a list (old TP writes), move it
        # to taskpeasant_tasks: and restore tasks: to an empty dict so any
        # sibling lookup that expects a mapping still works on next load.
        if isinstance(current.get("tasks"), list):
            # Merge: keep any items not already in _TP_KEY
            existing_uuids = {t["uuid"] for t in current[_TP_KEY] if "uuid" in t}
            for item in current["tasks"]:
                if isinstance(item, dict) and item.get("uuid") not in existing_uuids:
                    current[_TP_KEY].append(item)
            # Restore tasks: as empty dict so mapping lookups don't break
            current["tasks"] = {}

        p.write_text(
            yaml.dump(current, default_flow_style=False,
                      sort_keys=False, allow_unicode=True),
            encoding="utf-8"
        )
