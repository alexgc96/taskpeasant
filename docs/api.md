# Python API Reference

All symbols are importable directly from the `taskpeasant` package:

```python
import taskpeasant as tp
# or pick what you need:
from taskpeasant import Task, read_tasks, write_tasks, assign_ids, cmd_add, …
```

---

## Data model

### `Task`

```python
@dataclass
class Task:
    uuid:          str
    description:   str
    status:        str        = "pending"     # pending | completed | deleted | waiting
    entry:         str        = ""            # ISO 8601 UTC
    start:         str        = ""
    end:           str        = ""
    due:           str        = ""
    scheduled:     str        = ""
    wait:          str        = ""
    modified:      str        = ""
    tags:          list       = []
    depends:       list       = []            # list of UUID strings
    annotations:   list       = []            # [{entry, description}, …]
    project:       str        = ""
    priority:      str        = ""            # "H" | "M" | "L"
    udas:          dict       = {}            # unknown keys preserved on round-trip

    # Runtime only — never persisted
    urgency_value: float      = 0.0
    id:            int        = 0             # ephemeral integer ID
    virtual_tags:  set        = set()         # +OVERDUE, +BLOCKED, … (see _vtags)
```

`virtual_tags` is populated by `assign_ids()` (or
`taskpeasant._vtags.annotate_virtual_tags(tasks)` directly) and consumed by
filters (`+OVERDUE`), urgency graph factors, and info views. It never
appears in `to_dict()` / `to_tw_export()` output.

#### `Task.to_dict() → dict`

Returns a YAML-safe dict. Dates are ISO strings. UDAs are merged at the top
level. Used internally by `write_tasks()`.

#### `Task.to_tw_export() → dict`

Returns a Taskwarrior wire-format dict (dates as `YYYYMMDDTHHMMSSz`,
`depends` as comma-string, `is_active` bool, `id` field included). Used
by `cmd_export()` and the Studio OS JSON API.

#### `Task.from_dict(raw: dict) → Task`

Hydrate a Task from a YAML dict. Unknown keys → `udas`. Never drops data.

---

## Storage

### `read_tasks(yaml_path: str) → list[Task]`

Read all tasks from a YAML file. Reads from `taskpeasant_tasks:` key;
falls back to legacy `tasks:` list. Auto-transitions any `waiting` tasks
whose `wait` date has passed to `pending` (writes back immediately if any
transition occurred). Returns `[]` on missing file — never raises.

```python
tasks = tp.read_tasks("project.yaml")
pending = [t for t in tasks if t.status == "pending"]
```

### `write_tasks(yaml_path: str, tasks: list[Task]) → None`

Write task list to `taskpeasant_tasks:` in the YAML file. All other keys
in the file are preserved exactly. Thread-safe via per-file `RLock`.

```python
tasks = tp.read_tasks("project.yaml")
tasks[0].description = "updated"
tp.write_tasks("project.yaml", tasks)
```

### `assign_ids(yaml_path: str, tasks: list[Task], config=None) → None`

Assign ephemeral integer IDs to `pending`/`waiting` tasks in-place, sorted
by urgency descending. Results are mtime-cached — repeated calls within the
same file state are free. Completed/deleted tasks get `id = 0`. Also
annotates `virtual_tags` on every task. `config` is an optional
`UrgencyConfig` forwarded to `compute_urgency` (the ID cache is keyed per
config).

```python
tasks = tp.read_tasks("project.yaml")
tp.assign_ids("project.yaml", tasks)
for t in tasks:
    print(t.id, t.description)
```

---

## Commands

All command functions return a human-readable string (mirrors Taskwarrior's
stdout). They read → mutate → write atomically under the per-file lock.
Task lookup accepts any UUID prefix (4+ hex characters).

### `cmd_add`

```python
cmd_add(
    yaml_path:   str,
    description: str,
    tags:        list = None,
    due:         str  = "",
    scheduled:   str  = "",
    wait:        str  = "",
    project:     str  = "",
    priority:    str  = "",   # "H" | "M" | "L"
) → str
```

Creates a new pending task (or `waiting` if `wait` is set).

```python
tp.cmd_add("project.yaml", "render the shot",
           tags=["urgent"], due="2026-06-25", priority="H", project="studio")
```

### `cmd_done(yaml_path, uuid_prefix) → str`

Mark a task completed. Sets `end`, clears `start`.

### `cmd_delete(yaml_path, uuid_prefix) → str`

Mark a task deleted. Sets `end`.

### `cmd_start(yaml_path, uuid_prefix) → str`

Set `start` to now (task becomes active).

### `cmd_stop(yaml_path, uuid_prefix) → str`

Clear `start`.

### `cmd_annotate(yaml_path, uuid_prefix, note: str) → str`

Append an annotation to the task.

```python
tp.cmd_annotate("project.yaml", "8c2f1a3b", "blocked on design review")
```

### `cmd_modify`

```python
cmd_modify(
    yaml_path:   str,
    uuid_prefix: str,
    mods:        dict,
) → str
```

Update fields on a task. `mods` may contain:

