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
```

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

### `assign_ids(yaml_path: str, tasks: list[Task]) → None`

Assign ephemeral integer IDs to `pending`/`waiting` tasks in-place, sorted
by urgency descending. Results are mtime-cached — repeated calls within the
same file state are free. Completed/deleted tasks get `id = 0`.

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
| `tags_add` | list | Add tags |
| `tags_remove` | list | Remove tags |
| `depends` | list | Replace depends list |
| _(any other key)_ | any | Stored as UDA |

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
) → list[dict]
```

Returns TW-wire-format dicts, ready for `json.dumps`. Includes `id`,
`urgency`, `is_active`. Pass `filter_tokens` to restrict results.

```python
data = tp.cmd_export("project.yaml", filter_tokens=["status:pending"])
data.sort(key=lambda t: -t["urgency"])
```

---

## Scoring

### `compute_urgency(task: Task) → float`

Returns an urgency score in the ~0–20 range, compatible with Taskwarrior's
urgency display. Returns `0.0` for non-pending tasks.

```python
tasks = tp.read_tasks("project.yaml")
for t in tasks:
    print(t.description, tp.compute_urgency(t))
```

The scoring factors and weights are exposed in `taskpeasant.urgency.WEIGHTS`
and can be tuned by the host application.

> **Roadmap (v0.3.0):** `compute_urgency` will gain a second parameter,
> `config: UrgencyConfig = DEFAULT_CONFIG`. Callers that omit it get identical
> behaviour. The `UrgencyConfig` dataclass will also accept a custom polynomial
> evaluator, enabling full Taskwarrior-style urgency as a drop-in.
> `WEIGHTS` will be deprecated in favour of `DEFAULT_CONFIG`.

---

## CLI parser

### `execute_command(raw: str, yaml_path: str) → str`

Parse a Taskwarrior-style CLI string and dispatch to the correct command.
Returns terminal output as a plain string. Never raises — all errors are
returned as strings.

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
print(taskpeasant.__version__)   # "0.2.0"
```
