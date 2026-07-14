"""
taskpeasant/_taskrc.py
Taskwarrior-style configuration.

Mirrors TW's Config class: every setting is a flat string key=value pair,
layered   built-in defaults  ←  taskrc file  ←  rc.key=value overrides.

The library path (execute_command) never reads files from disk on its own —
hosts pass rc.* override tokens (or a Taskrc instance via the optional
`config` kwarg).  The CLI entry point loads the taskrc file at startup:

  1. $TASKPEASANT_TASKRC or $TASKRC     (explicit path)
  2. ~/.taskpeasantrc                   (if taskrc format — a YAML-mapping
                                         file keeps the legacy _config.py
                                         behaviour instead)
  3. $XDG_CONFIG_HOME/taskpeasant/taskrc

File format is Taskwarrior's:

    # comment
    key=value
    include /path/to/other/file

The DEFAULTS table below carries the honored subset of TW's own rc
defaults (report definitions, urgency coefficients, color rules, …) so
`task show` and the report engine behave like a stock Taskwarrior.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Built-in defaults (ported from Taskwarrior src/Context.cpp) ──────────────

DEFAULTS: Dict[str, str] = {
    # Behaviour
    "confirmation": "1",
    "recurrence":   "0",     # TW default is on; TP is opt-in (compat contract)
    "due":          "7",     # days horizon for the +DUE virtual tag
    "dateformat":   "Y-M-D",
    "defaultwidth": "80",
    "list.all.projects": "0",
    "list.all.tags":     "0",
    "color":        "1",
    "undo.limit":   "100",   # journal entries kept in the sidecar undo file

    # Urgency coefficients (TW defaults)
    "urgency.user.tag.next.coefficient": "15.0",
    "urgency.due.coefficient":           "12.0",
    "urgency.blocking.coefficient":      "8.0",
    "urgency.uda.priority.H.coefficient": "6.0",
    "urgency.uda.priority.M.coefficient": "3.9",
    "urgency.uda.priority.L.coefficient": "1.8",
    "urgency.scheduled.coefficient":     "5.0",
    "urgency.active.coefficient":        "4.0",
    "urgency.age.coefficient":           "2.0",
    "urgency.annotations.coefficient":   "1.0",
    "urgency.tags.coefficient":          "1.0",
    "urgency.project.coefficient":       "1.0",
    "urgency.waiting.coefficient":       "-3.0",
    "urgency.blocked.coefficient":       "-5.0",
    "urgency.age.max":                   "365",
    "urgency.inherit":                   "0",

    # Color rules (TW default theme) — consumed by _colors.py
    "rule.precedence.color": "deleted,completed,active,keyword.,tag.,project.,"
                             "overdue,scheduled,due.today,due,blocked,blocking,"
                             "recurring,tagged,uda.",
    "color.active":         "black on bright_green",
    "color.blocked":        "black on white",
    "color.blocking":       "black on bright_white",
    "color.overdue":        "bold red",
    "color.due.today":      "red",
    "color.due":            "yellow",
    "color.scheduled":      "",
    "color.recurring":      "",
    "color.tagged":         "",
    "color.completed":      "",
    "color.deleted":        "",
    "color.burndown.done":    "white on green",
    "color.burndown.pending": "white on red",
    "color.burndown.started": "black on yellow",
    "color.calendar.today":   "bold white on blue",
    "color.calendar.due":     "black on yellow",
    "color.calendar.due.today": "black on bright_yellow",
    "color.calendar.overdue": "white on red",
    "color.calendar.weekend": "bright_black",
    "color.history.add":      "green",
    "color.history.done":     "blue",
    "color.history.delete":   "red",
    "color.summary.bar":      "white on green",
    "color.summary.background": "white on bright_black",

    # Calendar
    "calendar.details":        "sparse",   # none | sparse | full
    "calendar.details.report": "list",
    "calendar.holidays":       "none",
    "weekstart":               "sunday",

    # ── Report definitions (TW built-ins) ────────────────────────────────────
    "report.next.description": "Most urgent tasks",
    "report.next.columns": "id,start.age,entry.age,depends,priority,project,"
                           "tags,recur,scheduled.countdown,due.relative,"
                           "until.remaining,description,urgency",
    "report.next.labels":  "ID,Active,Age,Deps,P,Project,Tag,Recur,S,Due,"
                           "Until,Description,Urg",
    "report.next.sort":    "urgency-",
    "report.next.filter":  "status:pending -WAITING limit:page",

    "report.list.description": "Most details of tasks",
    "report.list.columns": "id,start.age,entry.age,depends.indicator,priority,"
                           "project,tags,recur.indicator,wait.remaining,"
                           "scheduled.countdown,due,until.remaining,"
                           "description.count,urgency",
    "report.list.labels":  "ID,Active,Age,D,P,Project,Tags,R,Wait,Sch,Due,"
                           "Until,Description,Urg",
    "report.list.sort":    "start-,due+,project+,urgency-",
    "report.list.filter":  "status:pending -WAITING",

    "report.ls.description": "Few details of tasks",
    "report.ls.columns": "id,start.active,depends.indicator,project,tags,"
                         "recur.indicator,wait.remaining,scheduled.countdown,"
                         "due.countdown,until.countdown,description.count",
    "report.ls.labels":  "ID,A,D,Project,Tags,R,Wait,S,Due,Until,Description",
    "report.ls.sort":    "start-,description+",
    "report.ls.filter":  "status:pending -WAITING",

    "report.minimal.description": "Minimal details of tasks",
    "report.minimal.columns": "id,project,tags.count,description.count",
    "report.minimal.labels":  "ID,Project,Tags,Description",
    "report.minimal.sort":    "project+,description+",
    "report.minimal.filter":  "status:pending or status:waiting",

    "report.long.description": "All details of tasks",
    "report.long.columns": "id,start.active,entry,modified.age,depends,"
                           "priority,project,tags,recur,wait.remaining,"
                           "scheduled,due,until,description",
    "report.long.labels":  "ID,A,Created,Mod,Deps,P,Project,Tags,Recur,Wait,"
                           "Sched,Due,Until,Description",
    "report.long.sort":    "modified-",
    "report.long.filter":  "status:pending -WAITING",

    "report.all.description": "All tasks",
    "report.all.columns": "id,status.short,uuid.short,start.active,entry.age,"
                          "end.age,depends.indicator,priority,project.parent,"
                          "tags.count,recur.indicator,wait.remaining,"
                          "scheduled.countdown,due,until.remaining,description",
    "report.all.labels":  "ID,St,UUID,A,Age,Done,D,P,Project,Tags,R,Wait,Sch,"
                          "Due,Until,Description",
    "report.all.sort":    "entry-",
    "report.all.filter":  "",

    "report.active.description": "Active tasks",
    "report.active.columns": "id,start,start.age,entry.age,depends,priority,"
                             "project,tags,recur,wait,scheduled.remaining,due,"
                             "until,description",
    "report.active.labels":  "ID,Started,Active,Age,Deps,P,Project,Tags,Recur,"
                             "W,Sch,Due,Until,Description",
    "report.active.sort":    "project+,start+",
    "report.active.filter":  "status:pending and +ACTIVE",

    "report.blocked.description": "Blocked tasks",
    "report.blocked.columns": "id,depends,project,priority,due,start.active,"
                              "entry.age,description",
    "report.blocked.labels":  "ID,Deps,Project,P,Due,A,Age,Description",
    "report.blocked.sort":    "due+,priority-,start-",
    "report.blocked.filter":  "status:pending +BLOCKED",

    "report.blocking.description": "Blocking tasks",
    "report.blocking.columns": "id,uuid.short,start.active,depends,project,"
                               "tags,recur,wait,scheduled.remaining,"
                               "due.relative,until.remaining,"
                               "description.count,urgency",
    "report.blocking.labels":  "ID,UUID,A,Deps,Project,Tags,R,W,Sch,Due,Until,"
                               "Description,Urg",
    "report.blocking.sort":    "urgency-,due+,entry+",
    "report.blocking.filter":  "status:pending +BLOCKING",

    "report.unblocked.description": "Unblocked tasks",
    "report.unblocked.columns": "id,depends,project,priority,due,start.active,"
                                "entry.age,description",
    "report.unblocked.labels":  "ID,Deps,Project,P,Due,A,Age,Description",
    "report.unblocked.sort":    "due+,priority-,start-",
    "report.unblocked.filter":  "status:pending -BLOCKED",

    "report.completed.description": "Completed tasks",
    "report.completed.columns": "id,uuid.short,entry,end,entry.age,depends,"
                                "priority,project,tags,recur.indicator,due,"
                                "description",
    "report.completed.labels":  "ID,UUID,Created,Completed,Age,Deps,P,Project,"
                                "Tags,R,Due,Description",
    "report.completed.sort":    "end+",
    "report.completed.filter":  "status:completed",

    "report.newest.description": "Newest tasks",
    "report.newest.columns": "id,start.age,entry,entry.age,modified.age,"
                             "depends.indicator,priority,project,tags,"
                             "recur.indicator,wait.remaining,"
                             "scheduled.countdown,due,until.remaining,"
                             "description",
    "report.newest.labels":  "ID,Active,Created,Age,Mod,D,P,Project,Tags,R,"
                             "Wait,Sch,Due,Until,Description",
    "report.newest.sort":    "entry-",
    "report.newest.filter":  "status:pending or status:waiting",

    "report.oldest.description": "Oldest tasks",
    "report.oldest.columns": "id,start.age,entry,entry.age,modified.age,"
                             "depends.indicator,priority,project,tags,"
                             "recur.indicator,wait.remaining,"
                             "scheduled.countdown,due,until.remaining,"
                             "description",
    "report.oldest.labels":  "ID,Active,Created,Age,Mod,D,P,Project,Tags,R,"
                             "Wait,Sch,Due,Until,Description",
    "report.oldest.sort":    "entry+",
    "report.oldest.filter":  "status:pending or status:waiting",

    "report.overdue.description": "Overdue tasks",
    "report.overdue.columns": "id,start.age,entry.age,depends,priority,"
                              "project,tags,recur.indicator,"
                              "scheduled.countdown,due,until.remaining,"
                              "description,urgency",
    "report.overdue.labels":  "ID,Active,Age,Deps,P,Project,Tag,R,S,Due,Until,"
                              "Description,Urg",
    "report.overdue.sort":    "urgency-,due+",
    "report.overdue.filter":  "status:pending and +OVERDUE",

    "report.ready.description": "Most urgent actionable tasks",
    "report.ready.columns": "id,start.age,entry.age,depends,priority,project,"
                            "tags,recur,scheduled.countdown,due.relative,"
                            "until.remaining,description,urgency",
    "report.ready.labels":  "ID,Active,Age,Deps,P,Project,Tag,Recur,S,Due,"
                            "Until,Description,Urg",
    "report.ready.sort":    "start-,urgency-",
    "report.ready.filter":  "+READY",

    "report.recurring.description": "Recurring Tasks",
    "report.recurring.columns": "id,start.age,entry.age,depends.indicator,"
                                "priority,project,tags,recur,"
                                "scheduled.countdown,due,until.remaining,"
                                "description,urgency",
    "report.recurring.labels":  "ID,Active,Age,D,P,Project,Tags,Recur,Sch,Due,"
                                "Until,Description,Urg",
    "report.recurring.sort":    "due+,urgency-,entry+",
    "report.recurring.filter":  "(status:pending or status:waiting) and "
                                "(+PARENT or +CHILD)",

    "report.waiting.description": "Waiting (hidden) tasks",
    "report.waiting.columns": "id,start.age,entry.age,depends.indicator,"
                              "priority,project,tags,recur.indicator,wait,"
                              "wait.remaining,scheduled.countdown,due,"
                              "until.remaining,description",
    "report.waiting.labels":  "ID,Active,Age,D,P,Project,Tags,R,Wait,Remaining,"
                              "Sch,Due,Until,Description",
    "report.waiting.sort":    "due+,wait+,entry+",
    "report.waiting.filter":  "+WAITING",
}


class Taskrc:
    """Layered flat config: DEFAULTS ← file values ← rc overrides.

    All values are strings, exactly like Taskwarrior.  Use the typed
    getters for coercion.  `source_path` records the loaded file (or "").
    """

    def __init__(self, values: Optional[Dict[str, str]] = None,
                 source_path: str = ""):
        self._values: Dict[str, str] = dict(DEFAULTS)
        if values:
            self._values.update(values)
        self.source_path = source_path

    # ── Access ───────────────────────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self._values.get(key)
        if v is None:
            return default
        return v.strip().lower() in ("1", "yes", "on", "true", "y")

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._values.get(key, "").strip())
        except (ValueError, AttributeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self._values.get(key, "").strip())
        except (ValueError, AttributeError):
            return default

    def has(self, key: str) -> bool:
        return key in self._values

    def set(self, key: str, value: str) -> None:
        self._values[str(key)] = str(value)

    def update(self, overrides: Dict[str, str]) -> None:
        for k, v in (overrides or {}).items():
            self.set(k, v)

    def subtree(self, prefix: str) -> Dict[str, str]:
        """All keys starting with prefix, prefix stripped from the result."""
        n = len(prefix)
        return {k[n:]: v for k, v in self._values.items()
                if k.startswith(prefix)}

    def keys(self) -> List[str]:
        return sorted(self._values)

    def items(self):
        return sorted(self._values.items())

    def is_default(self, key: str) -> bool:
        return key in DEFAULTS and self._values.get(key) == DEFAULTS[key]

    # ── Report helpers ───────────────────────────────────────────────────────

    def report_names(self) -> List[str]:
        names = set()
        for key in self._values:
            if key.startswith("report.") and key.count(".") >= 2:
                names.add(key.split(".")[1])
        return sorted(names)


# ── File parsing ──────────────────────────────────────────────────────────────

def parse_taskrc_text(text: str, base_dir: str = "",
                      _depth: int = 0) -> Dict[str, str]:
    """Parse taskrc-format text into a flat dict.  Handles `include`."""
    values: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("include ") or line.startswith("include\t"):
            if _depth >= 10:      # cycle guard
                continue
            inc = os.path.expanduser(line.split(None, 1)[1].strip())
            if base_dir and not os.path.isabs(inc):
                inc = os.path.join(base_dir, inc)
            try:
                sub = Path(inc).read_text(encoding="utf-8")
            except OSError:
                continue
            values.update(parse_taskrc_text(sub, os.path.dirname(inc),
                                            _depth + 1))
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


def looks_like_yaml_mapping(path: str) -> bool:
    """True when the file parses as a YAML mapping (legacy _config.py format).

    A taskrc line like `a=b` parses as a YAML *string*, so this cleanly
    separates the two formats.
    """
    import yaml
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(raw, dict)


def find_taskrc_path() -> Optional[str]:
    """First existing taskrc per the search order, or None."""
    for env in ("TASKPEASANT_TASKRC", "TASKRC"):
        explicit = os.environ.get(env, "")
        if explicit:
            return explicit if os.path.isfile(explicit) else None

    rc_path = os.path.join(os.path.expanduser("~"), ".taskpeasantrc")
    if os.path.isfile(rc_path) and not looks_like_yaml_mapping(rc_path):
        return rc_path

    xdg_home = os.environ.get("XDG_CONFIG_HOME", "") or \
        os.path.join(os.path.expanduser("~"), ".config")
    xdg_path = os.path.join(xdg_home, "taskpeasant", "taskrc")
    if os.path.isfile(xdg_path):
        return xdg_path

    return None


def load_taskrc(path: Optional[str] = None) -> Taskrc:
    """Load the taskrc file (or defaults when none exists).  Never raises."""
    path = path or find_taskrc_path()
    if not path:
        return Taskrc()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return Taskrc()
    return Taskrc(parse_taskrc_text(text, os.path.dirname(path)), path)


def default_taskrc_write_path() -> str:
    """Where `task config` writes when no taskrc exists yet."""
    xdg_home = os.environ.get("XDG_CONFIG_HOME", "") or \
        os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(xdg_home, "taskpeasant", "taskrc")


def write_taskrc_value(path: str, key: str, value: Optional[str]) -> str:
    """Set (or unset when value is None) a key in a taskrc file.

    Rewrites the matching line in place, appends when missing.  Returns a
    TW-style confirmation string.
    """
    p = Path(path)
    lines: List[str] = []
    if p.is_file():
        lines = p.read_text(encoding="utf-8").splitlines()

    found = False
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in stripped and \
                stripped.partition("=")[0].strip() == key:
            found = True
            if value is not None:
                out.append(f"{key}={value}")
            continue          # drop the line on unset
        out.append(line)

    if value is not None and not found:
        out.append(f"{key}={value}")

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")

    if value is None:
        return (f"Config file {path} modified." if found
                else f"No entry named '{key}' found.")
    return f"Config file {path} modified."


# ── rc.* command-line overrides ──────────────────────────────────────────────

def extract_rc_overrides(tokens: List[str]) -> Tuple[List[str], Dict[str, str]]:
    """Split rc.key=value / rc.key:value tokens out of an argv list.

    Returns (remaining_tokens, overrides).  Malformed rc.* tokens are
    dropped silently (the pre-0.4 behaviour was to strip all of them).
    """
    remaining: List[str] = []
    overrides: Dict[str, str] = {}
    for tok in tokens:
        if tok.startswith("rc.") and len(tok) > 3:
            body = tok[3:]
            for sep in ("=", ":"):
                if sep in body:
                    key, _, val = body.partition(sep)
                    if key:
                        overrides[key] = val
                    break
            continue
        if tok.startswith("rc:"):      # rc:<path> — alternate taskrc (CLI)
            overrides["__taskrc_path__"] = tok[3:]
            continue
        remaining.append(tok)
    return remaining, overrides
