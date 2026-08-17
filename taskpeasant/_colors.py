"""
taskpeasant/_colors.py
Taskwarrior color rules, rendered through rich.

Config keys (same names as TW):

    color.active, color.blocked, color.blocking, color.overdue, color.due,
    color.due.today, color.scheduled, color.recurring, color.tagged,
    color.completed, color.deleted, color.tag.<tag>, color.project.<name>,
    color.keyword.<word>, color.uda.<name>[.<value>]

Rule precedence comes from `rule.precedence.color` (highest first;
entries ending in "." are prefix families).  The first matching rule
with a non-empty color wins the row style.

TW color specs ("bold red on bright yellow", "color15", "rgb530",
"gray10", "underline") are translated to rich style strings.
"""

from __future__ import annotations

import re
from typing import Optional

from .task_model import Task

_ATTR_WORDS = {
    "bold": "bold", "underline": "underline", "inverse": "reverse",
    "dim": "dim", "blink": "blink", "italic": "italic",
}


def _tw_color_word(word: str) -> Optional[str]:
    """One TW color word → rich color name, or None if not a color."""
    w = word.lower()
    m = re.fullmatch(r'color(\d{1,3})', w)
    if m and int(m.group(1)) <= 255:
        return f"color({m.group(1)})"
    m = re.fullmatch(r'rgb([0-5])([0-5])([0-5])', w)
    if m:
        r, g, b = (int(x) for x in m.groups())
        return f"color({16 + 36 * r + 6 * g + b})"
    m = re.fullmatch(r'gr[ae]y(\d{1,2})', w)
    if m and int(m.group(1)) <= 23:
        return f"color({232 + int(m.group(1))})"
    if w in ("black", "red", "green", "yellow", "blue", "magenta", "cyan",
             "white"):
        return w
    return None


def tw_style(spec: str) -> str:
    """TW color spec → rich style string ('' when unparseable/empty)."""
    spec = (spec or "").strip()
    if not spec:
        return ""

    parts: list = []
    on_seen = False
    words = spec.replace("_", " ").split()
    i = 0
    while i < len(words):
        w = words[i].lower()
        if w == "on":
            on_seen = True
            i += 1
            continue
        if w == "bright" and i + 1 < len(words):
            color = _tw_color_word(words[i + 1])
            if color and "(" not in color:
                color = f"bright_{color}"
            if color:
                parts.append(f"on {color}" if on_seen else color)
            i += 2
            continue
        if w in _ATTR_WORDS:
            parts.append(_ATTR_WORDS[w])
            i += 1
            continue
        color = _tw_color_word(w) or (w if w.startswith("bright_") else None)
        if color:
            parts.append(f"on {color}" if on_seen else color)
        i += 1

    style = " ".join(parts)
    try:
        from rich.style import Style
        Style.parse(style)
    except Exception:
        return ""
    return style


_DEFAULT_PRECEDENCE = ("deleted,completed,active,keyword.,tag.,project.,"
                       "overdue,scheduled,due.today,due,blocked,blocking,"
                       "recurring,tagged,uda.")


def _rule_spec(task: Task, rule: str, conf) -> str:
    """The TW color spec for one rule if the task matches it, else ''."""
    vt = task.virtual_tags

    if rule == "deleted":
        return conf.get("color.deleted") if task.status == "deleted" else ""
    if rule == "completed":
        return conf.get("color.completed") \
            if task.status == "completed" else ""
    if rule == "active":
        return conf.get("color.active") if task.start else ""
    if rule == "overdue":
        return conf.get("color.overdue") if "OVERDUE" in vt else ""
    if rule == "due.today":
        return conf.get("color.due.today") if "TODAY" in vt else ""
    if rule == "due":
        return conf.get("color.due") if "DUE" in vt else ""
    if rule == "scheduled":
        return conf.get("color.scheduled") if "SCHEDULED" in vt else ""
    if rule == "blocked":
        return conf.get("color.blocked") if "BLOCKED" in vt else ""
    if rule == "blocking":
        return conf.get("color.blocking") if "BLOCKING" in vt else ""
    if rule == "recurring":
        return conf.get("color.recurring") \
            if task.udas.get("recur") or task.status == "recurring" else ""
    if rule == "tagged":
        return conf.get("color.tagged") if task.tags else ""

    if rule == "tag.":
        for tag in task.tags:
            spec = conf.get(f"color.tag.{tag}")
            if spec:
                return spec
        return ""
    if rule == "project.":
        if task.project:
            spec = conf.get(f"color.project.{task.project}")
            if spec:
                return spec
            parent = task.project.split(".")[0]
            return conf.get(f"color.project.{parent}")
        return ""
    if rule == "keyword.":
        desc = task.description.lower()
        for key, spec in conf.subtree("color.keyword.").items():
            if spec and key.lower() in desc:
                return spec
        return ""
    if rule == "uda.":
        for name, value in task.udas.items():
            spec = conf.get(f"color.uda.{name}.{value}")
            if spec:
                return spec
            spec = conf.get(f"color.uda.{name}")
            if spec:
                return spec
        return ""
    return ""


def style_for_task(task: Task, conf) -> str:
    """rich style for a task row per the color rules ('' = default)."""
    if conf is None or not conf.get_bool("color", True):
        return ""
    precedence = conf.get("rule.precedence.color", _DEFAULT_PRECEDENCE)
    for rule in (r.strip() for r in precedence.split(",")):
        if not rule:
            continue
        spec = _rule_spec(task, rule, conf)
        if spec:
            style = tw_style(spec)
            if style:
                return style
    return ""


def cmd_colors(conf) -> str:
    """`task colors` — every color.* setting and its value."""
    rules = [(k, v) for k, v in conf.items() if k.startswith("color.")]
    width = max(len(k) for k, _ in rules)
    lines = [f"{'Rule':<{width}}  Color", "-" * (width + 24)]
    for k, v in rules:
        lines.append(f"{k:<{width}}  {v or '(none)'}")
    lines.append("")
    lines.append(f"{len(rules)} color rules — precedence: "
                 + conf.get("rule.precedence.color", _DEFAULT_PRECEDENCE))
    return "\n".join(lines)
