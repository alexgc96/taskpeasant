"""
taskpeasant/report_engine.py
Taskwarrior-style report engine.

A report is defined entirely by config keys (see _taskrc.DEFAULTS for the
TW built-in set — next, list, ls, minimal, long, all, active, blocked,
blocking, unblocked, completed, newest, oldest, overdue, ready, recurring,
waiting):

    report.<name>.description
    report.<name>.columns      id,project,due.relative,description,urgency
    report.<name>.labels       ID,Project,Due,Description,Urg
    report.<name>.sort         urgency-,due+
    report.<name>.filter       status:pending -WAITING limit:page

Custom reports are just extra keys — set report.foo.* in the taskrc (or
send rc.report.foo.columns=... overrides) and `task foo` works.

Column format specs are a port of TW's src/columns/: <attr>[.<format>]
with formats like description.count, due.relative, entry.age, uuid.short,
depends.indicator, tags.count, status.short, project.parent, start.active.

Empty columns are dropped from the output, exactly like Taskwarrior.
"""

from __future__ import annotations

import shlex
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from ._dates import parse_date
from ._taskrc import Taskrc
from .query import Filter, FilterError
from .storage import read_tasks, assign_ids
from .task_model import Task
from .urgency import apply_inherited_urgency

PAGE_SIZE = 25     # rows shown for limit:page in a non-tty context


# ── Duration / date formatting (port of TW's formatSeconds) ─────────────────

def format_duration_compact(seconds: float) -> str:
    """TW-style compact duration: 30s, 5min, 3h, 2d, 3w, 5mo, 1.2y."""
    s = abs(seconds)
    sign = "-" if seconds < 0 else ""
    if s < 60:
        return f"{sign}{int(s)}s"
    if s < 3600:
        return f"{sign}{int(s / 60)}min"
    if s < 86400:
        return f"{sign}{int(s / 3600)}h"
    if s < 86400 * 14:
        return f"{sign}{int(s / 86400)}d"
    if s < 86400 * 90:
        return f"{sign}{int(s / (86400 * 7))}w"
    if s < 86400 * 365:
        return f"{sign}{int(s / (86400 * 30))}mo"
    years = s / (86400 * 365)
    return f"{sign}{years:.1f}y"


def _fmt_date(value: str) -> str:
    """Report date rendering — ISO date, with time when present."""
    if not value:
        return ""
    if len(value) > 10 and not value.endswith("T00:00:00Z"):
        dt = parse_date(value)
        if dt:
            return dt.strftime("%Y-%m-%d %H:%M")
    return value[:10]


def _age(value: str, now: datetime) -> str:
    dt = parse_date(value) if value else None
    if not dt:
        return ""
    return format_duration_compact((now - dt).total_seconds())


def _countdown(value: str, now: datetime) -> str:
    dt = parse_date(value) if value else None
    if not dt:
        return ""
    return format_duration_compact((dt - now).total_seconds())


# ── Column formatters ─────────────────────────────────────────────────────────

class _Ctx:
    """Per-render context shared by the formatters."""
    __slots__ = ("now", "id_by_uuid")

    def __init__(self, now: datetime, id_by_uuid: Dict[str, int]):
        self.now = now
        self.id_by_uuid = id_by_uuid


def _combined_description(t: Task) -> str:
    lines = [t.description]
    for a in t.annotations:
        date = str(a.get("entry", ""))[:10]
        lines.append(f"  {date} {a.get('description', '')}")
    return "\n".join(lines)


def _depends_ids(t: Task, ctx: _Ctx) -> str:
    ids = [str(ctx.id_by_uuid.get(u, "")) or u[:8] for u in t.depends]
    return " ".join(ids)


def _status_short(status: str) -> str:
    return {"pending": "P", "completed": "C", "deleted": "D",
            "waiting": "W", "recurring": "R"}.get(status, "?")


def _priority_of(t: Task) -> str:
    return t.priority


def _recur_of(t: Task) -> str:
    return str(t.udas.get("recur", "") or "")


def _until_of(t: Task) -> str:
    return str(t.udas.get("until", "") or "")


