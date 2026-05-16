"""Print a safe local development profile."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dev_env import profile_data


def main() -> None:
    data = profile_data("minimal")
    print(f"profile={data['profile']}")
    print(data["commands"][0])


if __name__ == "__main__":
    main()
