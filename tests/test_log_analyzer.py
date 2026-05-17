import json
import subprocess
import sys

from scripts.analyze_logs import DEMO_LOG_LINES, analyze_lines, format_markdown, format_text


def test_log_analyzer_counts_levels_and_repeated_messages():
    data = analyze_lines(
        [
            "app.core: INFO started",
            "app.core: WARNING retrying",
            "app.core: WARNING retrying",
            "app.worker: ERROR failed",
        ]
    )

    assert data["levels"]["INFO"] == 1
    assert data["levels"]["WARNING"] == 2
    assert data["levels"]["ERROR"] == 1
    assert data["repeated_messages"]
    assert "Investigate ERROR" in " ".join(data["suggestions"])
    assert "Log Analysis" in format_text(data)
    assert "# Log Analysis" in format_markdown(data)


def test_log_analyzer_demo_mode_outputs_json():
    completed = subprocess.run(
        [sys.executable, "scripts/analyze_logs.py", "--demo", "--format", "json"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["line_count"] == len(DEMO_LOG_LINES)
    assert payload["levels"]["INFO"] == 2
    assert payload["levels"]["WARNING"] == 1
