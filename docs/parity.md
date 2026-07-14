# Taskwarrior Parity Matrix

> Status as of TaskPeasant **0.4.0**.
> ✓ = supported · ~ = partial / different implementation · ✗ = not supported
>
> The reference is Taskwarrior 2.6.x (GothenburgBitFactory/taskwarrior,
> GPL-3.0 — the same license as this project). Where behaviour differs,
> the notes say how.

---

## Fields

| Field | TW | TaskPeasant | Notes |
|---|---|---|---|
| `uuid` | ✓ | ✓ | Full UUID v4, stored as-is |
| `description` | ✓ | ✓ | |
| `status` | ✓ | ✓ | `pending`, `completed`, `deleted`, `waiting`; `recurring` **opt-in** (see Recurrence) |
| `entry` / `modified` | ✓ | ✓ | ISO 8601 in YAML, TW wire on export |
| `start` / `end` | ✓ | ✓ | Set by `start`/`stop`/`done`/`delete` |
| `due` / `scheduled` / `wait` | ✓ | ✓ | `wait` auto-releases `waiting→pending` at read time |
| `until` | ✓ | ✓ | Expires open tasks (status→deleted) — only when `recurrence=on` |
| `recur` / `parent` / `mask` / `imask` | ✓ | ✓ | Opt-in recurrence engine, TW bookkeeping |
| `tags` | ✓ | ✓ | `+tag`/`-tag` syntax |
| `depends` | ✓ | ✓ | UUID list in YAML, comma-string on TW wire; ID/prefix resolution, cycle rejection |
| `project` | ✓ | ✓ | Hierarchical: `project:film` matches `film.editing` |
| `priority` | ✓ | ✓ | H/M/L via the `urgency.uda.priority.*` mechanism, like TW |
| `annotations` | ✓ | ✓ | `[{entry, description}]`; `annotate`/`denotate` |
| UDAs | ✓ | ✓ | Unknown keys round-trip; `uda.<name>.type/label` config; UDA columns, filters, urgency coefficients |
| `id` (ephemeral) | ✓ | ~ | Assigned at read time, **urgency-sorted** (TW uses storage order) |
| `urgency` | ✓ | ✓ | TW polynomial (see Urgency) |

## Commands

| Command | TW | TaskPeasant | Notes |
|---|---|---|---|
| `add` / `log` | ✓ | ✓ | |
| `done` / `delete` / `start` / `stop` | ✓ | ✓ | By ID, UUID prefix, or bulk filter |
| `modify` / `annotate` / `denotate` / `append` / `prepend` | ✓ | ✓ | Single, ID, or bulk |
| `duplicate` / `purge` | ✓ | ✓ | `purge` is deleted-only and cleans dangling depends, like TW |
| `undo` | ✓ | ✓ | Journal in sidecar `<file>.undo` (contract forbids new YAML keys); task-level restore, capped by `undo.limit` |
| `info` | ✓ | ✓ | |
| `edit` | ✓ | ✓ | CLI only (`$EDITOR` round-trip of one task as YAML) |
| `import` / `export` | ✓ | ✓ | TW wire JSON; import merges by uuid, accepts array or line-delimited |
| `count` / `ids` / `uuids` | ✓ | ✓ | `ids` prints compact ranges |
| `_ids` / `_uuids` / `_projects` / `_tags` / `_commands` / `_get` | ✓ | ✓ | `_get` supports `<id\|uuid>.<attribute>` |
| all built-in reports | ✓ | ✓ | next, list, ls, minimal, long, all, active, blocked, blocking, unblocked, completed, newest, oldest, overdue, ready, recurring, waiting |
| custom reports | ✓ | ✓ | `report.<name>.columns/labels/sort/filter` in taskrc or `rc.` overrides |
| `reports` / `columns` / `colors` / `show` / `config` | ✓ | ✓ | |
| `context` | ✓ | ✓ | define/set/none/show/list/delete; `.read`/`.write` split |
| `calendar` | ✓ | ✓ | `due` / `<year>` / `<month> <year>` args, weekstart, details legend |
| `burndown.daily/.weekly/.monthly` | ✓ | ✓ | Stacked pending/started/done + net fix rate + ETA |
| `history` / `ghistory` ×(daily/weekly/monthly/annual) | ✓ | ✓ | Filterable |
| `summary` / `stats` / `timesheet` / `projects` / `tags` / `udas` | ✓ | ✓ | |
| `version` / aliases (`alias.*`) | ✓ | ✓ | Alias expands the first command token |
| `sync` | ✓ | ✗ | **Intentional** — TaskPeasant is local-first; the YAML file is the sync surface |
| `diagnostics` / `execute` / `calc` | ✓ | ✗ | Low value in an embedded engine |
| Hooks (`on-add`, `on-modify`, …) | ✓ | ✗ | Host apps embed the library and hook in Python instead |

