import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_examples_smoke_run_without_network():
    examples = [
        ROOT / "examples" / "basic_config.py",
        ROOT / "examples" / "production_guardrails.py",
        ROOT / "examples" / "bob_coverage_report.py",
        ROOT / "examples" / "test_scaffold_preview.py",
    ]

    for example in examples:
        result = subprocess.run([sys.executable, str(example)], cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()
