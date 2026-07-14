"""Milestone 3: TW attribute modifiers, regex, ID ranges, limit:, new vtags."""

from datetime import timedelta

import pytest

from taskpeasant.query import Filter, apply_filter
from tests.conftest import iso, now_utc


def match(tokens, task, all_tasks=None):
    return task in apply_filter(all_tasks or [task], tokens,
                                all_tasks=all_tasks)


# ── String modifiers ─────────────────────────────────────────────────────────

def test_is_isnt(make_task):
    t = make_task(description="render shot", project="film")
    assert match(["project.is:film"], t)
    assert not match(["project.is:fil"], t)
    assert match(["project.isnt:audio"], t)
    assert match(["description.is:render shot".replace(" ", " ")], t) \
        is False   # exact match only


def test_has_hasnt(make_task):
    t = make_task(description="Render the Final Shot")
    assert match(["description.has:final"], t)
    assert not match(["description.hasnt:final"], t)
    assert match(["description.hasnt:zzz"], t)


def test_startswith_endswith(make_task):
    t = make_task(description="alpha beta gamma")
    assert match(["description.startswith:alpha"], t)
    assert match(["description.left:alpha"], t)
    assert match(["description.endswith:gamma"], t)
    assert match(["description.right:gamma"], t)
    assert not match(["description.startswith:beta"], t)


def test_word_noword(make_task):
    t = make_task(description="fix the fixture")
    assert match(["description.word:fix"], t)
    assert not match(["description.word:fixt"], t)
    assert match(["description.noword:broken"], t)
    assert not match(["description.noword:fixture"], t)


def test_attribute_abbreviations(make_task):
    t = make_task(description="something", project="film", priority="H")
    assert match(["proj:film"], t)
    assert match(["pri:H"], t)
    assert match(["desc.has:some"], t)


# ── Project hierarchy ────────────────────────────────────────────────────────

def test_project_matches_subprojects(make_task):
    t = make_task(project="film.editing")
    assert match(["project:film"], t)
    assert match(["project:film.editing"], t)
    assert not match(["project:filmx"], t)
    assert match(["project.is:film.editing"], t)
    assert not match(["project.is:film"], t)


# ── Date modifiers ───────────────────────────────────────────────────────────

def test_date_before_after_by(make_task):
    t = make_task(due=iso(now_utc() + timedelta(days=3)))
    assert match(["due.before:+5d"], t)
    assert not match(["due.before:today"], t)
    assert match(["due.after:today"], t)
    assert match(["due.by:+3d"], t)
    assert not match(["due.by:+2d"], t)


def test_date_over_under_synonyms(make_task):
    t = make_task(due=iso(now_utc() + timedelta(days=3)))
    assert match(["due.under:+5d"], t)
    assert match(["due.over:yesterday"], t)


def test_date_is_day_equality(make_task):
    t = make_task(due=iso(now_utc() + timedelta(days=1)))
    assert match(["due.is:tomorrow"], t)
    assert not match(["due.is:today"], t)
    assert match(["due.isnt:today"], t)


def test_plain_date_attr_matches_day(make_task):
    t = make_task(due=iso(now_utc() + timedelta(days=1)))
    assert match(["due:tomorrow"], t)
    assert not match(["due:today"], t)


def test_plain_date_attr_empty_means_none(make_task):
    with_due = make_task(due=iso(now_utc()))
    without  = make_task()
    assert not match(["due:"], with_due)
    assert match(["due:"], without)


def test_entry_end_modified_filterable(make_task):
    t = make_task(entry=iso(now_utc() - timedelta(days=10)))
    assert match(["entry.before:-5d"], t)
    assert not match(["entry.after:today"], t)


def test_compound_date_expression_in_filter(make_task):
    t = make_task(due=iso(now_utc() + timedelta(days=40)))
    assert match(["due.after:eom"], t)


# ── Numeric modifiers (urgency) ───────────────────────────────────────────────

def test_urgency_over_under(make_task):
    urgent = make_task(priority="H", tags=["urgent", "next"])
    mild   = make_task()
    assert match(["urgency.over:5"], urgent)
    assert not match(["urgency.over:5"], mild)
    assert match(["urgency.under:5"], mild)


# ── Regex ─────────────────────────────────────────────────────────────────────

def test_regex_token(make_task):
    t = make_task(description="render shot 42")
    assert match(["/shot \\d+/"], t)
    assert not match(["/^shot/"], t)


def test_bad_regex_is_unknown_token(make_task):
    f = Filter.parse(["/([unclosed/"])
    assert f.unknown_tokens


# ── ID specs ──────────────────────────────────────────────────────────────────

def _with_ids(tasks):
    for i, t in enumerate(tasks, start=1):
        t.id = i
    return tasks


def test_id_single(make_task):
    a, b = _with_ids([make_task(), make_task()])
    assert match(["1"], a, all_tasks=[a, b])
    assert not match(["1"], b, all_tasks=[a, b])


def test_id_range_and_list(make_task):
    tasks = _with_ids([make_task() for _ in range(5)])
    got = apply_filter(tasks, ["2-3,5"])
    assert [t.id for t in got] == [2, 3, 5]


# ── limit: ────────────────────────────────────────────────────────────────────

def test_limit_captured_not_unknown():
    f = Filter.parse(["limit:5", "+work"])
    assert f.limit == "5"
    assert not f.unknown_tokens


def test_limit_page():
    f = Filter.parse(["limit:page"])
    assert f.limit == "page"


# ── UDA filters ───────────────────────────────────────────────────────────────

def test_uda_equality(make_task):
    t = make_task(udas={"size": "large"})
    assert match(["size:large"], t)
    assert not match(["size:small"], t)


def test_uda_modifier(make_task):
    t = make_task(udas={"size": "large"})
    assert match(["size.has:arg"], t)
    assert match(["size.any:"], t)
    assert not match(["size.none:"], t)


# ── New virtual tags ─────────────────────────────────────────────────────────

def test_ready_vtag(make_task):
    plain     = make_task()
    scheduled = make_task(scheduled=iso(now_utc() + timedelta(days=2)))
    past_sch  = make_task(scheduled=iso(now_utc() - timedelta(days=1)))
    tasks = [plain, scheduled, past_sch]
    got = apply_filter(tasks, ["+READY"])
    assert plain in got and past_sch in got and scheduled not in got


def test_ready_excludes_blocked(make_task):
    dep     = make_task()
    blocked = make_task(depends=[dep.uuid])
    got = apply_filter([dep, blocked], ["+READY"])
    assert dep in got and blocked not in got


def test_unblocked_vtag(make_task):
    dep     = make_task()
    blocked = make_task(depends=[dep.uuid])
    got = apply_filter([dep, blocked], ["+UNBLOCKED"])
    assert dep in got and blocked not in got


def test_latest_vtag(make_task):
    old = make_task(entry=iso(now_utc() - timedelta(days=9)))
    new = make_task(entry=iso(now_utc() - timedelta(hours=1)))
    got = apply_filter([old, new], ["+LATEST"])
    assert got == [new]


def test_uda_vtag(make_task):
    t = make_task(udas={"size": "xl"})
    plain = make_task()
    got = apply_filter([t, plain], ["+UDA"])
    assert t in got and plain not in got
