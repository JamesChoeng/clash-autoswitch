"""Unit tests for Opus whitelist scanning (no network)."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from clashpilot import opus


class CountryFromNameTest(unittest.TestCase):
    def test_us_emoji_and_keyword(self) -> None:
        self.assertEqual(opus._country_from_name("🇺🇸美国01|流媒体"), "US")
        self.assertEqual(opus._country_from_name("Los Angeles US-01"), "US")

    def test_jp_and_sg(self) -> None:
        self.assertEqual(opus._country_from_name("🇯🇵日本高速05"), "JP")
        self.assertEqual(opus._country_from_name("SG-Singapore-01"), "SG")

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(opus._country_from_name(" mystery-node "))


class EligibleNodesCooldownTest(unittest.TestCase):
    def setUp(self) -> None:
        opus._LAST_RESCAN_TS = time.time()

    @patch("clashpilot.opus.list_nodes", return_value=["node-a", "node-b", "HK-01"])
    @patch.object(opus.config, "opus_whitelist", return_value=["stale-node"])
    def test_stale_whitelist_uses_fallback_pool_on_cooldown(self, _wl, _nodes) -> None:
        pool = opus.eligible_nodes({})
        self.assertIn("node-a", pool)
        self.assertIn("node-b", pool)
        self.assertNotIn("HK-01", pool)

    @patch("clashpilot.opus.refresh_opus_whitelist_light", return_value=["node-a"])
    @patch("clashpilot.opus.list_nodes", return_value=["node-a"])
    @patch.object(opus.config, "opus_whitelist", return_value=[])
    def test_empty_whitelist_triggers_light_rescan_after_cooldown(
        self, _wl, _nodes, mock_light
    ) -> None:
        opus._LAST_RESCAN_TS = 0.0
        result = opus.eligible_nodes({})
        self.assertEqual(result, ["node-a"])
        mock_light.assert_called_once()


class RefreshWhitelistModesTest(unittest.TestCase):
    @patch("clashpilot.opus._refresh_opus_whitelist_full", return_value=["full"])
    @patch("clashpilot.opus.refresh_opus_whitelist_light", return_value=["light"])
    def test_default_is_light(self, mock_light, mock_full) -> None:
        self.assertEqual(opus.refresh_opus_whitelist(), ["light"])
        mock_light.assert_called_once()
        mock_full.assert_not_called()

    @patch("clashpilot.opus._refresh_opus_whitelist_full", return_value=["full"])
    @patch("clashpilot.opus.refresh_opus_whitelist_light", return_value=["light"])
    def test_full_flag_uses_geo_scan(self, _mock_light, mock_full) -> None:
        self.assertEqual(opus.refresh_opus_whitelist(full=True), ["full"])
        mock_full.assert_called_once()


if __name__ == "__main__":
    unittest.main()
