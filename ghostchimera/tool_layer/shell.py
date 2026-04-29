"""
Shell Tool
==========

This module exposes a simple wrapper for running shell commands.  It is used
by skills that need to execute system commands.  The command is executed
with ``/bin/bash`` by default and returns the stdout and stderr combined.

Note: This tool should be used with care.  Executing arbitrary shell
commands can be dangerous.  In a production system you would enforce
permissions and restrict which commands are allowed.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

from ..safety_layer.gating import ensure_authorized


def run_command(command: str | Sequence[str], policy: dict[str, Any] | None = None) -> str:
    """Execute a shell command and return its output.

    This function optionally prefixes commands with the ``rtk`` binary to
    reduce token usage when interacting with large language models.  If
    the environment variable ``GHOSTCHIMERA_USE_RTK`` is set to a truthy
    value (``'1'``, ``'true'``, or ``'yes'``) and the ``rtk`` binary is
    available on the system ``PATH``, the command is executed via
    ``rtk <command>``.  Otherwise it is executed as provided.

    Parameters
    ----------
    command: str
        The shell command to execute.

    Returns
    -------
    str
        The captured output from the command.
    """
    policy = dict(ensure_authorized(policy))
    timeout = int(policy.get("timeout_seconds", 10))
    output_limit = int(policy.get("output_limit_bytes", 20_000))
    cwd_value = policy.get("cwd")
    cwd = Path(str(cwd_value)).expanduser().resolve() if cwd_value else None

    # Determine whether to use RTK based on environment and availability
    use_rtk_env = os.environ.get("GHOSTCHIMERA_USE_RTK", "").lower()
    use_rtk = use_rtk_env in {"1", "true", "yes"}
    rtk_path = shutil.which("rtk")
    argv = _command_to_argv(command)
    if use_rtk and rtk_path:
        argv = [rtk_path, *argv]
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return _limit_output(f"{output}\nTimed out after {timeout} seconds", output_limit)

    output = completed.stdout or ""
    if completed.returncode != 0:
        output = f"{output}\nProcess exited with code {completed.returncode}"
    return _limit_output(output, output_limit)


def _command_to_argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command, posix=os.name != "nt")
    return [str(part) for part in command]


def _limit_output(output: str, limit: int) -> str:
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return output
    truncated = encoded[:limit].decode("utf-8", errors="ignore")
    return f"{truncated}\n[output truncated to {limit} bytes]"
