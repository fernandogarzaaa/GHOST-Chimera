"""Tests for optional GitHub console auth helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ghostchimera.integrations import github_client


class GitHubClientAuthTests(unittest.TestCase):
    def test_oauth_client_id_prefers_ghostchimera_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"GHOSTCHIMERA_GITHUB_CLIENT_ID": "ghost-client", "GITHUB_CLIENT_ID": "generic-client"},
            clear=False,
        ):
            self.assertEqual(github_client.github_oauth_client_id(), "ghost-client")

    def test_start_device_flow_maps_github_response(self) -> None:
        with patch.object(
            github_client,
            "_post_form_json",
            return_value={
                "device_code": "device",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
        ) as post:
            result = github_client.start_device_flow(client_id="client", scope="read:user")

        self.assertEqual(result.user_code, "ABCD-EFGH")
        self.assertEqual(result.verification_uri, "https://github.com/login/device")
        post.assert_called_once_with(
            github_client.GITHUB_DEVICE_CODE_URL,
            {"client_id": "client", "scope": "read:user"},
        )

    def test_poll_device_flow_uses_device_grant(self) -> None:
        with patch.object(github_client, "_post_form_json", return_value={"access_token": "token"}) as post:
            result = github_client.poll_device_flow(client_id="client", device_code="device")

        self.assertEqual(result["access_token"], "token")
        post.assert_called_once()
        payload = post.call_args.args[1]
        self.assertEqual(payload["client_id"], "client")
        self.assertEqual(payload["device_code"], "device")
        self.assertEqual(payload["grant_type"], "urn:ietf:params:oauth:grant-type:device_code")


if __name__ == "__main__":
    unittest.main()
