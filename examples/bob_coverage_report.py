"""Run the Bob coverage reporter and print a compact summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.coverage_report import analyze_coverage


def main() -> None:
    data = analyze_coverage()
    print(f"modules={data['total_modules']}")
    print(f"coverage_ratio={data['coverage_ratio']:.1%}")


if __name__ == "__main__":
    main()
