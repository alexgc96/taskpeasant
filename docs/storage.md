# Storage Contract

> This document is part of the frozen public contract. Nothing described here
> changes without a MAJOR version bump. See `BACKWARDS_COMPAT.md`.

---

## Storage key

TaskPeasant owns exactly one top-level key in any YAML file it touches:

```yaml
taskpeasant_tasks:
  - uuid: 8c2f1a3b-…
    description: render the final shot
    status: pending
    entry: 2026-06-19T14:30:00Z
```

Every other key in the file is left completely untouched. This makes it safe
to embed TaskPeasant inside a project YAML that already carries metadata,
Taskwarrior context tags, or anything else.

---

## YAML schema

Each task is a YAML mapping. All fields are optional except `uuid` and
`description`. Unknown keys are preserved as UDAs (User-Defined Attributes)
and round-trip transparently.

| Field | Type | Notes |
|---|---|---|
| `uuid` | string | UUID v4 |
| `description` | string | |
| `status` | string | `pending` \| `completed` \| `deleted` \| `waiting` |
| `entry` | ISO 8601 string | Creation timestamp (UTC) |
| `start` | ISO 8601 string | Set when task is started |
| `end` | ISO 8601 string | Set on `done` or `delete` |
| `due` | ISO 8601 string | |
| `scheduled` | ISO 8601 string | |
| `wait` | ISO 8601 string | Task hidden until this date |
| `modified` | ISO 8601 string | Updated on every mutation |
| `tags` | list of strings | |
| `depends` | list of UUID strings | |
| `annotations` | list of `{entry, description}` | |
| `project` | string | |
| `priority` | string | `H` \| `M` \| `L` |
| _(any other key)_ | any | Stored as UDA, never dropped |

**Date format:** All dates are stored as `YYYY-MM-DDTHH:MM:SSZ` (ISO 8601,
UTC). On TW-wire export (`to_tw_export()`) they are converted to
`YYYYMMDDTHHMMSSz` for UI compatibility.

---

## Thread safety

TaskPeasant uses one `threading.RLock` per file path. Concurrent reads and
writes from different threads within the same process are safe. Cross-process
safety is the caller's responsibility (use a file-level lock if needed).

The lock is reentrant (`RLock`) so that `read_tasks()` can call `write_tasks()`
internally during `waiting→pending` auto-transitions without deadlocking.

---

## Ephemeral integer IDs

Integer IDs are **never stored**. They are assigned at read time to
`pending` and `waiting` tasks, sorted by urgency descending. ID assignment
is cached by `(path, mtime, config)` — any write bumps the file's mtime and
invalidates the cache, so a list followed immediately by an action resolves
the same ID both times.

The cache is capped at 256 entries (oldest evicted first). Unlike Taskwarrior,
which is a short-lived CLI process and recomputes IDs on every invocation,
TaskPeasant runs in-process and can accumulate one stale cache entry per unique
mtime across a long session; the cap bounds worst-case memory growth.

Completed and deleted tasks always have `id = 0`.

> **Taskwarrior reference:** TaskPeasant takes Taskwarrior 2.x as its primary
> reference because its flat-file storage model (human-readable, one file per
> task set) is the closest analogue to TaskPeasant's YAML approach. Taskwarrior
> 3.x persists tasks through a SQLite backend (taskchampion) and reuses ID
> assignments across invocations via a persistent working set — a better fit for
> some long-running embedded applications. TaskPeasant exists specifically to
> run embedded in Python on Windows natively, without requiring a Taskwarrior
> binary or a Linux/Unix container.

---

## Auto-transition: `waiting → pending`

When `read_tasks()` loads a file, it checks every task with
`status: waiting`. If the task's `wait` date is in the past, the status is
changed to `pending` and `wait` is cleared. The updated list is immediately
written back to disk. This mirrors Taskwarrior's garbage-collection pass.

---

## Legacy migration

Very early TaskPeasant files wrote tasks directly to a `tasks:` list key.
On first read, if `taskpeasant_tasks:` is absent but `tasks:` is a list,
TaskPeasant reads from `tasks:`. On next write, tasks are moved to
`taskpeasant_tasks:` and `tasks:` is restored to an empty mapping so host
apps that use `tasks:` for metadata continue to work.

This migration path is permanent and will not be removed.

---

## Embedding

Point TaskPeasant at any YAML file — it does not need to own the file:

```python
yaml_path = "/path/to/project.yaml"   # may contain other keys
tasks = read_tasks(yaml_path)
```

A recommended pattern for multi-project setups is one `project.yaml` per
project. The host app resolves the correct file before calling any
TaskPeasant function.
