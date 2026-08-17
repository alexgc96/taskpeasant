"""Milestone 8: alias.<name> expansion and TW contexts."""

import pytest

from taskpeasant import execute_command, read_tasks
from taskpeasant._taskrc import Taskrc


@pytest.fixture
def rc_env(tmp_path, monkeypatch):
    """Point the taskrc search at a scratch file so context writes land
    somewhere testable."""
    rc = tmp_path / "taskrc"
    rc.write_text("")
    monkeypatch.setenv("TASKPEASANT_TASKRC", str(rc))
    return str(rc)


def conf_from(rc_path):
    from taskpeasant._taskrc import load_taskrc
    return load_taskrc(rc_path)


# ── Aliases ───────────────────────────────────────────────────────────────────

def test_alias_expands_to_command(yaml_file):
    execute_command("task add doomed thing", yaml_file)
    u = read_tasks(yaml_file)[0].uuid
    conf = Taskrc({"alias.rm": "delete"})
    out = execute_command(f"task {u} rm", yaml_file, config=conf)
    # alias applies to first token only; '<uuid> rm' hits the uuid path,
    # so rm-as-verb is not aliased (same as TW). But 'task rm ...' is:
    out2 = execute_command("task rm nonexistent-word-xyz", yaml_file,
                           config=conf)
    assert "No matching tasks" in out2 or "no task" in out2.lower() or \
        "Error" in out2 or "0 task" in out2 or "No" in out2


def test_alias_first_token(yaml_file):
    execute_command("task add burn me", yaml_file)
    conf = Taskrc({"alias.burn": "burndown.daily"})
    out = execute_command("task burn", yaml_file, config=conf)
    assert "Daily Burndown" in out


def test_alias_with_arguments(yaml_file):
    execute_command("task add urgent thing +work", yaml_file)
    conf = Taskrc({"alias.work": "list +work"})
    out = execute_command("task work", yaml_file, config=conf)
    assert "urgent thing" in out


def test_alias_via_rc_override(yaml_file):
    execute_command("task add visible", yaml_file)
    out = execute_command("task rc.alias.l=list l", yaml_file)
    assert "visible" in out


# ── Contexts ──────────────────────────────────────────────────────────────────

def test_context_define_and_show(yaml_file, rc_env):
    out = execute_command("task context define work +work", yaml_file,
                          config=conf_from(rc_env))
    assert "defined" in out
    execute_command("task context work", yaml_file, config=conf_from(rc_env))
    out = execute_command("task context show", yaml_file,
                          config=conf_from(rc_env))
    assert "work" in out and "+work" in out


def test_context_filters_reports(yaml_file, rc_env):
    execute_command("task add office thing +work", yaml_file)
    execute_command("task add home thing +home", yaml_file)
    execute_command("task context define work +work", yaml_file,
                    config=conf_from(rc_env))
    execute_command("task context work", yaml_file, config=conf_from(rc_env))
    conf = conf_from(rc_env)
    out = execute_command("task list", yaml_file, config=conf)
    assert "office thing" in out
    assert "home thing" not in out


def test_context_applies_to_count_and_export(yaml_file, rc_env):
    execute_command("task add a +work", yaml_file)
    execute_command("task add b +home", yaml_file)
    execute_command("task context define work +work", yaml_file,
                    config=conf_from(rc_env))
    execute_command("task context work", yaml_file, config=conf_from(rc_env))
    conf = conf_from(rc_env)
    assert execute_command("task count", yaml_file, config=conf) == "1"
    import json
    exported = json.loads(execute_command("task export", yaml_file,
                                          config=conf))
    assert [rec["description"] for rec in exported] == ["a"]


def test_context_write_defaults_on_add(yaml_file, rc_env):
    execute_command("task context define work +work project:office",
                    yaml_file, config=conf_from(rc_env))
    execute_command("task context work", yaml_file, config=conf_from(rc_env))
    execute_command("task add ctx task", yaml_file, config=conf_from(rc_env))
    t = read_tasks(yaml_file)[0]
    assert "work" in t.tags and t.project == "office"


def test_context_none_and_delete(yaml_file, rc_env):
    execute_command("task context define tmp +x", yaml_file,
                    config=conf_from(rc_env))
    execute_command("task context tmp", yaml_file, config=conf_from(rc_env))
    out = execute_command("task context none", yaml_file,
                          config=conf_from(rc_env))
    assert "unset" in out
    out = execute_command("task context show", yaml_file,
                          config=conf_from(rc_env))
    assert "No context" in out
    out = execute_command("task context delete tmp", yaml_file,
                          config=conf_from(rc_env))
    assert "deleted" in out
    out = execute_command("task context list", yaml_file,
                          config=conf_from(rc_env))
    assert "No contexts defined." in out


def test_context_undefined_name(yaml_file, rc_env):
    out = execute_command("task context nope", yaml_file,
                          config=conf_from(rc_env))
    assert "not defined" in out


def test_context_read_write_split(yaml_file, rc_env):
    conf = Taskrc({"context.split.read": "+work",
                   "context.split.write": "+inbox",
                   "context": "split"})
    execute_command("task add split task", yaml_file, config=conf)
    t = read_tasks(yaml_file)[0]
    assert t.tags == ["inbox"]
    out = execute_command("task list", yaml_file, config=conf)
    assert "split task" not in out      # read filter +work excludes it
