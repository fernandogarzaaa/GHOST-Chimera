"""Preview production guardrail validation with fixture values."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_config import validate_config


def main() -> None:
    result = validate_config(
        {
            "GHOSTCHIMERA_DEPLOYMENT_MODE": "production",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "0",
            "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN": "demo-token-for-local-docs",
            "VULTR_INFERENCE_API_KEY": "vultr-demo-key",
            "VULTR_INFERENCE_MODEL": "llama-demo",
            "VULTR_INFERENCE_BASE_URL": "https://api.vultrinference.com/v1",
        },
        production_mode=True,
    )
    print(f"production_ready={result['valid']}")


if __name__ == "__main__":
    main()
