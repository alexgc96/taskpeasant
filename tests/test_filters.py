"""Filter expression engine: legacy tokens, boolean operators, parens."""

from __future__ import annotations

from datetime import timedelta

import pytest

from taskpeasant import execute_command, read_tasks
from taskpeasant.query import Filter, FilterError, apply_filter, _retokenize

from .conftest import (UUID_DONE, UUID_OVERDUE, UUID_PLAIN, UUID_SOON,
                       iso, now_utc)


def names(tasks):
    return {t.description for t in tasks}


# ── Legacy token behavior unchanged ─────────────────────────────────────────

def test_implicit_and(make_task):
    a = make_task(description="a", tags=["x", "y"])
    b = make_task(description="b", tags=["x"])
    assert names(apply_filter([a, b], ["+x", "+y"])) == {"a"}


def test_tag_exclusion(make_task):
    a = make_task(description="a", tags=["x"])
    b = make_task(description="b")
    assert names(apply_filter([a, b], ["-x"])) == {"b"}


def test_bare_word_description_search(make_task):
    a = make_task(description="Fix the Widget")
    b = make_task(description="other")
    assert names(apply_filter([a, b], ["widget"])) == {"Fix the Widget"}


def test_date_before_after(make_task):
    early = make_task(description="early", due=iso(now_utc() + timedelta(days=1)))
    late = make_task(description="late", due=iso(now_utc() + timedelta(days=10)))
    assert names(apply_filter([early, late], ["due.before:+5d"])) == {"early"}
    assert names(apply_filter([early, late], ["due.after:+5d"])) == {"late"}


def test_any_none_presence(make_task):
    dated = make_task(description="dated", due=iso(now_utc()))
    bare = make_task(description="bare")
    assert names(apply_filter([dated, bare], ["due.any:"])) == {"dated"}
    assert names(apply_filter([dated, bare], ["due.none:"])) == {"bare"}


def test_empty_filter_matches_all(make_task):
    tasks = [make_task(), make_task()]
    assert len(apply_filter(tasks, [])) == 2


# ── Boolean operators ────────────────────────────────────────────────────────

@pytest.fixture
def trio(make_task):
    return [
        make_task(description="urgent-film", tags=["urgent"], project="film"),
        make_task(description="calm-film", project="film"),
        make_task(description="urgent-web", tags=["urgent"], project="web"),
    ]


def test_or(trio):
    got = names(apply_filter(trio, ["+urgent", "or", "project:film"]))
    assert got == {"urgent-film", "calm-film", "urgent-web"}


def test_explicit_and(trio):
    got = names(apply_filter(trio, ["+urgent", "and", "project:film"]))
    assert got == {"urgent-film"}


def test_not(trio):
    got = names(apply_filter(trio, ["not", "+urgent"]))
    assert got == {"calm-film"}


def test_xor(trio):
    got = names(apply_filter(trio, ["+urgent", "xor", "project:film"]))
    assert got == {"calm-film", "urgent-web"}


def test_precedence_and_binds_tighter_than_or(trio):
    # a or b and c  ≡  a or (b and c)
    got = names(apply_filter(
        trio, ["project:web", "or", "+urgent", "and", "project:film"]))
    assert got == {"urgent-web", "urgent-film"}


def test_parens_override_precedence(trio):
    got = names(apply_filter(
        trio, ["(", "project:web", "or", "+urgent", ")", "and", "project:film"]))
    assert got == {"urgent-film"}


def test_glued_parens_from_shlex(trio):
    # shlex delivers '(project:web' and 'project:film)' as single tokens
    got = names(apply_filter(
        trio, ["(project:web", "or", "+urgent)", "and", "project:film"]))
    assert got == {"urgent-film"}


def test_nested_parens(trio):
    got = names(apply_filter(
        trio, ["((+urgent))", "and", "(not", "(project:web))"]))
    assert got == {"urgent-film"}


def test_operator_keywords_case_insensitive(trio):
    got = names(apply_filter(trio, ["+urgent", "OR", "project:film"]))
    assert got == {"urgent-film", "calm-film", "urgent-web"}


