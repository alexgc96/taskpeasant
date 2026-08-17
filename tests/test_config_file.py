"""CLI config file: search order, schema, precedence, resilience."""

from __future__ import annotations

import pytest

from taskpeasant import read_tasks
from taskpeasant._config import CLIConfig, find_config_path, load_cli_config


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated $HOME with no ambient config env vars."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("TASKPEASANT_CONFIG", raising=False)
    monkeypatch.delenv("TASKPEASANT_FILE", raising=False)
    return tmp_path


def write_cfg(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_no_config_returns_defaults(home):
    assert find_config_path() is None
    cfg = load_cli_config()
    assert cfg == CLIConfig()


def test_xdg_default_path(home):
    p = write_cfg(home / ".config" / "taskpeasant" / "config.yaml",
                  "default:\n  project: film\n")
    assert find_config_path() == p
    assert load_cli_config().default_project == "film"


def test_xdg_config_home_override(home, tmp_path, monkeypatch):
    alt = tmp_path / "alt-xdg"
    p = write_cfg(alt / "taskpeasant" / "config.yaml",
                  "default:\n  project: web\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(alt))
    assert find_config_path() == p


def test_taskpeasantrc_fallback(home):
    p = write_cfg(home / ".taskpeasantrc", "default:\n  project: rc\n")
    assert find_config_path() == p
    assert load_cli_config().default_project == "rc"


def test_explicit_env_config_wins(home, monkeypatch):
    write_cfg(home / ".config" / "taskpeasant" / "config.yaml",
              "default:\n  project: xdg\n")
    p = write_cfg(home / "explicit.yaml", "default:\n  project: explicit\n")
    monkeypatch.setenv("TASKPEASANT_CONFIG", p)
    assert find_config_path() == p
    assert load_cli_config().default_project == "explicit"


def test_data_location_tilde_expanded(home):
    write_cfg(home / ".taskpeasantrc", "data:\n  location: ~/tasks/work.yaml\n")
    cfg = load_cli_config()
    assert cfg.data_location == str(home / "tasks" / "work.yaml")


def test_urgency_overrides_parsed(home, capsys):
    write_cfg(home / ".taskpeasantrc",
              "urgency:\n"
              "  blocking: 5.0\n"
              "  priority: {H: 7.0, M: 4.0, L: 2.0}\n"
              "  bogus_key: 1.0\n")
    cfg = load_cli_config()
    assert cfg.urgency_overrides["blocking"] == 5.0
    assert cfg.urgency_overrides["priority"] == {"H": 7.0, "M": 4.0, "L": 2.0}
    assert "bogus_key" not in cfg.urgency_overrides
    assert "bogus_key" in capsys.readouterr().err


def test_malformed_yaml_never_raises(home, capsys):
    write_cfg(home / ".taskpeasantrc", "not: [valid: yaml: {{{{")
    cfg = load_cli_config()
    assert cfg == CLIConfig()
    assert "warning" in capsys.readouterr().err


def test_non_mapping_config_ignored(home, capsys):
    write_cfg(home / ".taskpeasantrc", "- just\n- a\n- list\n")
    assert load_cli_config() == CLIConfig()
    assert "warning" in capsys.readouterr().err


# ── End-to-end through the CLI entry point ───────────────────────────────────

def run_cli(monkeypatch, argv):
    import taskpeasant.__main__ as M
    monkeypatch.setattr("sys.argv", ["tp"] + argv)
    M.main()


def test_config_data_location_used_by_cli(home, monkeypatch, capsys):
    data = home / "from-config.yaml"
    write_cfg(home / ".taskpeasantrc", f"data:\n  location: {data}\n")
    run_cli(monkeypatch, ["task", "add", "config-driven", "task"])
    tasks = read_tasks(str(data))
    assert len(tasks) == 1


def test_file_flag_beats_env_beats_config(home, monkeypatch):
    cfg_file = home / "cfg.yaml"
    env_file = home / "env.yaml"
    flag_file = home / "flag.yaml"
    write_cfg(home / ".taskpeasantrc", f"data:\n  location: {cfg_file}\n")

    monkeypatch.setenv("TASKPEASANT_FILE", str(env_file))
    run_cli(monkeypatch, ["task", "add", "goes-to-env"])
    assert len(read_tasks(str(env_file))) == 1
    assert read_tasks(str(cfg_file)) == []

    run_cli(monkeypatch, ["--file", str(flag_file), "task", "add", "goes-to-flag"])
    assert len(read_tasks(str(flag_file))) == 1
    assert len(read_tasks(str(env_file))) == 1  # unchanged


def test_default_project_applied_on_add(home, monkeypatch):
    data = home / "t.yaml"
    write_cfg(home / ".taskpeasantrc",
              f"data:\n  location: {data}\ndefault:\n  project: film\n")
    run_cli(monkeypatch, ["task", "add", "no project given"])
    assert read_tasks(str(data))[0].project == "film"

    run_cli(monkeypatch, ["task", "add", "explicit", "project:web"])
    assert read_tasks(str(data))[1].project == "web"


def test_urgency_override_affects_cli_scoring(home, monkeypatch, capsys):
    import taskpeasant.urgency as U
    original = dict(U.WEIGHTS)
    data = home / "t.yaml"
    write_cfg(home / ".taskpeasantrc",
              f"data:\n  location: {data}\nurgency:\n  tag_urgent: 19.0\n")
    try:
        run_cli(monkeypatch, ["task", "add", "hot", "+urgent"])
        assert U.WEIGHTS["tag_urgent"] == 19.0
        tasks = read_tasks(str(data))
        from taskpeasant import compute_urgency
        assert compute_urgency(tasks[0]) >= 19.0
    finally:
        U.WEIGHTS.clear()
        U.WEIGHTS.update(original)
