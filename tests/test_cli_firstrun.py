"""First-run CLI regressions from the round-2 newcomer/poweruser audits."""

from __future__ import annotations

import sys

import pytest

from ghostchimera.control_plane import cli


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(tmp_path / ".ghostchimera"))


# --- newcomer P1-4 (brief: P1-6): `ghost policy` argparse mismatch ---


@pytest.mark.parametrize("argv", [["policy"], ["policy", "list"]])
def test_policy_list_works_from_the_top_level_cli(argv, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ghost", *argv])
    assert cli._main(argv) == 0
    out = capsys.readouterr().out
    assert "strict_factual" in out


def test_policy_set_and_scan_receive_their_own_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ghost", "policy", "set", "coding"])
    assert cli._main(["policy", "set", "coding"]) == 0
    assert "code_review" in capsys.readouterr().out
    argv = ["policy", "scan", "hello world", "--policy", "strict_factual"]
    monkeypatch.setattr(sys, "argv", ["ghost", *argv])
    assert cli._main(argv) == 0
    assert '"policy_id": "strict_factual"' in capsys.readouterr().out


# --- newcomer P1-6 (brief: P1-8): subcommand typos must not run as tasks ---


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("dmeo", "demo"), ("polcy", "policy"), ("doctr", "doctor"), ("stup", "setup"), ("mpc", "mcp")],
)
def test_subcommand_typo_suggests_and_exits_2(typed, expected, monkeypatch, capsys) -> None:
    ran = []
    monkeypatch.setattr(cli, "_run_ask_cli", lambda args: ran.append(args) or 0)
    monkeypatch.setattr(sys, "argv", ["ghost", typed])
    assert cli._main([typed]) == 2
    err = capsys.readouterr().err
    assert f"unknown command '{typed}'" in err
    assert f"Did you mean '{expected}'?" in err
    assert ran == [], "a typo must not be executed as an objective"


def test_typo_with_flags_is_still_caught(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ghost", "dmeo", "--json"])
    assert cli._main(["dmeo", "--json"]) == 2
    assert "Did you mean 'demo'?" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["summarize"], ["hello"], ["use"], ["dmeo the repo"], ["fix", "the", "tests"], ["test", "my", "code"]],
)
def test_objectives_that_are_not_typos_still_run_as_ask(argv, monkeypatch) -> None:
    ran = []
    monkeypatch.setattr(cli, "_run_ask_cli", lambda args: ran.append(" ".join(args.objective)) or 0)
    monkeypatch.setattr(sys, "argv", ["ghost", *argv])
    assert cli._main(argv) == 0
    assert ran == [" ".join(argv)]


# --- newcomer P1-5 (brief: P1-7): Ctrl-C prints one line, exit 130 ---


def test_keyboard_interrupt_exits_130_with_one_line(monkeypatch, capsys) -> None:
    def _interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run_ask_cli", _interrupt)
    monkeypatch.setattr(sys, "argv", ["ghost", "summarize", "my", "workspace"])
    assert cli._main(["summarize", "my", "workspace"]) == 130
    captured = capsys.readouterr()
    assert captured.err.strip() == "Interrupted."
    assert "Traceback" not in captured.err + captured.out


def test_sigint_in_a_real_process_exits_130_without_traceback(tmp_path) -> None:
    import signal
    import subprocess
    import time

    if sys.platform == "win32":
        pytest.skip("POSIX signal delivery")
    script = (
        "import sys, time\n"
        "from ghostchimera.control_plane import cli\n"
        "def _slow(args):\n"
        "    print('ready', flush=True)\n"
        "    time.sleep(30)\n"
        "    return 0\n"
        "cli._run_ask_cli = _slow\n"
        "sys.exit(cli._main(['summarize', 'this']))\n"
    )
    env = {**__import__("os").environ, "HOME": str(tmp_path), "GHOSTCHIMERA_STATE_DIR": str(tmp_path / ".gc")}
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        time.sleep(0.2)
        proc.send_signal(signal.SIGINT)
        _out, err = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 130
    assert "Traceback" not in err
    assert err.strip().splitlines()[-1] == "Interrupted."


# --- newcomer P1-8 (brief: P1-10): UnicodeEncodeError on a cp1252 stdout ---


def test_non_utf8_stdout_does_not_crash_on_model_unicode(tmp_path) -> None:
    import os
    import subprocess

    script = (
        "import sys\n"
        "from ghostchimera.control_plane import cli\n"
        "def _reply(args):\n"
        "    print('Nemotron says: non\\u2011breaking \\u2192 done')\n"
        "    return 0\n"
        "cli._run_ask_cli = _reply\n"
        "sys.exit(cli._main(['what', 'is', 'nemotron']))\n"
    )
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "HOME": str(tmp_path),
        "GHOSTCHIMERA_STATE_DIR": str(tmp_path / ".gc"),
    }
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("cp1252", "replace")
    assert b"UnicodeEncodeError" not in proc.stderr
    assert proc.stdout.decode("cp1252").startswith("Nemotron says: non?breaking")
