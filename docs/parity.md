# TaskWarrior Parity Matrix

> Status as of TaskPeasant **0.3.0**.
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
| `depends` | ✓ | ✓ | List of UUID strings; comma-string on TW wire export. `modify depends:2,-3` resolves IDs/prefixes, rejects cycles |
| virtual tags | ✓ | ✓ | `+PENDING/+COMPLETED/+DELETED/+WAITING/+ACTIVE/+OVERDUE/+TODAY/+DUE/+SCHEDULED/+TAGGED/+ANNOTATED/+PROJECT/+BLOCKED/+BLOCKING` — computed at read time, filterable, never persisted |
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
| `task <filter> <verb>` (bulk) | ✓ | ✓ | Any filter before done/delete/start/stop/modify/annotate; bare verb stays a search (no filterless bulk) |
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
| `and` / `or` / `xor` / `not` operators | ✓ | ✓ | Precedence: `not` > `and` > `xor` > `or`; implicit AND for plain lists |
| Parenthesised expressions | ✓ | ✓ | `( … )` groups; parens may be glued to tokens |
| `description.contains:` | ✓ | ✓ | Also `description.has:`; bare word does the same thing |
| `tag.any:` / `tag.none:` | ✓ | ✓ | Comma-separated any-of / none-of; empty value = has any / no tags |
| Virtual tags in filters | ✓ | ✓ | `+OVERDUE`, `-BLOCKED`, etc. |

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
| `eoy` / `soy` (year boundaries) | ✓ | ✓ |
| `som` / `sow` (start of …) | ✓ | ✓ |
| `eoww` (end of work week) | ✓ | ✓ |
| `now` | ✓ | ✓ |
| `someday` / `later` | ✓ | ✓ |

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
| Blocked (unresolved open `depends`) | −5.0 | −5.0 |
| Blocking (other open tasks depend on it) | 1.0 | 1.0 |

TW uses a polynomial; TaskPeasant uses a transparent additive model. Output range is equivalent (~0–20) so UI urgency bars need no changes.

All coefficients are configurable per caller via the `UrgencyConfig`
dataclass (`compute_urgency(task, config=…)`) or via the `urgency:` section
of the CLI config file. The legacy `WEIGHTS` dict is still honoured when no
config is passed. `UrgencyConfig` is also the seam through which a full TW
polynomial evaluator can be plugged in later.

---

## Intentional Gaps

| Feature | Reason |
|---|---|
| Recurring tasks | Engine complexity; host app can replicate with UDAs + cron |
| Sync / conflict resolution | Intentionally local-first and filesystem-backed |
| Colour rules | Host UI owns rendering |
| Report definitions | Host exports flat JSON and renders its own views |
| Daemon / server | Pure library — host app owns the HTTP layer |

(The configuration file and `UrgencyConfig`, listed as gaps in 0.2.0,
shipped in 0.3.0.)
