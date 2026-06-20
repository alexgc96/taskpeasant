# Backwards Compatibility Contract

> **Read this before you change any code in the public API.**
>
> Anything documented on this page is **frozen** — it cannot change without a **MAJOR** version bump (semver). A change here is, by definition, a breaking change for every embedder.
>
> If you're tempted to change something here for "code cleanliness" or because "no one uses it"… you're wrong. Studio OS uses it. Other embedders will too. Add a new entry point instead.

---

## Why this file exists

TaskPeasant was extracted from analogtrsh's [Studio OS](https://github.com/alexgc96/analogtrsh), which has been depending on its API and storage layout since the in-tree days. The integration assumes specific module exports, function signatures, a specific YAML key, a specific Task dict shape, and a specific CLI grammar.

If any of those drift, Studio OS (and any other embedder) breaks silently — read paths return empty lists, write paths corrupt sibling metadata, the terminal widget shows "command not found".

So they are frozen. Period.

---

## 1. Public symbols exported from `taskpeasant/__init__.py`

These names are part of the public API:

| Symbol            | Kind       | Frozen since |
| ----------------- | ---------- | ------------ |
| `Task`            | class      | 0.1.0        |
| `read_tasks`      | function   | 0.1.0        |
| `write_tasks`     | function   | 0.1.0        |
| `cmd_add`         | function   | 0.1.0        |
| `cmd_done`        | function   | 0.1.0        |
| `cmd_delete`      | function   | 0.1.0        |
| `cmd_start`       | function   | 0.1.0        |
| `cmd_stop`        | function   | 0.1.0        |
| `cmd_annotate`    | function   | 0.1.0        |
| `cmd_modify`      | function   | 0.1.0        |
| `cmd_export`      | function   | 0.1.0        |
| `compute_urgency` | function   | 0.1.0        |
| `execute_command` | function   | 0.1.0        |

Rules:
- **Adding** a new symbol — fine, never breaking.
- **Renaming** any symbol above — MAJOR bump.
- **Removing** any symbol above — MAJOR bump.
- **Changing the signature** of a function above (parameter name, order, default) — MAJOR bump. Adding a *new optional keyword* with a default is fine.

## 2. Storage key

```python
_TP_KEY = "taskpeasant_tasks"
```

- The literal string `taskpeasant_tasks` is the **only** top-level key TaskPeasant ever writes to.
- TaskPeasant never writes to, deletes, or restructures any *other* top-level key. Specifically, it must never touch a sibling `tasks:` mapping (host apps may use `tasks:` for unrelated metadata, e.g. Taskwarrior context tags).
- The legacy fallback in `read_tasks` (read from `tasks:` if it's a list) and the migration in `write_tasks` (move list-form `tasks:` into `taskpeasant_tasks:` and restore `tasks:` as an empty dict) **must remain forever**. Cost is negligible, removing it silently wipes data on old files.

Renaming `_TP_KEY` is a MAJOR bump — and even then, you need a migration path that reads both keys for at least one release cycle.

## 3. `Task.to_dict()` output shape

The dict returned by `Task.to_dict()` is what gets serialised into YAML. Embedders read that YAML directly (Studio OS does, for example, in `routes/calendar.py` and `routes/tasks.py`) so the field names are part of the contract:

| Field         | Type       | Notes                                              |
| ------------- | ---------- | -------------------------------------------------- |
| `uuid`        | str        | Always present                                     |
| `description` | str        | Always present                                     |
| `status`      | str        | Always present. One of `pending`/`completed`/`deleted`/`waiting` |
| `entry`       | str (ISO)  | Always present                                     |
| `start`       | str (ISO)  | Present only when active                           |
| `end`         | str (ISO)  | Present only when completed/deleted                |
| `due`         | str (ISO)  | Optional, ISO 8601 with Z suffix                   |
| `scheduled`   | str (ISO)  | Optional                                           |
| `modified`    | str (ISO)  | Optional                                           |
| `tags`        | list[str]  | Omitted when empty                                 |
| `depends`     | list[str]  | Omitted when empty; list of UUID strings           |
| `annotations` | list[dict] | Each `{entry: ISO, description: str}`              |
| (UDAs)        | any        | Any unknown key passes through, top-level in dict  |

Date format inside YAML is ISO 8601 with Z: `2026-06-19T14:30:00Z`. The wire-format variant (`20260619T143000Z`) is produced only by `to_tw_export()` for UI/JSON consumers — never written to YAML.

## 4. `Task.to_tw_export()` output shape

This is the dict the host UI consumes (Studio OS pipes it straight to JS that originally parsed `task export` output). It must remain TaskWarrior-wire-compatible:

- Dates in `YYYYMMDDTHHMMSSZ` form
- `depends` as a comma-separated string (NOT a list — that's the TW quirk)
- `urgency` as a float, rounded to 2 decimals
- `is_active` boolean derived from `bool(start)`
- All UDAs merged at the top level

## 5. `execute_command(raw, yaml_path)` signature and grammar

Signature: `execute_command(raw: str, yaml_path: str) -> str`

Returns a plain string suitable for direct display in a host terminal widget. The string format may evolve (whitespace, ordering) but the function must always return a string and never raise.

Supported CLI grammar — **floor** that must keep working:

- `task add <description> [+tag] [due:<date|alias>] [scheduled:<date|alias>]`
- `task <uuid_prefix> done`
- `task <uuid_prefix> delete`
- `task <uuid_prefix> start`
- `task <uuid_prefix> stop`
- `task <uuid_prefix> annotate <text>`
- `task <uuid_prefix> modify [+tag] [-tag] [<field>:<value>]`
- `task [+tag] [-tag] [status:<v>] [<field>.any|.none:]` — implicit list
- `task [filter] export` — JSON output
- `rc.*` flags silently stripped (TW config overrides — host may send them)

Date aliases that must resolve: `today`, `tomorrow`, `yesterday`, `eow`, `eom`, weekday names (lowercase).

New commands can be added freely. Removing or changing semantics of any of the above is a MAJOR bump.

## 6. Urgency score range

`compute_urgency(task)` returns a `float` clamped to `>= 0.0`. The number lands in roughly the same 0-20 range as TaskWarrior's default coefficients, so a host UI that draws an urgency bar normalised against that range keeps working.

Tweaking individual `WEIGHTS` constants for tuning is fine. Returning a wildly different scale (e.g. 0-1, 0-100) is a MAJOR bump.

## 7. Status enum

```python
_VALID_STATUSES = frozenset(["pending", "completed", "deleted", "waiting"])
```

These four strings, lowercase, exactly. Any unknown status string read from YAML is coerced to `"pending"` on load. Adding `recurring` would be a MAJOR bump for any embedder that filters on a closed enum.

---

## Deferred / aspirational (NOT frozen yet)

These exist but are explicitly *unstable* and may move:

- The exact text output of `_cmd_list` (column widths, ordering, ASCII vs Unicode markers). The fact that a string comes back is frozen; its formatting is not.
- `WEIGHTS` numeric values (the dict keys are stable, the numbers may be tuned).
- The `udas` dict on `Task` — the *mechanism* (unknown keys round-trip) is frozen, but specific UDA names are host-defined.

If you'd like one of these promoted to frozen, open an issue.