# spec → callable(task, ctx) -> str
_FORMATTERS: Dict[str, Callable[[Task, _Ctx], str]] = {
    "id":          lambda t, c: str(t.id) if t.id else "-",
    "uuid":        lambda t, c: t.uuid,
    "uuid.short":  lambda t, c: t.uuid[:8],

    "description":           lambda t, c: _combined_description(t),
    "description.combined":  lambda t, c: _combined_description(t),
    "description.desc":      lambda t, c: t.description,
    "description.oneline":   lambda t, c: " / ".join(
        [t.description] + [a.get("description", "") for a in t.annotations]),
    "description.truncated": lambda t, c: (t.description[:37] + "..."
                                           if len(t.description) > 40
                                           else t.description),
    "description.count":     lambda t, c: (
        f"{t.description} [{len(t.annotations)}]" if t.annotations
        else t.description),

    "project":        lambda t, c: t.project,
    "project.full":   lambda t, c: t.project,
    "project.parent": lambda t, c: t.project.split(".")[0],
    "project.indented": lambda t, c: t.project,

    "priority":      lambda t, c: _priority_of(t),
    "priority.long": lambda t, c: {"H": "High", "M": "Medium",
                                   "L": "Low"}.get(t.priority, ""),

    "tags":           lambda t, c: " ".join(t.tags),
    "tags.list":      lambda t, c: " ".join(t.tags),
    "tags.count":     lambda t, c: f"[{len(t.tags)}]" if t.tags else "",
    "tags.indicator": lambda t, c: "+" if t.tags else "",

    "depends":           _depends_ids,
    "depends.list":      _depends_ids,
    "depends.count":     lambda t, c: (f"[{len(t.depends)}]"
                                       if t.depends else ""),
    "depends.indicator": lambda t, c: "D" if t.depends else "",

    "status":       lambda t, c: t.status.capitalize(),
    "status.short": lambda t, c: _status_short(t.status),

    "urgency":         lambda t, c: f"{t.urgency_value:.4g}",
    "urgency.real":    lambda t, c: f"{t.urgency_value:.4f}",
    "urgency.integer": lambda t, c: str(int(t.urgency_value)),

    "recur":           lambda t, c: _recur_of(t),
    "recur.duration":  lambda t, c: _recur_of(t),
    "recur.indicator": lambda t, c: "R" if _recur_of(t) else "",

    "start.active": lambda t, c: "*" if t.start else "",
}

_DATE_BASES = ("entry", "start", "end", "due", "scheduled", "wait",
               "until", "modified")


def _date_formatter(base: str, fmt: str) -> Optional[Callable]:
    def value_of(t: Task) -> str:
        if base == "until":
            return _until_of(t)
        return getattr(t, base, "") or ""

    if fmt in ("", "formatted"):
        return lambda t, c: _fmt_date(value_of(t))
    if fmt == "age":
        return lambda t, c: _age(value_of(t), c.now)
    if fmt in ("relative", "countdown", "remaining"):
        return lambda t, c: _countdown(value_of(t), c.now)
    if fmt == "julian":
        return lambda t, c: (str(parse_date(value_of(t)).toordinal() + 1721425)
                             if value_of(t) and parse_date(value_of(t))
                             else "")
    if fmt == "epoch":
        return lambda t, c: (str(int(parse_date(value_of(t)).timestamp()))
                             if value_of(t) and parse_date(value_of(t))
                             else "")
    if fmt == "iso":
        return lambda t, c: value_of(t)
    if fmt == "indicator":
        return lambda t, c: "*" if value_of(t) else ""
    if fmt == "active":
        return lambda t, c: "*" if value_of(t) else ""
    return None


def get_formatter(spec: str) -> Callable[[Task, _Ctx], str]:
    """Formatter for a column spec; unknown specs render the UDA/attr raw."""
    if spec in _FORMATTERS:
        return _FORMATTERS[spec]
    base, _, fmt = spec.partition(".")
    if base in _DATE_BASES:
        fn = _date_formatter(base, fmt)
        if fn is not None:
            return fn
    # UDA column (or unknown format on a known attr): raw string value
    def uda_fmt(t: Task, c: _Ctx, name=base) -> str:
        v = getattr(t, name, None)
        if v is None:
            v = t.udas.get(name, "")
        return str(v or "")
    return uda_fmt


