# Changelog

All notable changes to TaskPeasant will be documented in this file.
The format is loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Breaking-change policy**: anything listed in [`docs/BACKWARDS_COMPAT.md`](docs/BACKWARDS_COMPAT.md) cannot change without a MAJOR version bump.
> The entry is loud-tagged `**BREAKING**` here and explained in `docs/integration.md` with a migration note for embedders.

## [Unreleased]

_(nothing yet)_

---

## [0.5.0] — 2026-11-09

The hardening release: safer writes, a calendar that looks like
Taskwarrior's, and a bounded recurrence catch-up. Nothing in the frozen
contract (`docs/BACKWARDS_COMPAT.md`) changes.

### Added
- **Calendar color parity with Taskwarrior** (`_rich.py`, `_colors.py`,
  `_calendar_grid.py`) — `task calendar` now shades day cells to match
  TW's `color.calendar.*` rules (today/due/due.today/overdue/scheduled/
  weekend), adds a week-number column (`displayweeknumber`) and a
  plain-word legend (`calendar.legend`) to both the plain-text and rich
  rendered calendar, and fixes the rich calendar ignoring `weekstart`.
  New keys: `rule.precedence.calendar.color`, `color.calendar.scheduled`,
  `color.calendar.weeknumber`, `calendar.legend`, `displayweeknumber`.
  (#11, #18)
- **`tp sync` stub** — the CLI answers `sync` with a short "intentionally
  not implemented" message and local-first alternatives (git, rsync, a
  shared drive) instead of treating the word as a filter. (#8, #14)
- **`py.typed` marker** and a type-annotation sweep over the public API,
  so type checkers pick up TaskPeasant's annotations in host apps
  (PEP 561). Signatures are unchanged at runtime. (#16)
- **`recurrence.catchup.limit`** (default `2`, `0` = no cap) — see
  Changed. (#9)

### Changed
- **Python 3.10 or newer is now required.** 3.9 is past end-of-life and
  can no longer be tested in CI; `requires-python` is `>=3.10` and the
  test matrix is 3.10–3.14. Hosts still on 3.9 should stay on 0.4.0.
- **Recurrence catch-up is now capped** (only affects hosts that set
  `recurrence=on`). A recurring template that has fallen behind used to
  get every missed occurrence created by the next command — a daily task
  in a file untouched for a year meant 365 new tasks at once. Now each
  command creates at most `recurrence.catchup.limit` past-due children
  per template (oldest first) and the rest follow on later commands. Set
  `recurrence.catchup.limit=0` for the old behaviour. `synthesize_tasks()`
  called directly is uncapped unless `catchup_limit=` is passed. (#9)
- The CLI no longer runs the recurrence pass twice for commands it hands
  to the parser (`count`, `add`, `done`, …).

### Fixed
- **Atomic writes** — `write_tasks` writes to a temp file in the same
  directory and renames it over the target, so a crash mid-write can no
  longer truncate the YAML file. (#6, #12)
- **Cross-process write lock** — writes take an OS-level exclusive lock
  on a `<file>.lock` sidecar (`fcntl.flock` on POSIX, an exclusive-create
  sidecar with a 30 s timeout on Windows) on top of the in-process
  `RLock`, so two processes can't write the same file at the same time.
  See `docs/storage.md` for what this does and doesn't guarantee. (#7, #17)
- **ID cache growth** — the ephemeral-ID cache is capped at 256 entries
  (oldest evicted first) instead of growing by one entry per write for
  the life of a long-running host process. (#13, #15)

### Tests
- Rich renderers other than the calendar (`render_report`, `render_list`,
  `render_info`, `render_history`, `render_ghistory`, `render_burndown`,
  `confirm`, `error`) are now covered. (#19)

### Docs
- README, `docs/cli.md` and the landing page now show the CLI the way
  it's meant to be typed — `tp add …`, `tp 1 done` — and say outright
  that the leading `task` word is optional.
- `docs/storage.md` documents atomic writes, the `<file>.lock` sidecar
  and the limits of the cross-process lock.

---

## [0.4.0] — 2026-07-14

The big Taskwarrior-parity release: TaskPeasant now aims to be
"Taskwarrior logic ported to Python, as close as we could get".
Everything below is additive — the frozen contract in
`docs/BACKWARDS_COMPAT.md` is untouched and its test suite passes
unmodified.

### Added
- **Taskrc config system** (`_taskrc.py`) — TW-style `key=value` config
  with `include`, layered defaults ← file ← `rc.key=value` command-line
  overrides, `rc:<path>` alternate file. Search order:
  `$TASKPEASANT_TASKRC`/`$TASKRC`, `~/.taskpeasantrc` (taskrc format),
  `$XDG_CONFIG_HOME/taskpeasant/taskrc`. A YAML-mapping
  `~/.taskpeasantrc` keeps the legacy 0.3 config behaviour.
  New commands: `task show [pattern]`, `task config <key> [value]`.
  `execute_command` gained an optional `config=` keyword (Taskrc).
- **Report engine** (`report_engine.py`) — TW report definitions
  (`report.<name>.columns/labels/sort/filter`) with all TW built-ins:
  `next`, `list`, `ls`, `minimal`, `long`, `all`, `active`, `blocked`,
  `blocking`, `unblocked`, `completed`, `newest`, `oldest`, `overdue`,
  `ready`, `recurring`, `waiting`. TW column formats
  (`description.count`, `due.relative`, `entry.age`, `uuid.short`,
  `depends.indicator`, `tags.count`, `status.short`, UDA columns, …),
  sort specs (`urgency-,due+`), `limit:N` / `limit:page`, empty columns
  dropped. Custom reports via taskrc or `rc.report.foo.*` overrides.
  `task reports` and `task columns` list what's available.
- **Filter parity** — TW attribute modifiers (`.before/.after/.by/
  .over/.under/.above/.below/.is/.isnt/.has/.hasnt/.startswith/
  .endswith/.left/.right/.word/.noword`), plain date-attribute day
  matching (`due:tomorrow`), `/regex/` tokens, ID ranges (`1-5`,
  `1,3,7-9`), attribute abbreviations (`proj:`, `pri:`, `desc.has:`),
  project hierarchy matching (`project:film` matches `film.editing`),
  UDA filters, `entry`/`end`/`modified`/`start` filterable.
- **Date parity** — compound expressions (`eom-2d`, `now+3h`,
  `monday+1w`), signed offsets with unit words (`-2w`, `+90min`),
  `eod`/`sod`, `soq`/`eoq`, ordinals (`23rd`), epoch timestamps.
- **TW urgency polynomial** — the real Taskwarrior formula is now the
  default: coefficient × measure with the due-date ramp (0.2 → 1.0
  across due−14d…due+7d), tiered tag/annotation measures, age/365,
  waiting −3, blocking +8, blocked −5, `+next` +15. All coefficients
  configurable via `urgency.*` keys, including
  `urgency.uda.<name>[.<value>].coefficient`,
  `urgency.user.tag/project/keyword.<x>.coefficient`, and
  `urgency.inherit`. Passing an `UrgencyConfig` (or mutating `WEIGHTS`)
  still selects the pre-0.4 additive model, unchanged.
- **Graphical reports** — `burndown.daily/.weekly/.monthly` (stacked
  pending/started/done, net fix rate, estimated completion),
  `history` and `ghistory` in `daily/weekly/monthly/annual` variants
  (filterable), TW-style `calendar` (`due`, `<year>`, `<month> <year>`,
  `weekstart`, `calendar.details`), `summary` (per-project completion
  bars), `stats`, `timesheet [weeks]`, `projects`, `tags`, `udas`.
- **Lifecycle commands** — `undo` (journal in a sidecar `<file>.undo`,
  never a new YAML key), `duplicate`, `purge` (deleted-only; cleans
  dangling depends), `log`, `append`, `prepend`, `denotate`, `import`
  (TW wire JSON, merges by uuid), `task edit` (`$EDITOR`, CLI only),
  `version`. All work single-target, by ID, and as bulk filter ops.
- **Helper commands** — `ids` (compact ranges), `uuids`, `_ids`,
  `_uuids`, `_projects`, `_tags`, `_commands`, `_get <ref>.<attr>`.
- **Color rules** (`_colors.py`) — TW `color.*` rules with
  `rule.precedence.color`, TW color specs (`color15`, `rgb530`,
  `gray10`, `bright red on yellow`) mapped to rich styles, applied to
  every CLI report row; `task colors`.
- **Aliases & contexts** — `alias.<name>` first-token expansion;
  `task context define/set/none/show/list/delete` with read filters
  applied to reports/export/count and write filters applied on `add`
  (`context.<name>.read`/`.write` split supported).
- **Recurrence — opt-in** (`recurrence=on`, default **off**) —
  `recur:`/`until:` on add create templates (status `recurring`),
  children synthesized per command with catch-up and
  `recurrence.limit` future instances, TW `mask`/`imask` bookkeeping,
  `until` expiry. Off by default so embedded hosts never see a fifth
  status value without opting in.
- **Virtual tags** — `+READY`, `+UNBLOCKED`, `+UDA`, `+LATEST`,
  `+PRIORITY`, `+UNTIL`, `+PARENT`, `+CHILD` join the 0.3 set.

### Changed
- Default urgency model is TW's polynomial (see Added); the additive
  model remains available through the frozen `UrgencyConfig`/`WEIGHTS`
  paths, so embedder scores are reproducible bit-for-bit.
- Bare `task [filter]` now runs the `default.command` report (`list`);
  set `default.command=next` for stock-TW behaviour.
- `rc.*` tokens: known keys are now honored as per-call overrides;
  unknown keys are still silently ignored (the 0.3 contract floor).

---

## [0.3.0] — 2026-07-12

TaskWarrior-parity sprint: virtual tags, boolean filter expressions, bulk
operations, dependency wiring, configurable urgency, config file, and a
test suite guarding the backwards-compat contract.

### Added
- **Virtual tags** — computed at read time, never persisted: `+PENDING`,
  `+COMPLETED`, `+DELETED`, `+WAITING`, `+ACTIVE`, `+OVERDUE`, `+TODAY`,
  `+DUE` (7-day horizon), `+SCHEDULED`, `+TAGGED`, `+ANNOTATED`,
  `+PROJECT`, and graph-aware `+BLOCKED` / `+BLOCKING`. Filterable with
  the usual `+TAG` / `-TAG` syntax; shown in `info` views. Real tags that
  collide with virtual names are rejected.
- **Boolean filter expressions** — `and`, `or`, `xor`, `not` operators and
  parenthesised groups in any filter (`task "(+urgent or +OVERDUE)" list`).
  Precedence: `not` > `and` > `xor` > `or`; plain token lists keep the old
  implicit-AND behaviour. New leaf filters: `tag.any:` / `tag.none:`
  (comma-separated any-of / none-of) and `description.contains:` /
  `description.has:`.
- **Bulk operations** — any filter may precede a mutation verb:
  `task +urgent done`, `task project:film modify priority:H`. One read,
  one write; inapplicable tasks are skipped and counted. The rich CLI
  asks for confirmation when more than one task would be touched (new
  `--yes` / `-y` flag skips it).
- **`depends:` wiring** — `task 1 modify depends:2,-3` resolves integer
  IDs and UUID prefixes to full UUIDs, supports add / `-`remove / clear
  (empty value), and rejects self-dependencies and cycles. Feeds
  `+BLOCKED` / `+BLOCKING` and the urgency graph factors.
- **`UrgencyConfig`** — frozen dataclass of all urgency coefficients;
  `compute_urgency(task, config=...)`, `assign_ids(..., config=...)` and
  `cmd_export(..., config=...)` accept it. New `blocking` factor (+1.0)
  rewards tasks that other open tasks depend on. Exported alongside
  `DEFAULT_CONFIG` and `cmd_bulk`.
- **Config file** — `$TASKPEASANT_CONFIG`, then
  `$XDG_CONFIG_HOME/taskpeasant/config.yaml`, then `~/.taskpeasantrc`.
  Keys: `data.location`, `default.project`, `urgency.*` overrides.
  CLI-only; the library path never reads it.
- **Test suite + CI** — pytest suite (149 tests) including a frozen
  backwards-compat contract file; GitHub Actions matrix on Python
  3.9–3.13.

### Changed
- Bare `and` / `or` / `xor` / `not` tokens in filters are now operators,
  not description-search words (quote them to search literally).
- `task <filter> <verb>` is now a bulk operation. A bare verb with no
  filter (`task done`) remains a description search — there is no
  filterless "complete everything". Filter tokens the engine cannot
  evaluate abort a bulk operation instead of matching every task.
- `task <id> delete` on an already-deleted task now reports it instead
  of re-stamping `end`/`modified`.
- Empty modify values clear fields (TW convention): `due:`, `scheduled:`,
  `wait:` (releases a waiting task back to pending), `project:`,
  `priority:`; an empty UDA value deletes the UDA. A blank
  `description:` is rejected.
- `execute_command` now guards its full dispatch path, hardening the
  never-raise contract.

### Fixed
- `task <id> modify due:` no longer fails with a false
  "not a recognised date" error (empty value now means *clear*).
- The `tp` CLI re-quotes tokens when delegating mutations, so multi-word
  quoted values survive the round trip.
- `tag.any:` / `tag.none:` previously fell through to the generic field
  presence check and matched nothing / everything; they now test real
  tag-list membership.

---

## [0.2.0] — 2026-07-10

_(Entry reconstructed — 0.2.0 shipped without a changelog entry.)_

### Added
- Ephemeral integer IDs (urgency-sorted, mtime-cached, never persisted).
- `project:`, `priority:` (H/M/L) and `wait:` fields with auto
  `waiting→pending` transition.
- Report suite: `next`, `all`, `completed`, `waiting`, `count`,
  `history`, `ghistory`, `burndown`, `calendar`; single-task `info` view.
- Extended date math (`+Nd/w/m/y`) and more aliases (`now`, `sow`/`som`/
  `soy`, `eoww`, `eoy`, weekday short forms, `someday`).
- Richer filters: `due.before:`/`.after:` (and scheduled/wait),
  `project:`/`priority:` filters.
- Rich CLI layer (`tp` / `taskpeasant` entry points).
- Docs: parity.md, storage.md, cli.md, api.md, BACKWARDS_COMPAT.md.

---

## [0.1.0] — 2026-06-19

Initial extraction from the [analogtrsh Studio OS](https://github.com/alexgc96/analogtrsh) monorepo into a standalone repository.

### Added
- Public API: `Task`, `read_tasks`, `write_tasks`, `cmd_add`, `cmd_done`, `cmd_delete`, `cmd_start`, `cmd_stop`, `cmd_annotate`, `cmd_modify`, `cmd_export`, `compute_urgency`, `execute_command`.
- TaskWarrior-compatible JSON export (`Task.to_tw_export()`).
- Subset of the TaskWarrior CLI grammar (`add`, `done`, `delete`, `start`, `stop`, `annotate`, `modify`, `+tag`, `-tag`, `due:`, `scheduled:`, `status:`, `+tag export`, `rc.*` silently stripped).
- Filter engine with `+tag`, `-tag`, `status:`, `uuid:`, `<field>.any:` / `.none:`, bare-word description search.
- Urgency model — additive, transparent, mirrors TW's weight ranges so existing UI urgency bars work unchanged.
- YAML storage under dedicated `taskpeasant_tasks:` key with per-file locking and legacy `tasks:`-as-list fallback.
- Date aliases: `today`, `tomorrow`, `yesterday`, `eow`, `eom`, weekday names.

[Unreleased]: https://github.com/alexgc96/taskpeasant/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/alexgc96/taskpeasant/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/alexgc96/taskpeasant/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/alexgc96/taskpeasant/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/alexgc96/taskpeasant/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/alexgc96/taskpeasant/releases/tag/v0.1.0
