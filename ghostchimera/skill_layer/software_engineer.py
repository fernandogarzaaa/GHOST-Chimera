"""
Software Engineer Skill
======================

This skill provides basic file and command operations that a software engineer
might perform.  It leverages tools from the ``ghostchimera.tool_layer`` to
interact with the host system.

Supported actions:

- ``write_file`` – create or overwrite a file with specified content.
- ``read_file`` – read the contents of a file.
- ``shell`` – execute a shell command and return its output.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import Skill
from ..tool_layer.file_system import write_file, read_file
from ..tool_layer.shell import run_command


class SoftwareEngineerSkill(Skill):
    name = "software_engineer"
    description = "Operate on the local filesystem and run shell commands"
    actions = ["write_file", "read_file", "shell"]

    def run(self, task: Dict[str, Any]) -> Any:
        action = task.get("action")
        policy = task.get("_ghostchimera_policy")
        if action == "write_file":
            path = task.get("path")
            content = task.get("content", "")
            if not path:
                raise ValueError("'path' is required for write_file task")
            write_file(path, content, policy=policy)
            return f"Wrote {len(content)} bytes to {path}"
        elif action == "read_file":
            path = task.get("path")
            if not path:
                raise ValueError("'path' is required for read_file task")
            return read_file(path, policy=policy)
        elif action == "shell":
            command = task.get("command")
            if not command:
                raise ValueError("'command' is required for shell task")
            return run_command(command, policy=policy)
        else:
            raise ValueError(f"Unsupported action for SoftwareEngineerSkill: {action}")