def test_retokenize():
    assert _retokenize(["(+a", "or", "+b)"]) == ["(", "+a", "or", "+b", ")"]
    assert _retokenize(["((x))"]) == ["(", "(", "x", ")", ")"]
    # mid-token parens survive
    assert _retokenize(["desc(with)parens"]) == ["desc(with)parens"]
    # whole shell-quoted expression re-splits
    assert _retokenize(["(+a or +b)"]) == ["(", "+a", "or", "+b", ")"]
    # ...but a quoted multi-word literal (no parens) stays atomic
    assert _retokenize(["waiting or blocked"]) == ["waiting or blocked"]


def test_shell_quoted_expression_single_token(trio):
    got = names(apply_filter(trio, ["(+urgent or project:film)"]))
    assert got == {"urgent-film", "calm-film", "urgent-web"}


def test_quoted_multiword_literal_is_description_search(make_task):
    a = make_task(description="this is waiting or blocked on review")
    b = make_task(description="or")
    got = names(apply_filter([a, b], ["waiting or blocked"]))
    assert got == {"this is waiting or blocked on review"}


# ── Errors ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    ["(", "+a"],
    ["+a", ")"],
    ["+a", "or"],
    ["or", "+a"],
    ["+a", "and"],
    ["not"],
])
def test_malformed_expression_raises_filter_error(bad):
    with pytest.raises(FilterError):
        Filter.parse(bad)


def test_malformed_filter_via_execute_command_returns_error_string(seeded_yaml):
    out = execute_command("task ( +urgent", seeded_yaml)
    assert isinstance(out, str)
    assert out.startswith("Error")


# ── New leaf types ───────────────────────────────────────────────────────────

def test_tag_any_list(make_task):
    a = make_task(description="a", tags=["x"])
    b = make_task(description="b", tags=["y"])
    c = make_task(description="c")
    assert names(apply_filter([a, b, c], ["tag.any:x,z"])) == {"a"}
    assert names(apply_filter([a, b, c], ["tag.none:x,z"])) == {"b", "c"}


def test_tag_any_none_empty_value(make_task):
    tagged = make_task(description="tagged", tags=["x"])
    plain = make_task(description="plain")
    assert names(apply_filter([tagged, plain], ["tag.any:"])) == {"tagged"}
    assert names(apply_filter([tagged, plain], ["tag.none:"])) == {"plain"}


def test_description_contains(make_task):
    a = make_task(description="Fix the Widget")
    b = make_task(description="other")
    assert names(apply_filter([a, b], ["description.contains:widget"])) == \
        {"Fix the Widget"}
    assert names(apply_filter([a, b], ["description.has:WIDGET"])) == \
        {"Fix the Widget"}


# ── Virtual tags in filters ──────────────────────────────────────────────────

def test_virtual_tag_filtering(make_task):
    overdue = make_task(description="overdue",
                        due=iso(now_utc() - timedelta(days=1)))
    fresh = make_task(description="fresh")
    assert names(apply_filter([overdue, fresh], ["+OVERDUE"])) == {"overdue"}
    assert names(apply_filter([overdue, fresh], ["-OVERDUE"])) == {"fresh"}


def test_blocked_filter_with_narrowed_subset(make_task):
    blocker = make_task(description="blocker")
    blocked = make_task(description="blocked", depends=[blocker.uuid])
    # Filtering only [blocked] but passing the full graph via all_tasks
    got = apply_filter([blocked], ["+BLOCKED"], all_tasks=[blocker, blocked])
    assert names(got) == {"blocked"}


def test_virtual_tag_filter_through_cli(seeded_yaml):
    out = execute_command("task +OVERDUE", seeded_yaml)
    assert "ship overdue report" in out
    assert "colour grade reel" not in out
    out = execute_command("task +BLOCKED", seeded_yaml)
    assert "colour grade reel" in out


def test_or_expression_through_cli(seeded_yaml):
    out = execute_command("task (+urgent or +next)", seeded_yaml)
    assert "ship overdue report" in out
    assert "refactor website nav" in out
    assert "colour grade reel" not in out
