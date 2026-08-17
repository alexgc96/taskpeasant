"""Milestone 1: TW-style taskrc config — parsing, layering, rc overrides,
show/config commands, legacy YAML config coexistence."""

import os

import pytest

from taskpeasant import execute_command
from taskpeasant._taskrc import (
    DEFAULTS, Taskrc, default_taskrc_write_path, extract_rc_overrides,
    find_taskrc_path, load_taskrc, looks_like_yaml_mapping,
    parse_taskrc_text, write_taskrc_value,
)


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_parse_basic_key_values():
    values = parse_taskrc_text("a=1\nb=hello world\n# comment\n\nc=x=y\n")
    assert values == {"a": "1", "b": "hello world", "c": "x=y"}


def test_parse_ignores_garbage_lines():
    values = parse_taskrc_text("no equals here\n  # indented comment\nk=v")
    assert values == {"k": "v"}


def test_parse_include(tmp_path):
    inc = tmp_path / "theme.rc"
    inc.write_text("color.due=magenta\n")
    values = parse_taskrc_text(f"a=1\ninclude {inc}\n", str(tmp_path))
    assert values == {"a": "1", "color.due": "magenta"}


def test_parse_include_relative(tmp_path):
    (tmp_path / "sub.rc").write_text("x=1\n")
    values = parse_taskrc_text("include sub.rc\n", str(tmp_path))
    assert values == {"x": "1"}


def test_parse_include_missing_file_ignored(tmp_path):
    values = parse_taskrc_text("include /nonexistent/nope.rc\na=1\n")
    assert values == {"a": "1"}


def test_parse_include_cycle_guard(tmp_path):
    rc = tmp_path / "loop.rc"
    rc.write_text(f"include {rc}\na=1\n")
    values = parse_taskrc_text(rc.read_text(), str(tmp_path))
    assert values["a"] == "1"     # terminates


# ── Layering / typed getters ─────────────────────────────────────────────────

def test_defaults_present():
    conf = Taskrc()
    assert conf.get("urgency.due.coefficient") == "12.0"
    assert conf.get("report.next.sort") == "urgency-"
    assert conf.get_bool("confirmation") is True
    assert conf.get_bool("recurrence") is False   # TP opt-in default


def test_file_values_override_defaults():
    conf = Taskrc({"urgency.due.coefficient": "20.0"})
    assert conf.get_float("urgency.due.coefficient") == 20.0
    assert not conf.is_default("urgency.due.coefficient")
    assert conf.is_default("urgency.active.coefficient")


def test_typed_getters_fall_back_on_garbage():
    conf = Taskrc({"n": "not-a-number"})
    assert conf.get_int("n", 5) == 5
    assert conf.get_float("n", 1.5) == 1.5
    assert conf.get_int("missing", 7) == 7


def test_bool_variants():
    conf = Taskrc({"a": "yes", "b": "on", "c": "0", "d": "no", "e": "true"})
    assert conf.get_bool("a") and conf.get_bool("b") and conf.get_bool("e")
    assert not conf.get_bool("c") and not conf.get_bool("d")


def test_subtree():
    conf = Taskrc({"alias.rm": "delete", "alias.burn": "burndown.daily"})
    assert conf.subtree("alias.") == {"rm": "delete", "burn": "burndown.daily"}


def test_report_names_includes_builtins_and_custom():
    conf = Taskrc({"report.foo.columns": "id,description"})
    names = conf.report_names()
    for builtin in ("next", "list", "ls", "all", "ready", "waiting",
                    "completed", "overdue", "blocked", "blocking",
                    "newest", "oldest", "minimal", "long", "active",
                    "unblocked", "recurring"):
        assert builtin in names
    assert "foo" in names


# ── rc.* override extraction ─────────────────────────────────────────────────

def test_extract_rc_overrides_equals_and_colon():
    tokens, ov = extract_rc_overrides(
        ["rc.gc=off", "+tag", "rc.report.next.sort:due+", "list"])
    assert tokens == ["+tag", "list"]
    assert ov == {"gc": "off", "report.next.sort": "due+"}


def test_extract_rc_alternate_taskrc():
    tokens, ov = extract_rc_overrides(["rc:/tmp/x.rc", "list"])
    assert tokens == ["list"]
    assert ov["__taskrc_path__"] == "/tmp/x.rc"