def known_column_specs() -> List[str]:
    """All specs `task columns` should list."""
    specs = sorted(_FORMATTERS)
    for base in _DATE_BASES:
        specs.extend([base, f"{base}.age", f"{base}.relative",
                      f"{base}.countdown", f"{base}.remaining",
                      f"{base}.iso", f"{base}.epoch", f"{base}.julian",
                      f"{base}.indicator"])
    return sorted(set(specs))


# ── Sorting ───────────────────────────────────────────────────────────────────

_PRIORITY_RANK = {"H": 3, "M": 2, "L": 1, "": 0}


def parse_sort_spec(spec: str) -> List[Tuple[str, bool]]:
    """'urgency-,due+,project+/' → [(attr, ascending), ...].
    TW's `/` break markers are accepted and ignored."""
    keys = []
    for part in spec.split(","):
        part = part.strip().rstrip("/").rstrip("\\")
        if not part:
            continue
        if part.endswith("-"):
            keys.append((part[:-1], False))
        elif part.endswith("+"):
            keys.append((part[:-1], True))
        else:
            keys.append((part, True))
    return keys


def _sort_value(t: Task, attr: str):
    """(has_value, comparable) so tasks lacking the attr sort last."""
    if attr == "urgency":
        return (0, t.urgency_value)
    if attr == "id":
        return (0, t.id)
    if attr == "priority":
        return (0, _PRIORITY_RANK.get(t.priority, 0))
    if attr in _DATE_BASES:
        raw = _until_of(t) if attr == "until" else getattr(t, attr, "")
        dt = parse_date(raw) if raw else None
        if dt is None:
            return (1, 0.0)          # missing → after present values
        return (0, dt.timestamp())
    v = getattr(t, attr, None)
    if v is None:
        v = t.udas.get(attr, "")
    if isinstance(v, list):
        v = ",".join(str(x) for x in v)
    v = str(v or "").lower()
    return (1, "") if not v else (0, v)


class _Rev:
    """Inverts comparison so a descending key can ride an ascending sort
    (keeps tasks with missing values last in BOTH directions, like TW)."""
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v

    def __lt__(self, other):
        return other.v < self.v

    def __eq__(self, other):
        return self.v == other.v


def sort_tasks(tasks: List[Task], spec: str) -> None:
    """Stable multi-key sort in place, least-significant key first."""
    for attr, ascending in reversed(parse_sort_spec(spec)):
        def key(t, a=attr, asc=ascending):
            missing, val = _sort_value(t, a)
            return (missing, val if asc else _Rev(val))
        tasks.sort(key=key)


# ── Report resolution / execution ─────────────────────────────────────────────

class ReportDef:
    __slots__ = ("name", "description", "columns", "labels", "sort", "filter")

    def __init__(self, name: str, conf: Taskrc):
        self.name = name
        self.description = conf.get(f"report.{name}.description", name)
        self.columns = [c for c in
                        conf.get(f"report.{name}.columns").split(",") if c]
        labels = [x for x in conf.get(f"report.{name}.labels").split(",") if x]
        # pad/truncate labels to columns
        while len(labels) < len(self.columns):
            labels.append(self.columns[len(labels)].split(".")[0].capitalize())
        self.labels = labels[:len(self.columns)]
        self.sort = conf.get(f"report.{name}.sort")
        self.filter = conf.get(f"report.{name}.filter")


def get_report(conf: Taskrc, name: str) -> Optional[ReportDef]:
    if not conf.get(f"report.{name}.columns"):
        return None
    return ReportDef(name, conf)


def _combine_filters(report_filter: str, user_tokens: List[str]) -> List[str]:
    """(report filter) AND (user filter) — parenthesised so `or` inside
    either side can't leak across, mirroring TW."""
    rep = shlex.split(report_filter) if report_filter else []
    usr = list(user_tokens or [])
    if rep and usr:
        return ["("] + rep + [")", "("] + usr + [")"]
    return rep or usr


