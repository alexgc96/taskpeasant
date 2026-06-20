# taskpeasant

> A YAML-native, pure-Python task backend. Drop-in Taskwarrior alternative for local-first apps and platforms where the Taskwarrior binary is unavailable (e.g. native Windows).

Built by [analogtrsh studio](https://github.com/alexgc96) as the native task backend for Studio OS on Windows, where Taskwarrior is awkward to install. Released as GPL-3.0-or-later so any other local-first project can embed it.

---

## Why

Taskwarrior is excellent — but it's a C++ binary, it carries a daemon-ish posture in some setups, and on Windows it lives behind WSL or a brittle MSYS2 build. If your app already speaks YAML and lives on the filesystem, you don't need any of that. TaskPeasant gives you:

- The TaskWarrior data model (UUID, status, tags, due, scheduled, depends, annotations, UDAs)
- A subset of the TaskWarrior CLI grammar (`task add`, `task <uuid> done`, `+tag`, `due:eom`, etc.)
- TaskWarrior-compatible JSON export so existing UIs need zero changes
- All persisted as plain YAML — diffable, git-friendly, no daemon, no DB

## Install

```bash
pip install taskpeasant
```

Or, while developing alongside a host app:

```bash
pip install -e ../taskpeasant
```

## Quickstart

```python
from taskpeasant import execute_command, read_tasks, cmd_add

yaml_path = "/path/to/your/tasks.yaml"

# Use the TW-style CLI parser:
print(execute_command("task add render the final shot +urgent due:tomorrow", yaml_path))
# → Created task 8c2f1a3b  'render the final shot'

print(execute_command("task", yaml_path))
# →    UUID    Urg  Description
#     --------  -----  ----------------
#     8c2f1a3b   14.0  render the final shot   +urgent  due:2026-06-20

# …or call the Python API directly:
cmd_add(yaml_path, "another task", tags=["render"], due="2026-06-25")
tasks = read_tasks(yaml_path)
```

## Storage

TaskPeasant reads and writes a single top-level key, `taskpeasant_tasks:`, inside any YAML file you point it at:

```yaml
taskpeasant_tasks:
  - uuid: 8c2f1a3b-...
    description: render the final shot
    status: pending
    entry: 2026-06-19T14:30:00Z
    tags: [urgent]
    due: 2026-06-20T00:00:00Z
```

It will never touch any other key, which means you can embed it inside a YAML file that already carries project metadata, config, or TaskWarrior context tags. See [`docs/storage.md`](docs/storage.md) (TODO) and [`docs/BACKWARDS_COMPAT.md`](docs/BACKWARDS_COMPAT.md) for the contract.

## Status

Alpha. The public API and storage contract are frozen (see `docs/BACKWARDS_COMPAT.md`). New features are landing as we close TaskWarrior parity gaps — see `docs/parity.md` (TODO) for the matrix.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
