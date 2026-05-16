"""Generate a test scaffold preview for a tiny in-memory-style source file."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_test_scaffold import analyze_source_file, generate_test_scaffold


def main() -> None:
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "sample.py"
        source.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        scaffold = generate_test_scaffold(analyze_source_file(source), source)
        print(scaffold.splitlines()[0])
        print("test_add" in scaffold)


if __name__ == "__main__":
    main()