def select_tasks(yaml_path: str, report: ReportDef,
                 filter_tokens: Optional[List[str]] = None,
                 conf: Optional[Taskrc] = None
                 ) -> Tuple[List[Task], List[Task], int]:
    """Read, filter, score, sort, and limit.

    Returns (visible_tasks, all_tasks, limit_applied) where limit_applied
    is the row cap (0 = unlimited).
    """
    conf = conf or Taskrc()
    all_tasks = read_tasks(yaml_path)
    assign_ids(yaml_path, all_tasks)
    apply_inherited_urgency(all_tasks, conf)

    f = Filter.parse(_combine_filters(report.filter, filter_tokens))
    matched = [t for t in all_tasks if f.matches(t)]

    if report.sort:
        sort_tasks(matched, report.sort)

    limit = 0
    if f.limit == "page":
        limit = PAGE_SIZE
    elif f.limit.isdigit():
        limit = int(f.limit)
    if limit:
        matched = matched[:limit]
    return matched, all_tasks, limit


def build_report(yaml_path: str, name: str,
                 filter_tokens: Optional[List[str]] = None,
                 conf: Optional[Taskrc] = None):
    """Full pipeline → (report, headers, rows, tasks) or None if the
    report doesn't exist.  Empty columns are dropped (TW behaviour)."""
    conf = conf or Taskrc()
    report = get_report(conf, name)
    if report is None:
        return None
    tasks, _all, _limit = select_tasks(yaml_path, report, filter_tokens, conf)

    ctx = _Ctx(datetime.now(timezone.utc),
               {t.uuid: t.id for t in _all if t.id})
    formatters = [get_formatter(spec) for spec in report.columns]
    rows = [[fmt(t, ctx) for fmt in formatters] for t in tasks]

    # Drop columns that are empty for every row
    keep = [i for i in range(len(report.columns))
            if any(row[i] for row in rows)]
    headers = [report.labels[i] for i in keep]
    rows = [[row[i] for i in keep] for row in rows]
    specs = [report.columns[i] for i in keep]
    return report, headers, rows, tasks, specs


# Numeric-ish columns get right-aligned in the plain renderer
_RIGHT_ALIGN_BASES = frozenset(["id", "urgency"])


def render_plain(headers: List[str], rows: List[List[str]],
                 specs: List[str], count: int) -> str:
    """Monospace table with TW-style dashed underlines; multiline cells
    (combined descriptions) continue under their own column."""
    if not rows:
        return "No matches."

    # Explode multiline cells
    grid: List[List[List[str]]] = [
        [cell.split("\n") for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in grid:
        for i, cell_lines in enumerate(row):
            for ln in cell_lines:
                widths[i] = max(widths[i], len(ln))

    right = [specs[i].partition(".")[0] in _RIGHT_ALIGN_BASES
             for i in range(len(specs))]

    def fmt_line(cells: List[str]) -> str:
        parts = []
        for i, text in enumerate(cells):
            parts.append(text.rjust(widths[i]) if right[i]
                         else text.ljust(widths[i]))
        return " ".join(parts).rstrip()

    lines = [fmt_line(headers),
             " ".join("-" * w for w in widths)]
    for row in grid:
        height = max(len(c) for c in row)
        for ln in range(height):
            lines.append(fmt_line([c[ln] if ln < len(c) else ""
                                   for c in row]))
    lines.append("")
    lines.append(f"{count} task{'s' if count != 1 else ''}")
    return "\n".join(lines)


def run_report(yaml_path: str, name: str,
               filter_tokens: Optional[List[str]] = None,
               conf: Optional[Taskrc] = None) -> str:
    """Execute a report and return the plain-text table."""
    try:
        built = build_report(yaml_path, name, filter_tokens, conf)
    except FilterError as e:
        return f"Error: {e}"
    if built is None:
        return f"Unknown report '{name}'"
    _report, headers, rows, tasks, specs = built
    return render_plain(headers, rows, specs, len(tasks))


def list_reports(conf: Taskrc) -> str:
    """`task reports` — every defined report with its description."""
    names = conf.report_names()
    width = max(len(n) for n in names)
    lines = [f"{'Report':<{width}}  Description", "-" * (width + 40)]
    for n in names:
        lines.append(f"{n:<{width}}  {conf.get(f'report.{n}.description')}")
    lines.append("")
    lines.append(f"{len(names)} reports")
    return "\n".join(lines)


def list_columns() -> str:
    """`task columns` — supported column format specs."""
    lines = ["Columns"]
    lines.append("-" * 24)
    lines.extend(known_column_specs())
    return "\n".join(lines)
