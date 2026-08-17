# taskpeasant

> **Taskwarrior logic, ported to Python — as close as we could get.**
> A YAML-native, pure-Python task engine for local-first apps and platforms where the Taskwarrior binary is unavailable (e.g. native Windows).

Built by [analogtrsh studio](https://github.com/alexgc96) as the native task backend for Studio OS on Windows, where Taskwarrior is awkward to install. Released as GPL-3.0-or-later — the same license as [Taskwarrior](https://github.com/GothenburgBitFactory/taskwarrior), whose open-source code is the reference for TaskPeasant's behaviour, defaults, and output shape.

---

## Why

Taskwarrior is excellent — but it's a C++ binary, and on Windows it lives behind WSL or a brittle MSYS2 build. If your app already speaks YAML and lives on the filesystem, you don't need any of that. TaskPeasant re-implements the Taskwarrior model in pure Python:

- **The data model** — UUID, status, tags, due/scheduled/wait/until, depends, annotations, projects, priorities, UDAs, recurrence (opt-in)
- **The CLI grammar** — `task add`, `task 3 done`, `task +work list`, `due:eom`, attribute modifiers (`due.before:eow`, `description.word:fix`), boolean filter expressions, ID ranges, `/regex/`
- **The report engine** — every TW built-in report (`next`, `list`, `ls`, `long`, `all`, `ready`, `overdue`, `waiting`, `blocked`, …) plus custom reports defined in config, with TW's column formats and sort specs
- **The graphical reports** — `burndown.daily/weekly/monthly`, `history`/`ghistory` (daily→annual), `calendar`, `summary`, `stats`, `timesheet`
- **The urgency polynomial** — Taskwarrior's real formula with configurable `urgency.*` coefficients
- **The config system** — taskrc files, `rc.key=value` overrides, color rules, aliases, contexts, UDAs
- **The lifecycle** — `undo`, `duplicate`, `purge`, `log`, `append`/`prepend`, `denotate`, `import`/`export` (TW wire JSON), `task edit`
- All persisted as plain YAML — diffable, git-friendly, no daemon, no DB

See [`docs/parity.md`](docs/parity.md) for the full feature matrix against Taskwarrior, including the honest list of gaps (`sync` is intentionally out — TaskPeasant is local-first).

## Install

```bash
pip install taskpeasant
```

Or, while developing alongside a host app:

```bash
pip install -e ../taskpeasant
```

The CLI installs as `tp` (and `taskpeasant`). If TaskPeasant is the only task tool on the machine, `alias task=tp` completes the illusion — we deliberately don't claim the `task` name so a real Taskwarrior install can coexist.

## Quickstart — CLI

```bash
export TASKPEASANT_FILE=~/tasks/work.yaml

tp task add Write the pitch deck +work project:studio due:tomorrow priority:H
tp task add Fix boiler +home due:-2d
tp task 2 start
tp task next                     # TW's urgency-ranked report
tp task +home list               # filters compose with any report
tp task due.before:eow ready     # attribute modifiers, TW date synonyms
tp task 1 done
tp task undo                     # take that back
tp task burndown.weekly          # graphical reports
tp task summary
tp task rc.report.mine.columns=id,project,description.desc mine   # custom report
```

## Quickstart — embedded

```python
from taskpeasant import execute_command, read_tasks, cmd_add, Taskrc

yaml_path = "/path/to/your/tasks.yaml"

# The TW-style CLI parser returns plain text for your terminal widget:
print(execute_command("task add render the final shot +urgent due:tomorrow", yaml_path))
print(execute_command("task next", yaml_path))
print(execute_command("task +urgent export", yaml_path))    # TW wire JSON

# Optional: hand it a config with custom reports / urgency / colors
conf = Taskrc({"report.kanban.columns": "id,project,description.desc",
               "report.kanban.filter": "+ACTIVE"})
print(execute_command("task kanban", yaml_path, config=conf))

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

It will never touch any other key, which means you can embed it inside a YAML file that already carries project metadata, config, or Taskwarrior context tags. The undo journal lives in a sidecar file (`<file>.undo`) for the same reason. See [`docs/storage.md`](docs/storage.md) and [`docs/BACKWARDS_COMPAT.md`](docs/BACKWARDS_COMPAT.md) for the contract.

## Configuration

TaskPeasant reads a Taskwarrior-style `taskrc` (from `$TASKPEASANT_TASKRC`, `$TASKRC`, `~/.taskpeasantrc`, or `$XDG_CONFIG_HOME/taskpeasant/taskrc`):

```ini
default.command=next
urgency.user.tag.next.coefficient=15.0
report.kanban.columns=id,project,description.desc
color.overdue=bold red
alias.rm=delete
context.work=+work
recurrence=on          # opt-in; read BACKWARDS_COMPAT.md first if embedding
```

Everything can also be passed per-invocation as `rc.key=value`, exactly like Taskwarrior. `task show` prints the effective config.

## Status

Beta. The public API and storage contract are frozen (see `docs/BACKWARDS_COMPAT.md`) and guarded by a test suite. Feature coverage against Taskwarrior is tracked in [`docs/parity.md`](docs/parity.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
