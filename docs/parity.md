# TaskWarrior Parity Matrix

> Status as of TaskPeasant **0.2.0**.
> ✓ = fully supported · ~ = partial / different implementation · ✗ = not supported

---

## Fields

| Field | TW | TaskPeasant | Notes |
|---|---|---|---|
| `uuid` | ✓ | ✓ | Full UUID v4, stored as-is |
| `description` | ✓ | ✓ | |
| `status` | ✓ | ✓ | `pending`, `completed`, `deleted`, `waiting` |
| `entry` | ✓ | ✓ | ISO 8601 in YAML, TW wire on export |
| `start` | ✓ | ✓ | Set by `start`, cleared by `stop`/`done` |
| `end` | ✓ | ✓ | Set on `done`/`delete` |
| `due` | ✓ | ✓ | |
| `scheduled` | ✓ | ✓ | |
| `wait` | ✓ | ✓ | Auto-transitions `waiting→pending` at read time |
| `modified` | ✓ | ✓ | Updated on every mutation |
| `tags` | ✓ | ✓ | List; `+tag`/`-tag` syntax |
| `depends` | ✓ | ✓ | List of UUID strings; comma-string on TW wire export |
| `annotations` | ✓ | ✓ | `[{entry, description}]` |
| `project` | ✓ | ✓ | String; `project:name` syntax |
| `priority` | ✓ | ✓ | `H`, `M`, `L`; affects urgency |
| `id` (ephemeral) | ✓ | ✓ | Assigned at read time, urgency-sorted, never stored |
| `urgency` | ✓ | ~ | Additive model vs TW's polynomial — same 0–20 range |
| `recur` | ✓ | ✗ | Use a UDA + host-side logic if needed |
| `until` | ✓ | ✗ | Recurring-task field; not applicable |
| `mask` / `imask` | ✓ | ✗ | Recurring internals; out of scope |

---

## Commands

| Command | TW | TaskPeasant | Notes |
|---|---|---|---|
| `task add` | ✓ | ✓ | |
| `task <id> done` | ✓ | ✓ | Accepts integer ID or UUID prefix |
| `task <id> delete` | ✓ | ✓ | |
| `task <id> start` | ✓ | ✓ | |
| `task <id> stop` | ✓ | ✓ | |
| `task <id> annotate` | ✓ | ✓ | |
| `task <id> modify` | ✓ | ✓ | |
| `task <id> info` | ✓ | ✓ | Full detail view |
| `task next` | ✓ | ✓ | Top 25 pending by urgency |
| `task all` | ✓ | ✓ | All statuses |
| `task completed` | ✓ | ✓ | Completed tasks, most recent first |
| `task waiting` | ✓ | ✓ | Waiting tasks with wait date |
| `task count` | ✓ | ✓ | Accepts filter tokens |
| `task export` | ✓ | ✓ | TW-wire JSON; used by Studio OS |
| `task list` | ✓ | ~ | Implicit on bare `task` call |
| `task <id> edit` | ✓ | ✗ | No `$EDITOR` integration |
| `task sync` | ✓ | ✗ | Intentionally local-first |
| `task undo` | ✓ | ✗ | No undo log |
| `task duplicate` | ✓ | ✗ | |
| `task purge` | ✓ | ✗ | |
| `task calendar` | ✓ | ✗ | Host UI responsibility |
| `task burndown` | ✓ | ✗ | Host UI responsibility |

---

## Filter Syntax

| Filter | TW | TaskPeasant | Notes |
|---|---|---|---|
| `+tag` / `-tag` | ✓ | ✓ | |
| `status:<value>` | ✓ | ✓ | `status:pending` also matches `waiting` (TW behaviour) |
| `uuid:<prefix>` | ✓ | ✓ | |
| `project:<name>` | ✓ | ✓ | Exact match, case-insensitive |
| `priority:<H\|M\|L>` | ✓ | ✓ | |
| `due.any:` / `due.none:` | ✓ | ✓ | Works for any date field |
| `due.before:<date>` | ✓ | ✓ | Date aliases and `+Nd` offsets resolved |
| `due.after:<date>` | ✓ | ✓ | |
| `scheduled.before/after:` | ✓ | ✓ | |
| `wait.before/after:` | ✓ | ✓ | |
| `project.any:` / `project.none:` | ✓ | ✓ | |
| bare word | ✓ | ✓ | Case-insensitive description substring |
| `AND` / `OR` / `NOT` operators | ✓ | ✗ | All tokens are AND'd |
| Parenthesised expressions | ✓ | ✗ | |
| `description.contains:` | ✓ | ~ | Bare word does the same thing |
| `tag.any:` / `tag.none:` | ✓ | ✗ | Use `+tag` / `-tag` |

---

## Date Syntax

| Alias | TW | TaskPeasant |
|---|---|---|
| `today` | ✓ | ✓ |
| `tomorrow` | ✓ | ✓ |
| `yesterday` | ✓ | ✓ |
| `eow` (end of week) | ✓ | ✓ |
| `eom` (end of month) | ✓ | ✓ |
| Weekday names (`monday` etc.) | ✓ | ✓ |
| `+Nd` / `+Nw` / `+Nm` / `+Ny` | ✓ | ✓ |
| `eoy` (end of year) | ✓ | ✗ |
| `som` / `sow` (start of …) | ✓ | ✗ |
| `now` | ✓ | ✗ |

---

## Urgency Factors

| Factor | TW weight | TaskPeasant weight |
|---|---|---|
| Active (`start` set) | 15.0 | 15.0 |
| Overdue | 12.0 | 12.0 |
| Due today (< 24h) | 8.0 | 8.0 |
| Due soon (< 7d) | 4.0 | 4.0 |
| Scheduled | 2.0 | 2.0 |
| Priority H | 6.0 | 6.0 |
| Priority M | 3.9 | 3.9 |
| Priority L | 1.8 | 1.8 |
| Tag `+next` | 3.5 | 3.5 |
| Tag `+urgent` | 6.0 | 6.0 |
| Annotations | 0.5 each (max 2.0) | 0.5 each (max 2.0) |
| Age | 0.01/day (max 2.0) | 0.01/day (max 2.0) |
| Blocked (has `depends`) | −5.0 | −5.0 |

TW uses a polynomial; TaskPeasant uses a transparent additive model. Output range is equivalent (~0–20) so UI urgency bars need no changes.

**Roadmap:** v0.3.0 introduces `UrgencyConfig` — a dataclass that replaces the
hardcoded `WEIGHTS` dict and makes all coefficients configurable per-caller.
This is the seam through which a full TW polynomial evaluator can be plugged in later.

---

## Intentional Gaps

| Feature | Reason |
|---|---|
| Recurring tasks | Engine complexity; host app can replicate with UDAs + cron |
| Sync / conflict resolution | Intentionally local-first and filesystem-backed |
| Configuration file | Planned for v0.3.0 — `UrgencyConfig` dataclass + `~/.config/taskpeasant/config.yaml` |
| Colour rules | Host UI owns rendering |
| Report definitions | Host exports flat JSON and renders its own views |
| Daemon / server | Pure library — host app owns the HTTP layer |
