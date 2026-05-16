import json

import pytest

from scripts.dev_env import format_markdown, format_text, profile_data


def test_dev_env_profiles_print_commands_without_installing():
    data = profile_data("gateway")

    assert data["profile"] == "gateway"
    assert "dev,gateway" in data["extras"]
    assert "does not install anything" in data["note"]
    assert "pip install" in format_text(data)
    assert "Dev Environment" in format_markdown(data)
    json.dumps(data)


def test_dev_env_rejects_unknown_profile():
    with pytest.raises(ValueError):
        profile_data("unknown")
