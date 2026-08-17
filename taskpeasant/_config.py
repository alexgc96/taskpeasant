"""
taskpeasant/_config.py
CLI configuration file loading.

Loaded ONLY by the CLI entry point (__main__.py) at startup.  The
library path (execute_command and the cmd_* functions) never reads a
config file — headless callers pass yaml_path and UrgencyConfig
explicitly.

Search order:
  1. $TASKPEASANT_CONFIG            (explicit path)
  2. $XDG_CONFIG_HOME/taskpeasant/config.yaml
     ($XDG_CONFIG_HOME defaults to ~/.config)
  3. ~/.taskpeasantrc               (YAML, legacy-style fallback)

Schema (all keys optional):

    data:
      location: ~/tasks/work.yaml     # default YAML file (~ expanded)
    default:
      project: film                   # applied to `add` without project:
    urgency:                          # any UrgencyConfig field name
      active: 15.0
      blocking: 2.0
      priority: {H: 7.0, M: 4.0, L: 2.0}

Unknown urgency keys warn to stderr and are ignored; unknown top-level
keys are ignored silently (forward compatibility).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

import yaml

from .urgency import UrgencyConfig

_URGENCY_FIELDS = frozenset(f.name for f in fields(UrgencyConfig))


@dataclass
class CLIConfig:
    data_location:     str = ""
    default_project:   str = ""
    urgency_overrides: dict = field(default_factory=dict)
    source_path:       str = ""   # which file was loaded, for diagnostics


def find_config_path() -> Optional[str]:
    """Return the first existing config file per the search order, or None."""
    explicit = os.environ.get("TASKPEASANT_CONFIG", "")
    if explicit:
        return explicit if os.path.isfile(explicit) else None

    xdg_home = os.environ.get("XDG_CONFIG_HOME", "") or \
        os.path.join(os.path.expanduser("~"), ".config")
    xdg_path = os.path.join(xdg_home, "taskpeasant", "config.yaml")
    if os.path.isfile(xdg_path):
        return xdg_path

    rc_path = os.path.join(os.path.expanduser("~"), ".taskpeasantrc")
    if os.path.isfile(rc_path):
        return rc_path

    return None


def _warn(msg: str) -> None:
    print(f"[taskpeasant] config warning: {msg}", file=sys.stderr)


def load_cli_config(path: Optional[str] = None) -> CLIConfig:
    """Load the CLI config. Never raises: missing file or malformed YAML
    produce defaults (with a stderr warning for the malformed case)."""
    cfg = CLIConfig()
    path = path or find_config_path()
    if not path:
        return cfg

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        _warn(f"could not read {path}: {e}")
        return cfg
    if raw is None:
        return cfg
    if not isinstance(raw, dict):
        _warn(f"{path} is not a YAML mapping — ignoring it")
        return cfg

    cfg.source_path = path

    data = raw.get("data")
    if isinstance(data, dict) and data.get("location"):
        cfg.data_location = os.path.expanduser(str(data["location"]))

    default = raw.get("default")
    if isinstance(default, dict) and default.get("project"):
        cfg.default_project = str(default["project"])

    urgency = raw.get("urgency")
    if isinstance(urgency, dict):
        for key, val in urgency.items():
            if key not in _URGENCY_FIELDS:
                _warn(f"unknown urgency key '{key}' — ignoring it")
                continue
            if key == "priority":
                if isinstance(val, dict):
                    cfg.urgency_overrides["priority"] = {
                        str(k): float(v) for k, v in val.items()}
                else:
                    _warn("urgency.priority must be a mapping — ignoring it")
            else:
                try:
                    cfg.urgency_overrides[key] = float(val)
                except (TypeError, ValueError):
                    _warn(f"urgency.{key} must be a number — ignoring it")
    elif urgency is not None:
        _warn("urgency section must be a mapping — ignoring it")

    return cfg
