# CLI Reference

TaskPeasant ships a Python module entry point:

```bash
python3 -m taskpeasant [--file FILE] [command tokens…]
# short alias once installed via pip/pipx:
tp [--file FILE] [command tokens…]
```

**Default file:** `./tasks.yaml` or the `TASKPEASANT_FILE` environment variable.

```bash
export TASKPEASANT_FILE=~/tasks/work.yaml   # set once, use everywhere
```

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

Filters can be combined — all tokens are AND'd together.

| Token | Matches |
|---|---|
| `+tag` | task has this tag |
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
| bare word | description contains this word (case-insensitive) |

```bash
tp task +urgent due.before:+7d
tp task project:studio priority:H
tp task render                      # description contains "render"
tp task count due.none: status:pending
```

---

## Date syntax

All date fields accept the following values:

| Value | Resolves to |
|---|---|
| `today` | today at midnight UTC |
| `tomorrow` | tomorrow |
| `yesterday` | yesterday |
| `eow` | end of current week (Sunday) |
| `eom` | end of current month |
| `monday` … `friday` | next occurrence of that weekday |
| `+3d` | 3 days from today |
| `+2w` | 2 weeks from today |
| `+1m` | 1 month from today |
| `+1y` | 1 year from today |
| `YYYY-MM-DD` | literal ISO date |
| `YYYY-MM-DDTHH:MM:SSZ` | literal ISO datetime |

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TASKPEASANT_FILE` | `./tasks.yaml` | Default YAML file when `--file` is omitted |

---

## rc.* flags

Taskwarrior `rc.*` flags (e.g. `rc.gc=off`, `rc.confirmation=off`) are
silently stripped. This lets existing TW command strings work unchanged.