def test_extract_rc_malformed_dropped():
    tokens, ov = extract_rc_overrides(["rc.noseparator", "list"])
    assert tokens == ["list"]
    assert ov == {}


# ── File discovery & format detection ────────────────────────────────────────

def test_looks_like_yaml_mapping(tmp_path):
    y = tmp_path / "legacy"
    y.write_text("data:\n  location: ~/x.yaml\n")
    t = tmp_path / "taskrc"
    t.write_text("color.due=red\n")
    assert looks_like_yaml_mapping(str(y))
    assert not looks_like_yaml_mapping(str(t))


def test_find_taskrc_env_var(tmp_path, monkeypatch):
    rc = tmp_path / "my.rc"
    rc.write_text("a=1\n")
    monkeypatch.setenv("TASKPEASANT_TASKRC", str(rc))
    assert find_taskrc_path() == str(rc)


def test_find_taskrc_skips_legacy_yaml_taskpeasantrc(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKPEASANT_TASKRC", raising=False)
    monkeypatch.delenv("TASKRC", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    legacy = tmp_path / ".taskpeasantrc"
    legacy.write_text("urgency:\n  active: 10.0\n")   # YAML mapping = legacy
    assert find_taskrc_path() is None


def test_find_taskrc_accepts_taskrc_format_taskpeasantrc(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKPEASANT_TASKRC", raising=False)
    monkeypatch.delenv("TASKRC", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = tmp_path / ".taskpeasantrc"
    rc.write_text("urgency.due.coefficient=9.0\n")
    assert find_taskrc_path() == str(rc)


def test_load_taskrc_missing_returns_defaults(tmp_path):
    conf = load_taskrc(str(tmp_path / "nope.rc"))
    assert conf.get("urgency.due.coefficient") == "12.0"
    assert conf.source_path == ""


# ── config write helper ───────────────────────────────────────────────────────

def test_write_taskrc_value_append_and_replace(tmp_path):
    rc = tmp_path / "taskrc"
    write_taskrc_value(str(rc), "color.due", "red")
    assert "color.due=red" in rc.read_text()
    write_taskrc_value(str(rc), "color.due", "blue")
    text = rc.read_text()
    assert "color.due=blue" in text and "color.due=red" not in text


def test_write_taskrc_value_unset(tmp_path):
    rc = tmp_path / "taskrc"
    rc.write_text("a=1\nb=2\n")
    write_taskrc_value(str(rc), "a", None)
    assert "a=1" not in rc.read_text()
    assert "b=2" in rc.read_text()


def test_write_taskrc_preserves_comments(tmp_path):
    rc = tmp_path / "taskrc"
    rc.write_text("# my settings\na=1\n")
    write_taskrc_value(str(rc), "a", "2")
    assert "# my settings" in rc.read_text()


# ── show / config via execute_command ────────────────────────────────────────

def test_show_all(yaml_file):
    out = execute_command("task show", yaml_file)
    assert "urgency.due.coefficient" in out
    assert "12.0" in out


def test_show_pattern(yaml_file):
    out = execute_command("task show report.next", yaml_file)
    assert "report.next.sort" in out
    assert "report.list.sort" not in out


def test_show_no_match(yaml_file):
    out = execute_command("task show zzznope", yaml_file)
    assert "No configuration settings match" in out


def test_show_reflects_rc_override(yaml_file):
    out = execute_command("task rc.urgency.due.coefficient=42 show urgency.due",
                          yaml_file)
    assert "42" in out
    assert "*" in out   # marked non-default


def test_config_via_library_writes_taskrc(yaml_file, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    out = execute_command("task config color.due red", yaml_file)
    assert "modified" in out
    rc = tmp_path / "taskpeasant" / "taskrc"
    assert rc.is_file() and "color.due=red" in rc.read_text()


def test_config_requires_key(yaml_file):
    out = execute_command("task config", yaml_file)
    assert "Specify" in out


def test_unknown_rc_keys_still_silently_ignored(yaml_file):
    # Pre-0.4 contract: hosts may send rc.* noise; it must not break anything
    execute_command("task rc.gc=off rc.confirmation=off add compat check",
                    yaml_file)
    out = execute_command("task rc.whatever=1", yaml_file)
    assert "compat check" in out


def test_execute_command_accepts_config_kwarg(yaml_file):
    conf = Taskrc({"urgency.due.coefficient": "33.0"})
    out = execute_command("task show urgency.due.coefficient", yaml_file,
                          config=conf)
    assert "33.0" in out