## Filters

| Filter | TW | TaskPeasant | Notes |
|---|---|---|---|
| `+tag` / `-tag` (real + virtual) | ✓ | ✓ | |
| `attr:value` | ✓ | ✓ | Dates match the whole day; empty value = "none" |
| Attribute modifiers | ✓ | ✓ | `before/after/by/over/under/above/below/is/isnt/equals/not/has/contains/hasnt/startswith/left/endswith/right/word/noword/any/none` |
| Attribute abbreviation | ✓ | ✓ | Unique-prefix (`proj:`, `pri:`, `desc.has:`) |
| `and` / `or` / `xor` / `not`, parens | ✓ | ✓ | Precedence `not > and > xor > or`; implicit AND |
| ID / ID ranges | ✓ | ✓ | `3`, `1-5`, `1,3,7-9` |
| `/regex/` | ✓ | ✓ | Case-insensitive against description |
| `limit:N` / `limit:page` | ✓ | ✓ | `page` = 25 rows in plain output |
| UDA filters | ✓ | ✓ | `size:large`, `size.has:...` |
| Virtual tags | ✓ | ✓ | 0.3 set + `READY`, `UNBLOCKED`, `UDA`, `LATEST`, `PRIORITY`, `UNTIL`, `PARENT`, `CHILD` |

## Dates

| Syntax | TW | TaskPeasant |
|---|---|---|
| `today` `tomorrow` `yesterday` `now` | ✓ | ✓ |
| `sod` `eod` `sow` `eow` `soww` `eoww` | ✓ | ✓ |
| `som` `eom` `soq` `eoq` `soy` `eoy` | ✓ | ✓ |
| weekday names (`monday`, `fri`) | ✓ | ✓ |
| ordinals (`23rd`) | ✓ | ✓ |
| epoch (10-digit) | ✓ | ✓ |
| signed offsets (`+3d`, `-2w`, `+90min`, `+2wks`) | ✓ | ✓ |
| compound (`eom-2d`, `now+3h`, `monday+1w`) | ✓ | ✓ |
| `someday` / `later` | ✓ | ~ | TW pins 2038; TP uses +9 years |
| holiday files / locale dates | ✓ | ✗ | |

## Urgency

The TW polynomial is the default: each factor is a measure in [0, 1]
multiplied by an `urgency.<factor>.coefficient` (all TW default values):
active 4.0, scheduled 5.0 (once arrived), waiting −3.0, blocked −5.0,
blocking 8.0, project 1.0, tags 1.0 and annotations 1.0 (tiered
0.8/0.9/1.0), age 2.0 (linear to `urgency.age.max`=365), due 12.0 with
TW's ramp (0.2 at due−14d → 1.0 at due+7d), priority via
`urgency.uda.priority.{H,M,L}.coefficient` = 6.0/3.9/1.8, and
`urgency.user.tag.next.coefficient` = 15.0.

Also supported: `urgency.user.tag/project/keyword.<x>.coefficient`,
`urgency.uda.<name>[.<value>].coefficient`, `urgency.inherit`.

Deviations from TW (frozen by the embedder contract): the score is
rounded to 2 decimals and clamped ≥ 0. The pre-0.4 additive model is
still selected when a caller passes an `UrgencyConfig` or mutates the
legacy `WEIGHTS` dict.

## Recurrence (opt-in)

Fully implemented but **off by default** — the embedder contract freezes
the status enum, so `recur:` is rejected until the host sets
`recurrence=on`. When enabled: TW template/child model (`parent`,
`mask`, `imask`), duration grammar (`daily`, `weekdays`, `weekly`,
`monthly`, `3d`, `2w`, `1y`, …), catch-up synthesis plus
`recurrence.limit` (default 1) future instances, `until` stops spawning
and expires open tasks.

## Color rules

`color.active/blocked/blocking/overdue/due/due.today/scheduled/
recurring/tagged/completed/deleted`, `color.tag.<t>`,
`color.project.<p>`, `color.keyword.<w>`, `color.uda.<n>[.<v>]`, with
`rule.precedence.color` ordering. TW color specs (`color15`, `rgb530`,
`gray10`, `bright red on yellow`) map onto `rich` styles. CLI only —
the embedded `execute_command` path stays plain text by design.

## Intentional gaps

| Feature | Reason |
|---|---|
| `task sync` / taskserver | Local-first by design; the YAML file is the sync surface |
| Hooks | Embed the library and hook in Python |
| Holiday calendars, locale date formats | Low value; contributions welcome |
| `dateformat` rendering variants | Reports render ISO dates |
| News/nagging (`task news`, nag messages) | Deliberately quiet |
