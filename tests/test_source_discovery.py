"""Tests for external source discovery policy."""

from __future__ import annotations

import unittest

from ghostchimera.integrations.source_discovery import SourceCandidate, filter_allowed_sources


class SourceDiscoveryTests(unittest.TestCase):
    def test_filter_allowed_sources_blocks_unknown_license_for_training(self) -> None:
        candidates = [
            SourceCandidate(url="https://github.com/example/mit", kind="github", license="MIT", commit="abc"),
            SourceCandidate(url="https://github.com/example/unknown", kind="github", license="", commit="def"),
        ]

        allowed = filter_allowed_sources(candidates, intended_use="fine_tuning")

        self.assertEqual([item.url for item in allowed], ["https://github.com/example/mit"])


if __name__ == "__main__":
    unittest.main()
