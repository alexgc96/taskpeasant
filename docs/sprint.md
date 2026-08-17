# Sprint — TaskPeasant

> Lightweight tracking for what's being worked on now, what's queued, and what's done.
> Mirrors the analogtrsh Studio OS sprint convention.

---

## Current sprint

_Sprint:_ (between sprints — v0.4.0 shipped)
_Dates:_ —
_Goal:_ —

---

## Next sprint — v0.5.0 candidates

_Promote to active when ready to cut a new sprint._

- [ ] **Atomic writes** — temp-file + rename in `write_tasks`; a crash
  mid-write today can truncate the file.
- [ ] **Cross-process file locking** — current locking is in-process only;
  concurrent writers from separate processes can race.
- [ ] **`task sync` stub** — no-op with a clear message, sets expectations
  for embedders who might call it.
- [ ] **PyPI publish** — first public release; tag `v0.5.0`, push to PyPI.

## Backlog

_(Unscheduled. Promote when ready.)_

- Recurrence: catch-up cap — `recurrence.limit` only applies to future
  instances; a long-dormant file can still synthesize many past-due children
  at once.

---

## Recently shipped

_(Most recent first. Trim entries once they roll into a release in `CHANGELOG.md`.)_

- **0.4.0** — TW parity sprint 3: taskrc config system (`show`, `config`
  commands, `rc.key=val` overrides, layered search order), full report
  engine with all TW built-ins + custom reports, filter parity (attribute
  modifiers, date-attribute day matching, `/regex/`, ID ranges, abbreviations,
  project hierarchy), date parity (compound expressions, signed offsets,
  `eod/sod/soq/eoq`, ordinals, epoch timestamps), TW urgency polynomial
  as default (due-date ramp, all coefficients configurable via `urgency.*`),
  graphical reports (`burndown.*`, `history`, `ghistory`, `calendar`,
  `summary`, `stats`, `timesheet`, `projects`, `tags`, `udas`), lifecycle
  commands (`undo` via sidecar `.undo` file, `duplicate`, `purge`, `log`,
  `append`, `prepend`, `denotate`, `import`, `edit`), helper commands
  (`ids`, `uuids`, `_ids`, `_uuids`, `_projects`, `_tags`, `_commands`,
  `_get`), color rules, aliases, contexts, opt-in recurrence engine.
- **0.3.0** — TW parity sprint 2: virtual tags (+OVERDUE/+BLOCKED/+BLOCKING…),
  boolean filter expressions (and/or/xor/not + parens, tag.any/none,
  description.contains), bulk filter operations (`task +urgent done`) with
  CLI confirmation + `--yes`, depends: wiring (ID/prefix resolution, cycle
  detection), date clearing (`due:` empty), UrgencyConfig dataclass +
  blocking bonus, XDG config file (data.location / default.project /
  urgency.*), pytest suite (149 tests) + GitHub Actions CI (3.9–3.13).
- **0.2.0** — v2 sprint: integer IDs, project/priority/wait fields, full report suite
  (history, ghistory, burndown, calendar, next, all, completed, waiting, count),
  extended date math, richer filter operators, rich CLI layer (`_rich.py` / `__main__.py`),
  complete docs (parity.md, storage.md, cli.md, api.md), CHANGELOG.
- **0.1.0** — initial extraction from analogtrsh Studio OS monorepo. Frozen public API:
  13 symbols, YAML storage, 8 commands, urgency scoring, filter engine, TW-compatible export.
