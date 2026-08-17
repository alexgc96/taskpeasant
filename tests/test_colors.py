"""Milestone 7: TW color specs → rich styles, rule precedence, task colors."""

from datetime import timedelta

import pytest

from taskpeasant import execute_command
from taskpeasant._colors import style_for_task, tw_style
from taskpeasant._taskrc import Taskrc
from taskpeasant._vtags import annotate_virtual_tags
from tests.conftest import iso, now_utc


# ── Spec translation ──────────────────────────────────────────────────────────

def test_basic_colors():
    assert tw_style("red") == "red"
    assert tw_style("bold red") == "bold red"
    assert tw_style("red on white") == "red on white"
    assert tw_style("bold red on bright yellow") == \
        "bold red on bright_yellow"


def test_256_colors():
    assert tw_style("color15") == "color(15)"
    assert tw_style("color15 on color1") == "color(15) on color(1)"
    assert tw_style("rgb500") == "color(196)"       # pure red in the cube
    assert tw_style("gray10") == "color(242)"
    assert tw_style("grey0") == "color(232)"


def test_attributes_and_garbage():
    assert tw_style("underline blue") == "underline blue"
    assert tw_style("inverse") == "reverse"
    assert tw_style("") == ""
    assert tw_style("notacolor") == ""


def test_rich_style_passthrough():
    # DEFAULTS already use rich-style underscores
    assert tw_style("black on bright_green") == "black on bright_green"


# ── Rule matching / precedence ────────────────────────────────────────────────

def _styled(task, extra=None, tasks=None):
    conf = Taskrc(extra or {})
    annotate_virtual_tags(tasks or [task])
    return style_for_task(task, conf)


def test_overdue_rule(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=1)))
    assert _styled(t) == "bold red"       # color.overdue default


def test_active_beats_overdue(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=1)),
                  start=iso(now_utc()))
    assert _styled(t) == "black on bright_green"    # active precedes overdue


def test_tag_rule(make_task):
    t = make_task(tags=["urgent"])
    assert _styled(t, {"color.tag.urgent": "bold magenta"}) == "bold magenta"


def test_project_rule_with_parent_fallback(make_task):
    t = make_task(project="film.editing")
    assert _styled(t, {"color.project.film": "cyan"}) == "cyan"


def test_keyword_rule(make_task):
    t = make_task(description="fix the boiler now")
    assert _styled(t, {"color.keyword.boiler": "yellow"}) == "yellow"


def test_uda_rule_value_specific(make_task):
    t = make_task(udas={"size": "xl"})
    assert _styled(t, {"color.uda.size.xl": "red"}) == "red"
    assert _styled(t, {"color.uda.size": "blue"}) == "blue"


def test_color_off_disables_rules(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=1)))
    conf = Taskrc({"color": "off"})
    annotate_virtual_tags([t])
    assert style_for_task(t, conf) == ""


def test_custom_precedence(make_task):
    t = make_task(due=iso(now_utc() - timedelta(days=1)), tags=["urgent"])
    conf_default = {"color.tag.urgent": "magenta"}
    assert _styled(t, conf_default) == "magenta"    # tag. precedes overdue
    flipped = dict(conf_default)
    flipped["rule.precedence.color"] = "overdue,tag."
    assert _styled(t, flipped) == "bold red"


def test_blocked_rule(make_task):
    dep = make_task()
    t = make_task(depends=[dep.uuid])
    assert _styled(t, tasks=[dep, t]) == "black on white"


# ── colors command ────────────────────────────────────────────────────────────

def test_colors_command(yaml_file):
    out = execute_command("task colors", yaml_file)
    assert "color.overdue" in out and "bold red" in out
    assert "precedence" in out


def test_colors_reflects_override(yaml_file):
    out = execute_command("task rc.color.due=magenta colors", yaml_file)
    assert "magenta" in out
