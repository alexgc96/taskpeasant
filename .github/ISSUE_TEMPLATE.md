## Add Python tests for remaining Rich renderers

### Description
Currently, test coverage for the `_rich.py` module is limited to the calendar renderer (`render_calendar`). The module contains several other rendering functions that use the Rich library but lack test coverage:

- `render_report()` — Renders Rich Table for any report-engine result with per-cell styling
- `render_list()` — Rich Table for task list views (task, task next, task all)
- `render_info()` — Rich Panel for single task detail view
- `render_history()` — Table showing task history buckets by year/month
- `render_ghistory()` — Graphical history table with activity bars
- `render_burndown()` — Burndown chart with colored character art
- Utility functions: `confirm()`, `error()`, and color helper functions (`_urgency_color()`, `_due_color()`)

### Goals
Write comprehensive pytest tests for each of the above renderers to ensure:

1. **Correct Rich object types** — Verify that each renderer returns the correct Rich object type (Table, Panel, or Text)
2. **Styling and formatting** — Verify styling rules are applied correctly (colors, urgency-based styling, due-date styling, etc.)
3. **Content accuracy** — Verify that rendered content matches the input data (headers, rows, task properties, etc.)
4. **Edge cases** — Handle empty data, null values, boundary conditions (e.g., today is the 1st of month, no due dates, etc.)
5. **Configuration handling** — Ensure renderers respect configuration options where applicable (e.g., color settings)

### Implementation Notes
- Follow the pattern established in `tests/test_rich.py` (e.g., helper functions like `_spans_with_style()`, use of fixtures)
- Each renderer section should be grouped with a comment banner matching `_rich.py`'s own structure: `# ── Section ──────────────`
- Use existing test fixtures from `conftest.py` (e.g., `make_task`, `iso`, `now_utc`)
- Consider parameterized tests where appropriate to reduce duplication
