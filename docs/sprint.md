# Sprint — TaskPeasant

> Lightweight tracking for what's being worked on now, what's queued, and what's done.
> Mirrors the analogtrsh Studio OS sprint convention.

---

## Current sprint

_Sprint:_ v2 / 0.2.0
_Dates:_ 2026-06-19 → TBD
_Goal:_ TaskWarrior CLI parity (IDs, project, priority, reports, date math, filters) + complete documentation

---

## Active tracks

### Track A — TW Parity
Bring the CLI and data model close enough to TaskWarrior that the two are interchangeable
for day-to-day use. Studio OS integration must remain stable throughout.

### Track B — Documentation
Every public symbol, every CLI verb, every storage decision gets a clean written spec.
No stubs, no TODOs.

---

## This sprint

### Phase 1 — Core UX Parity

- [ ] **Ephemeral integer IDs** ← _locked, first ticket_
  - Assign integer `id` to pending/waiting tasks at read time, sorted by urgency desc
  - `id` is a runtime-only field on `Task` (never persisted, same pattern as `urgency_value`)
  - `_find_one()` accepts int or UUID prefix
  - `execute_command()` / `peasant_parser.py` detects `task 3 done` vs UUID
  - `cmd_export()` output includes `"id"` field (closes parity gap with TW backend in Studio OS)
  - List formatter gets `ID` column
  - mtime-based cache: `(path, mtime)` → ID→UUID map; invalidated on any write
  - MINOR bump safe; Studio OS routes untouched (all use full UUIDs)

- [ ] **`project:` field**
  - First-class string field on `Task` (persisted)
  - `cmd_add` / `cmd_modify` / `execute_command` support `project:foo`
  - Filter support: `project:foo`, `project.any:`, `project.none:`
  - `cmd_export` includes `project` in wire dict

- [ ] **`priority:` field**
  - Values: `H`, `M`, `L` (exact TW strings)
  - Plugs into urgency: H +6.0, M +3.9, L +1.8 (TW's coefficients)
  - `cmd_add` / `cmd_modify` / `execute_command` support `priority:H`
  - Filter: `priority:H`
  - `cmd_export` includes `priority`

- [ ] **`task <uuid/id>` — single task info view**
  - `execute_command("task 3", yaml_path)` or `execute_command("task 8c2f1a3b", yaml_path)`
  - Renders full task detail: all fields, annotations, depends chain

### Phase 2 — CLI Completeness

- [ ] **Standard reports**
  - `task next` — pending only, sorted urgency desc, top 25
  - `task all` — all statuses
  - `task completed` — completed tasks, most recent first
  - `task waiting` — waiting tasks with wait date
  - `task count [filter]` — integer count, no table

- [ ] **`wait:` field with auto-transition**
  - `wait` date on `Task` (persisted, ISO)
  - `cmd_add` / `cmd_modify` support `wait:date`
  - `read_tasks()` auto-transitions `waiting→pending` when `wait` date has passed
  - Filter: `wait.any:`, `wait.none:`, `wait.before:`, `wait.after:`

- [ ] **Extended date math**
  - `+3d`, `+1w`, `+2m`, `+1y` relative offsets from today
  - Works anywhere a date is accepted: `due:+3d`, `wait:+1w`, `scheduled:+2m`
  - Add to `_resolve_date_alias()` in `peasant_parser.py`

- [ ] **Richer filter operators**
  - `due.before:<date>`, `due.after:<date>`
  - `scheduled.before:`, `scheduled.after:`
  - `wait.before:`, `wait.after:`
  - `project:<name>`, `priority:<level>`
  - All date values in these filters resolve through same alias/math pipeline

### Phase 3 — Documentation

- [ ] **`docs/parity.md`** — full TW command/filter/field matrix with ✓/✗/partial + rationale for each gap
- [ ] **`docs/storage.md`** — YAML schema, `taskpeasant_tasks:` contract, migration path, thread-safety guarantees
- [ ] **`docs/cli.md`** — complete CLI grammar with examples for every verb and filter
- [ ] **`docs/api.md`** — every public symbol: signature, params, return, example
- [ ] **Docstrings** — clean one-liner on every public function (currently sparse)
- [ ] **`CHANGELOG.md`** — proper semver changelog from 0.1.0 → 0.2.0

---

## Next sprint — v0.3.0 candidates

_Promote to active when v0.2.0 is tagged and published._

### TW feel gaps (identified post-rich MVP)

- [ ] **Virtual tags** — auto-applied based on state: `+OVERDUE`, `+TODAY`, `+ACTIVE`, `+BLOCKING`, `+BLOCKED`
  - Computed at read time, never persisted; power users filter on these constantly
  - Required for `task +OVERDUE done` bulk pattern to feel right

- [ ] **Urgency: age + blocking scores**
  - Age: older tasks accrue urgency (TW: `age_coeff * days_old / 365`)
  - Blocking: tasks that others depend on get a bonus per blocked task
  - Without these, two tasks with same due/tags always tie forever

- [ ] **Bulk filter operations** — `task +urgent done`, `task project:film delete`
  - TW lets any filter precede a verb; we only support single UUID/ID
  - High daily-use impact

- [ ] **`depends:` wiring**
  - `task 1 modify depends:2` should link the tasks and compute `+BLOCKED`/`+BLOCKING`
  - Currently the field exists but no relationship is enforced

- [ ] **Date clearing** — `task 1 modify due:` (empty value) removes the field
  - TW convention; we don't handle the empty-value case

- [ ] **Config file** — `.taskpeasantrc` or `~/.config/taskpeasant/config.yaml`
  - Persist: default YAML file path, urgency weight overrides, default project
  - See backlog for full design notes

- [ ] **`UrgencyConfig` dataclass** — locked design decision
  - Replace hardcoded `WEIGHTS` dict with a proper `UrgencyConfig` dataclass
  - `compute_urgency(task, config=DEFAULT_CONFIG)` — pure function, no global state
  - Headless callers can pass custom configs; CLI loads from config file at startup
  - Opens the door to TW's polynomial urgency model as a future drop-in
  - `assign_ids()` and any other call site threads `config` through
  ```python
  @dataclass
  class UrgencyConfig:
      due_coeff:   float = 12.0
      tag_coeff:   float = 1.0
      age_coeff:   float = 2.0          # ready for age scoring
      priority:    dict  = field(default_factory=lambda: {"H": 6.0, "M": 3.9, "L": 1.8})
      # … extend per factor as needed
  ```

---

## Backlog

_(Post-v2 ideas. Promote when ready.)_

- **Config file design**: `~/.config/taskpeasant/config.yaml` (XDG-aware, falls back to `~/.taskpeasantrc`). Keys: `data.location`, `urgency.*` weight overrides, `default.project`. Loaded once at startup, never from `execute_command()` path (headless callers pass `yaml_path` explicitly).
- Recurring tasks engine
- `task sync` stub (no-op with clear error — sets expectation)
- `task <id> edit` (open in $EDITOR)

---

## Recently shipped

_(Most recent first. Trim entries once they roll into a release in `CHANGELOG.md`.)_

- **0.2.0** — v2 sprint: integer IDs, project/priority/wait fields, full report suite
  (history, ghistory, burndown, calendar, next, all, completed, waiting, count),
  extended date math, richer filter operators, rich CLI layer (`_rich.py` / `__main__.py`),
  complete docs (parity.md, storage.md, cli.md, api.md), CHANGELOG.
- **0.1.0** — initial extraction from analogtrsh Studio OS monorepo. Frozen public API:
  13 symbols, YAML storage, 8 commands, urgency scoring, filter engine, TW-compatible export.
