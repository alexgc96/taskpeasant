# CLI Reference

TaskPeasant ships a Python module entry point:

```bash
python3 -m taskpeasant [--file FILE] [--yes] [command tokens…]
# short alias once installed via pip/pipx:
tp [--file FILE] [--yes] [command tokens…]
```

**Default file** — resolved in this order:

1. `--file` / `-f` flag
2. `TASKPEASANT_FILE` environment variable
3. `data.location` from the [config file](#config-file)
4. `./tasks.yaml`

```bash
export TASKPEASANT_FILE=~/tasks/work.yaml   # set once, use everywhere
```

`--yes` / `-y` skips the interactive confirmation on bulk operations.

All examples below omit `--file` for brevity.

---

## Task identifiers

Every command that targets an existing task accepts either:

- **Integer ID** — ephemeral, urgency-sorted, shown in list output (`1`, `12`)
- **UUID prefix** — first 4+ hex characters of the UUID (`8c2f`, `8c2f1a3b`)

```bash
tp task 3 done           # integer ID
tp task 8c2f1a3b done    # UUID prefix
```

---

## Commands

### add

```
task add <description> [+tag] [due:<date>] [scheduled:<date>] [wait:<date>]
         [project:<name>] [priority:<H|M|L>] [<uda>:<value>]
```

```bash
tp task add render the final shot +urgent due:tomorrow priority:H project:studio
tp task add review PR +next due:+3d
tp task add plan sprint wait:+7d project:studio
tp task add deploy release due:eom priority:M
```

### done

```
task <id> done
```

Marks the task completed. Sets `end`, clears `start`.

### delete

```
task <id> delete
```

Marks the task deleted. Sets `end`.

### start

```
task <id> start
```

Sets `start` to now (task becomes active, urgency +15).

### stop

```
task <id> stop
```

Clears `start`.

### annotate

```
task <id> annotate <text>
```

```bash
tp task 2 annotate blocked waiting on design approval
```

### modify

```
task <id> modify [+tag] [-tag] [field:<value>] …
```

```bash
tp task 3 modify priority:H due:+2d
tp task 3 modify +urgent -someday project:studio
tp task 3 modify description:updated description text
```

**Clearing fields** — an empty value removes the field (TW convention):

```bash
tp task 3 modify due:            # remove the due date
tp task 3 modify wait:           # release a waiting task back to pending
tp task 3 modify project: priority:
tp task 3 modify my_uda:         # delete the UDA entirely
```

A blank `description:` is rejected.

**Dependencies** — `depends:` takes a comma-separated list of integer IDs
or UUID prefixes; prefix an item with `-` to remove it, or pass an empty
value to clear all:

```bash
tp task 1 modify depends:2          # task 1 now depends on task 2
tp task 1 modify depends:8c2f,5     # add two dependencies
tp task 1 modify depends:-2         # remove one
tp task 1 modify depends:           # clear all
```

Self-dependencies and circular chains are rejected. Dependencies feed the
`+BLOCKED` / `+BLOCKING` virtual tags and the urgency graph factors.

### Bulk operations

Any [filter expression](#filter-syntax) may precede a mutation verb
(`done`, `delete`, `start`, `stop`, `modify`, `annotate`) to apply it to
every match:

```bash
tp task +urgent done
tp task project:film delete
tp task "(+OVERDUE or +TODAY)" modify priority:H
tp task project:studio annotate sprint slipped a week
```

Rules:

- A bare verb with **no filter** (`tp task done`) is a description search,
  never a filterless bulk operation.
- Filter tokens the engine cannot evaluate **abort** the operation rather
  than silently matching everything.
- Already-completed / already-deleted / already-active tasks are skipped
  and counted, never errors.
- The `tp` CLI asks for confirmation when more than one task would be
  touched; pass `--yes` to skip (the programmatic `execute_command` path
  applies without prompting and reports what changed).
- Integer-ID and UUID-prefix commands (`tp task 3 done`) keep their
  single-target behaviour.

### info

```
task <id> info
```

Full detail view — all fields, annotations, urgency score.

```bash
tp task 1 info
```

---

## Reports

### task / task next

```
task [filter tokens…]
task next [filter tokens…]
```

Pending tasks sorted by urgency, top 25. This is the default when no command
is given.

```bash
tp task
tp task next
tp task next +urgent
tp task next project:studio
```

### task all

```
task all [filter tokens…]
```

All tasks across all statuses.

### task completed

```
task completed
```

Completed tasks, most recent first.

### task waiting

```
task waiting
```

Waiting tasks with their wait date.

### task count

```
task count [filter tokens…]
```

Returns a plain integer — no table.

```bash
tp task count status:pending
tp task count project:studio
```

### task export

```
task [filter tokens…] export
```

JSON array in Taskwarrior wire format. Useful for scripting.

```bash
tp task +urgent export
tp task status:pending export | python3 -c "import sys,json; [print(t['description']) for t in json.load(sys.stdin)]"
```

---

## Filter syntax

Plain token lists are AND'd together. Full boolean expressions are also
supported with `and`, `or`, `xor`, `not` (case-insensitive) and
parenthesised groups:

```bash
tp task "+urgent or +next"
tp task "(project:film or project:web) and not +BLOCKED"
tp task "+TAGGED xor +ANNOTATED"
```

Precedence: `not` > `and` (explicit or juxtaposition) > `xor` > `or`,
left-associative. Because `and`/`or`/`xor`/`not` are operators, quote a
filter if you need to search for those words literally in a description
(e.g. `tp task "fix or-gate"` — any token containing more than the bare
keyword is a normal search word).

| Token | Matches |
|---|---|
| `+tag` | task has this tag (real **or virtual**) |
| `-tag` | task does NOT have this tag |
| `status:pending` | pending (also matches waiting, mirrors TW) |
| `status:completed` | completed only |
| `status:waiting` | waiting only |
| `project:<name>` | exact project name (case-insensitive) |
| `priority:<H\|M\|L>` | exact priority |
| `uuid:<prefix>` | UUID starts with prefix |
| `due.any:` | task has a due date |
| `due.none:` | task has no due date |
| `due.before:<date>` | due date is before cutoff |
| `due.after:<date>` | due date is after cutoff |
| `scheduled.before/after:<date>` | same for scheduled |
| `wait.before/after:<date>` | same for wait |
| `project.any:` / `project.none:` | project field presence |
| `tag.any:a,b` / `tag.none:a,b` | has any of / none of these tags (empty value = has any / no tags) |
| `description.contains:<text>` | description substring (alias: `description.has:`) |
| bare word | description contains this word (case-insensitive) |

```bash
tp task +urgent due.before:+7d
tp task project:studio priority:H
tp task render                      # description contains "render"
tp task count due.none: status:pending
tp task tag.any:render,edit
```

### Virtual tags

Uppercase tags are **virtual** — computed at read time from task state,
never stored, and usable anywhere a `+tag`/`-tag` filter is:

| Tag | Applies when |
|---|---|
| `+PENDING` / `+COMPLETED` / `+DELETED` / `+WAITING` | task status |
| `+ACTIVE` | `start` is set (pending tasks) |
| `+OVERDUE` | due date is in the past |
| `+TODAY` | due today |
| `+DUE` | due within 7 days (includes overdue) |
| `+SCHEDULED` | has a scheduled date |
| `+TAGGED` | has at least one real tag |
| `+ANNOTATED` | has annotations |
| `+PROJECT` | has a project |
| `+BLOCKED` | depends on at least one open task |
| `+BLOCKING` | at least one open task depends on it |

```bash
tp task +OVERDUE                    # everything past due
tp task "+DUE and not +BLOCKED"     # actionable soon
tp task +OVERDUE done               # bulk-complete the backlog
```

Real tags may not reuse virtual names (`tp task 3 modify +OVERDUE` is
rejected).

---

## Date syntax

All date fields accept the following values:

| Value | Resolves to |
|---|---|
| `now` | current timestamp |
| `today` | today at midnight UTC |
| `tomorrow` | tomorrow |
| `yesterday` | yesterday |
| `sow` / `eow` | start (Monday) / end (Sunday) of current week |
| `eoww` | end of work week (Friday) |
| `som` / `eom` | first / last day of current month |
| `soy` / `eoy` | first / last day of current year |
| `monday` … `sunday` (or `mon` … `sun`) | next occurrence of that weekday |
| `someday` / `later` | ~9 years out |
| `+3d` | 3 days from today |
| `+2w` | 2 weeks from today |
| `+1m` | 1 month from today |
| `+1y` | 1 year from today |
| `YYYY-MM-DD` | literal ISO date |
| `YYYY-MM-DDTHH:MM:SSZ` | literal ISO datetime |

---

## Config file

The `tp` CLI (and only the CLI — the Python library never reads it) loads
an optional YAML config, the first of:

1. `$TASKPEASANT_CONFIG` (explicit path)
2. `$XDG_CONFIG_HOME/taskpeasant/config.yaml` (`$XDG_CONFIG_HOME` defaults to `~/.config`)
3. `~/.taskpeasantrc`

```yaml
data:
  location: ~/tasks/work.yaml    # default YAML file (~ expanded)
default:
  project: film                  # applied to `add` when no project: given
urgency:                         # any UrgencyConfig field name
  blocking: 2.0
  priority: {H: 7.0, M: 4.0, L: 2.0}
```

Missing files and malformed YAML never break the CLI — bad content warns
to stderr and falls back to defaults. Unknown `urgency.*` keys warn and
are ignored.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TASKPEASANT_FILE` | `./tasks.yaml` | Default YAML file when `--file` is omitted |
| `TASKPEASANT_CONFIG` | _(unset)_ | Explicit legacy YAML config path (beats the XDG search) |
| `TASKPEASANT_TASKRC` / `TASKRC` | _(unset)_ | Explicit taskrc path (0.4.0+) |

---

## rc.* flags

Since 0.4.0, Taskwarrior `rc.key=value` flags are honored as per-call
config overrides for every key TaskPeasant understands (reports,
urgency, colors, aliases, contexts, recurrence, …). Unknown keys are
still silently ignored, so existing TW command strings work unchanged.
`rc:<path>` selects an alternate taskrc file.

---

## 0.4.0 — the Taskwarrior-parity release

The CLI now covers most of stock Taskwarrior. Highlights (see
[`parity.md`](parity.md) for the full matrix):

- **Reports**: `next`, `list`, `ls`, `minimal`, `long`, `all`, `active`,
  `ready`, `overdue`, `waiting`, `completed`, `blocked`, `blocking`,
  `unblocked`, `newest`, `oldest`, `recurring` — plus custom reports via
  `report.<name>.columns/labels/sort/filter` in the taskrc. Any filter
  can precede or follow the report name. `task reports`, `task columns`.
- **Graphical**: `burndown[.daily|.weekly|.monthly]`,
  `history`/`ghistory` `[.daily|.weekly|.monthly|.annual]`, `calendar
  [due | <year> | <month> <year>]`, `summary`, `stats`,
  `timesheet [weeks]`, `projects`, `tags`, `udas`, `colors`.
- **Filters**: attribute modifiers (`due.before:eow`,
  `description.word:fix`, `project.isnt:film`), ID ranges (`1-5,8`),
  `/regex/`, `limit:N`, UDA filters, abbreviations (`proj:`, `pri:`).
- **Dates**: `sod/eod`, `soq/eoq`, ordinals (`23rd`), epoch, signed
  offsets (`-2w`, `+90min`) and compounds (`eom-2d`, `now+3h`).
- **Lifecycle**: `undo`, `duplicate`, `purge`, `log`, `append`,
  `prepend`, `denotate`, `import`, `edit` ($EDITOR), `version` — all of
  the mutating verbs work single-target, by ID, or as bulk filter ops.
- **Config**: taskrc file + `task show` + `task config`, `alias.*`,
  `task context …`, color rules, `urgency.*` coefficients.
- **Recurrence** (opt-in): set `recurrence=on`, then
  `task add pay rent due:1st recur:monthly until:2027-01-01`.
