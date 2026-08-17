# Sprint — TaskPeasant

> Lightweight tracking for what's being worked on now, what's queued, and what's done.
> Mirrors the analogtrsh Studio OS sprint convention.

---

## Current sprint

_Sprint:_ (between sprints — v0.3.0 shipped)
_Dates:_ —
_Goal:_ —

---

## Next sprint — v0.4.0 candidates

_Promote to active when v0.3.0 is tagged and published._

- [ ] **`task undo`** — needs a journaling substrate. The storage contract
  forbids new top-level YAML keys, so the undo log must live in a separate
  file (e.g. `<file>.undo.yaml`) or a namespaced sub-key. Design first.
- [ ] **`task duplicate`** — additive command, straightforward.
- [ ] **`task purge`** — actually remove `deleted` entries from the list.
- [ ] **`task <id> edit`** — open task in `$EDITOR` (CLI-only).
- [ ] **Recurring tasks engine** — must avoid a 5th status value
  (contract §7): model as pending + UDAs.
- [ ] **`task sync` stub** — no-op with a clear message, sets expectations.
- [ ] **Urgency: custom polynomial evaluator hook on `UrgencyConfig`** —
  the seam exists; TW-exact scoring as a drop-in.

## Backlog

_(Post-v0.4 ideas. Promote when ready.)_

- Atomic writes (temp-file + rename) in `write_tasks` — today a crash
  mid-write can truncate the file.
- Cross-process file locking (locking is currently in-process only).

---

## Recently shipped

_(Most recent first. Trim entries once they roll into a release in `CHANGELOG.md`.)_

- **0.3.0** — TW parity sprint 2: virtual tags (+OVERDUE/+BLOCKED/+BLOCKING…),
  boolean filter expressions (and/or/xor/not + parens, tag.any/none,
  description.contains), bulk filter operations (`task +urgent done`) with
  CLI confirmation + `--yes`, depends: wiring (ID/prefix resolution, cycle
  detection), date clearing (`due:` empty), UrgencyConfig dataclass +
  blocking bonus, XDG config file (data.location / default.project /
  urgency.*), pytest suite (149 tests) + GitHub Actions CI (3.9–3.13).
  Also: fixed stale parity.md date-alias rows (eoy/som/sow/now were
  already implemented in 0.2.0).
- **0.2.0** — v2 sprint: integer IDs, project/priority/wait fields, full report suite
  (history, ghistory, burndown, calendar, next, all, completed, waiting, count),
  extended date math, richer filter operators, rich CLI layer (`_rich.py` / `__main__.py`),
  complete docs (parity.md, storage.md, cli.md, api.md), CHANGELOG.
- **0.1.0** — initial extraction from analogtrsh Studio OS monorepo. Frozen public API:
  13 symbols, YAML storage, 8 commands, urgency scoring, filter engine, TW-compatible export.