| Key | Type | Effect |
|---|---|---|
| `description` | str | Replace description |
| `due` | str | Set due date |
| `scheduled` | str | Set scheduled date |
| `wait` | str | Set wait date (also sets `status: waiting`) |
| `status` | str | Set status directly |
| `project` | str | Set project |
| `priority` | str | Set priority (`H`/`M`/`L`) |
| `tags_add` | list | Add tags (virtual tag names are rejected) |
| `tags_remove` | list | Remove tags |
| `depends` | list \| str | List → replace verbatim. String → resolved spec: `"2,8c2f"` adds (IDs/prefixes → full UUIDs), `"-3"` removes, `""` clears; self-deps and cycles rejected |
| _(any other key)_ | any | Stored as UDA (empty string value deletes the UDA) |

Empty string values clear fields (`due`/`scheduled`/`wait`/`project`/
`priority`); clearing `wait` releases a `waiting` task back to `pending`.

```python
tp.cmd_modify("project.yaml", "8c2f1a3b", {
    "priority": "H",
    "tags_add": ["urgent"],
    "due": "2026-06-25",
})
```

### `cmd_export`

```python
cmd_export(
    yaml_path:     str,
    filter_tokens: list = None,
    config:        UrgencyConfig = None,
) → list[dict]
```

Returns TW-wire-format dicts, ready for `json.dumps`. Includes `id`,
`urgency`, `is_active`. Pass `filter_tokens` to restrict results (full
boolean expression syntax supported) and `config` to score with a custom
`UrgencyConfig`.

```python
data = tp.cmd_export("project.yaml", filter_tokens=["status:pending"])
data.sort(key=lambda t: -t["urgency"])
```

### `cmd_bulk`

```python
cmd_bulk(
    yaml_path:     str,
    filter_tokens: list,
    verb:          str,          # done|delete|start|stop|modify|annotate
    mods:          dict = None,  # for verb="modify"
    note:          str  = "",    # for verb="annotate"
) → str
```

Apply a mutation verb to every task matching a filter expression. One
read, one write. Inapplicable tasks are skipped and counted; unusable
filter tokens or mod errors abort before anything is written.

```python
tp.cmd_bulk("project.yaml", ["+OVERDUE"], "done")
tp.cmd_bulk("project.yaml", ["project:film"], "modify", mods={"priority": "H"})
```

---

## Scoring

### `compute_urgency(task: Task, config: UrgencyConfig = None) → float`

Returns an urgency score in the ~0–20 range, compatible with Taskwarrior's
urgency display. Returns `0.0` for non-pending tasks.

```python
tasks = tp.read_tasks("project.yaml")
for t in tasks:
    print(t.description, tp.compute_urgency(t))
```

### `UrgencyConfig` / `DEFAULT_CONFIG`

Frozen dataclass holding every urgency coefficient:

```python
from taskpeasant import UrgencyConfig, compute_urgency

cfg = UrgencyConfig(blocking=3.0, priority={"H": 8.0, "M": 4.0, "L": 2.0})
score = compute_urgency(task, cfg)
```

Fields: `active`, `overdue`, `due_today`, `due_soon`, `scheduled`,
`priority` (dict), `tag_urgent`, `tag_next`, `annotations`,
`annotations_cap`, `age_per_day`, `age_cap`, `blocked`, `blocking`.
`UrgencyConfig.from_weights(d)` builds one from a `WEIGHTS`-style dict.

The `blocked` penalty and `blocking` bonus are graph-aware when tasks have
been annotated with virtual tags (via `assign_ids`); on bare, un-annotated
tasks, `blocked` falls back to a `depends`-presence check and no blocking
bonus applies.

**Legacy knob:** when `config` is omitted, the config is rebuilt from the
live `taskpeasant.urgency.WEIGHTS` dict on every call, so existing hosts
that tune by mutating `WEIGHTS` keep working unchanged. `WEIGHTS` is
deprecated in favour of passing an `UrgencyConfig` explicitly.

> The design note in earlier docs sketched `config: UrgencyConfig =
> DEFAULT_CONFIG`; the shipped default is `None` precisely so that live
> `WEIGHTS` mutations stay honoured. A custom polynomial evaluator hook
> remains future work.

---

## CLI parser

### `execute_command(raw: str, yaml_path: str) → str`

Parse a Taskwarrior-style CLI string and dispatch to the correct command.
Returns terminal output as a plain string. Never raises — all errors are
returned as strings. Supports boolean filter expressions, virtual tags,
and bulk operations (`task +urgent done`); see [docs/cli.md](cli.md).

### `apply_filter(tasks, tokens, *, all_tasks=None) → list[Task]`

(from `taskpeasant.query`) Filter a task list by TW-style tokens,
including boolean expressions. Annotates virtual tags first; pass the
full list as `all_tasks` when `tasks` is a pre-narrowed subset so
`+BLOCKED`/`+BLOCKING` see the whole dependency graph. Raises
`taskpeasant.query.FilterError` on malformed expressions.

```python
output = tp.execute_command("task add render the shot +urgent due:tomorrow", yaml_path)
print(output)
# → Created task 8c2f1a3b  'render the shot'

output = tp.execute_command("task", yaml_path)
print(output)
# →  ID      UUID    Urg  Description
#    …

output = tp.execute_command("task 1 done", yaml_path)
```

---

## Version

```python
import taskpeasant
print(taskpeasant.__version__)   # "0.3.0"
```
