# Changelog

All notable changes to TaskPeasant will be documented in this file.
The format is loosely [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Breaking-change policy**: anything listed in [`docs/BACKWARDS_COMPAT.md`](docs/BACKWARDS_COMPAT.md) cannot change without a MAJOR version bump.
> The entry is loud-tagged `**BREAKING**` here and explained in `docs/integration.md` with a migration note for embedders.

## [Unreleased]

### Added
- _(nothing yet — track new features here as they land)_

### Changed
- _(non-breaking changes only)_

### Fixed
- _(bug fixes)_

### Removed
- _(deprecations and removals)_

---

## [0.1.0] — 2026-06-19

Initial extraction from the [analogtrsh Studio OS](https://github.com/alexgc96/analogtrsh) monorepo into a standalone repository.

### Added
- Public API: `Task`, `read_tasks`, `write_tasks`, `cmd_add`, `cmd_done`, `cmd_delete`, `cmd_start`, `cmd_stop`, `cmd_annotate`, `cmd_modify`, `cmd_export`, `compute_urgency`, `execute_command`.
- TaskWarrior-compatible JSON export (`Task.to_tw_export()`).
- Subset of the TaskWarrior CLI grammar (`add`, `done`, `delete`, `start`, `stop`, `annotate`, `modify`, `+tag`, `-tag`, `due:`, `scheduled:`, `status:`, `+tag export`, `rc.*` silently stripped).
- Filter engine with `+tag`, `-tag`, `status:`, `uuid:`, `<field>.any:` / `.none:`, bare-word description search.
- Urgency model — additive, transparent, mirrors TW's weight ranges so existing UI urgency bars work unchanged.
- YAML storage under dedicated `taskpeasant_tasks:` key with per-file locking and legacy `tasks:`-as-list fallback.
- Date aliases: `today`, `tomorrow`, `yesterday`, `eow`, `eom`, weekday names.

[Unreleased]: https://github.com/alexgc96/taskpeasant/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/alexgc96/taskpeasant/releases/tag/v0.1.0
