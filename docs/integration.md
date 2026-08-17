# Integrating TaskPeasant into a Host Application

This guide is for anyone embedding TaskPeasant inside another app — most concretely, the [analogtrsh Studio OS](https://github.com/alexgc96/analogtrsh) Flask app, which is the reference embedder.

If you're touching TaskPeasant code and need to know how a change will land in the host, read this. If you just want to use the Python API, see the [README](../README.md).

---

## The reference embedder: analogtrsh Studio OS

Studio OS uses TaskPeasant as one of two interchangeable task backends, selected via `cfg.TW_BACKEND`:

- `cfg.TW_BACKEND == "taskwarrior"` → shells out to the real `task` binary
- `cfg.TW_BACKEND == "taskpeasant"` → imports and calls into this package
- `cfg.TW_BACKEND == "disabled"`    → no task UI

The two backends are interchangeable because TaskPeasant emits TaskWarrior-compatible JSON (`Task.to_tw_export()`) and accepts TaskWarrior-compatible CLI syntax (`execute_command()`). The same UI JavaScript renders both.

### Integration touchpoints in Studio OS (as of 0.1.0)

| Studio OS file        | What it calls into TaskPeasant for                       |
| --------------------- | -------------------------------------------------------- |
| `app/app.py`          | `import taskpeasant` — availability flag at startup      |
| `app/routes/tasks.py` | All CRUD ops via `commands.cmd_*` + `execute_command`    |
| `app/routes/calendar.py` | `storage.read_tasks` + `task_model._iso_to_tw`        |
| `app/routes/files.py` | `commands.*` + `compute_urgency` for file-delivery flow  |
| `app/routes/assets.py`| Backend-routing checks (`if cfg.TW_BACKEND == "taskpeasant"`) |
| `app/ics_generator.py`| `storage.read_tasks` for ICS calendar export             |
| `app/create_project.py` | Future call site (currently a placeholder)             |

Every one of those call sites is guarded by:

```python
if cfg.TW_BACKEND == "taskpeasant":
    try:
        import taskpeasant  # noqa
        # ... use it
    except ImportError:
        return jsonify({"error": "taskpeasant package not installed"}), 503
```

So Studio OS degrades gracefully if TaskPeasant isn't installed.

---

## How to land a TaskPeasant change in Studio OS

### For a NON-breaking change (added function, new CLI verb, new UDA pass-through)

1. Make the change here, bump the **PATCH** or **MINOR** version in `pyproject.toml` and `__init__.py`.
2. Add an entry to `CHANGELOG.md` under `[Unreleased] → Added/Changed/Fixed`.
3. In Studio OS, bump the pin (`pip install -U taskpeasant`) if needed, or do nothing — existing code keeps working.
4. If Studio OS wants to *use* the new feature, that's a separate Studio OS commit. Don't entangle them.

### For a BREAKING change (removing/renaming a public symbol, changing a signature, renaming the storage key, etc.)

1. **Stop.** Re-read [`BACKWARDS_COMPAT.md`](BACKWARDS_COMPAT.md) and ask whether you really need this. Can you add a new symbol instead?
2. If you really do need it:
   - Bump **MAJOR** in `pyproject.toml` and `__init__.py`.
   - Add a loud `**BREAKING**` entry to `CHANGELOG.md` with a *Migration* sub-section.
   - In this file, add a section under "Migration notes" below describing what every embedder needs to change.
3. In Studio OS, pin the OLD version until you've prepared the migration commit. Then in a single Studio OS commit: bump the pin AND update the call sites.

### For a bug fix that changes observable behaviour

Treat as a breaking change if the old behaviour might have been depended on. Otherwise PATCH bump + CHANGELOG entry. When in doubt, document in this file.

---

## Migration notes by version

### → 0.1.0 (initial extraction)

No migration. This is the baseline. Studio OS was previously importing from `app.taskpeasant`; after this extraction it imports from the installed `taskpeasant` package. Both paths are valid during the transition — see `app/routes/tasks.py:54` for the import pattern.

---

## Embedding checklist (for non–Studio-OS hosts)

If you're adding TaskPeasant to a fresh app, the minimum integration is:

1. `pip install taskpeasant`
2. Decide on a YAML file (one per project, or one global file — TaskPeasant doesn't care).
3. Wire your UI to call `execute_command(user_input, yaml_path)` and display the returned string.
4. For machine-readable data (e.g. drawing a Kanban board), call `cmd_export(yaml_path, filter_tokens)` and consume the TW-wire-format dicts directly.
5. Guard imports with `try/except ImportError` if TaskPeasant is optional.
6. Pin to a MINOR-compatible range in your manifest: `taskpeasant>=0.1,<0.2`.

That's it. No daemon, no config file, no init step.
