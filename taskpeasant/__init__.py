"""
taskpeasant — a YAML-native, pure-Python task backend.
Drop-in replacement for Taskwarrior for local-first deployments and
platforms where a Taskwarrior binary is unavailable (e.g. native Windows).

Built by analogtrsh studio. GPL-3.0-or-later licensed.
"""

from .task_model import Task
from .storage import read_tasks, write_tasks, assign_ids
from .commands import (cmd_add, cmd_done, cmd_delete, cmd_start,
                       cmd_stop, cmd_annotate, cmd_modify, cmd_export,
                       cmd_bulk)
from .urgency import compute_urgency, UrgencyConfig, DEFAULT_CONFIG
from .peasant_parser import execute_command

__version__ = "0.3.0"

__all__ = [
    "Task", "read_tasks", "write_tasks", "assign_ids",
    "cmd_add", "cmd_done", "cmd_delete", "cmd_start",
    "cmd_stop", "cmd_annotate", "cmd_modify", "cmd_export",
    "cmd_bulk", "compute_urgency", "execute_command",
    "UrgencyConfig", "DEFAULT_CONFIG",
]
