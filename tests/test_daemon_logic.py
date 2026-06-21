"""Unit tests for node-selection and health logic (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from clashpilot import config, daemon, health, selector


class OpusFilteringDefaultsTest(unittest.TestCase):
    def test_filtering_on_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(config, "get_settings", return_value={}):
                self.assertTrue(config.opus_filtering_enabled())
                self.assertEqual(config.opus_whitelist(), [])


class ScoreAnthropicRequiredTest(unittest.TestCase):
    @patch("clashpilot.selector.delay")
    def test_rejects_node_when_anthropic_unreachable(self, mock_delay) -> None:
        def side_effect(node: str, url: str, timeout_ms: int = 0, expected: str | None = None):
            if "anthropic" in url:
                return None
            return 100

        mock_delay.side_effect = side_effect
        self.assertIsNone(selector.score("test-node"))

    @patch("clashpilot.selector.delay", return_value=100)
    def test_accepts_node_when_all_targets_ok(self, _mock_delay) -> None:
        score = selector.score("test-node")
        self.assertIsNotNone(score)
        self.assertEqual(score, 100.0)


class HealthThresholdTest(unittest.TestCase):
    @patch.object(health, "is_alive", return_value=True)
    @patch.object(health, "anthropic_reachable", return_value=False)
    def test_anthropic_failure_uses_fast_threshold(self, _anthropic, _alive) -> None:
        unhealthy, threshold = health.health_fail_threshold("node-a")
        self.assertTrue(unhealthy)
        self.assertEqual(threshold, health.ANTHROPIC_FAIL_THRESHOLD)

    @patch.object(health, "is_alive", return_value=False)
    @patch.object(health, "anthropic_reachable", return_value=True)
    def test_general_failure_uses_default_threshold(self, _anthropic, _alive) -> None:
        unhealthy, threshold = health.health_fail_threshold("node-a")
        self.assertTrue(unhealthy)
        self.assertEqual(threshold, health.HEALTH_FAIL_THRESHOLD)


class DaemonReexportsTest(unittest.TestCase):
    def test_backward_compatible_aliases(self) -> None:
        self.assertIs(daemon._health_fail_threshold, health.health_fail_threshold)
        self.assertIs(daemon.score, selector.score)
        self.assertIs(daemon.format_scan, selector.format_scan)


class MacOSServiceTunTest(unittest.TestCase):
    @patch.object(config, "set_tun_enabled")
    @patch.object(config, "get_settings", return_value={})
    @patch.object(config, "_env_bool", return_value=None)
    def test_enables_tun_on_first_macos_install(self, _env, _settings, set_tun) -> None:
        with patch.object(config.sys, "platform", "darwin"):
            self.assertTrue(config.ensure_macos_service_tun())
        set_tun.assert_called_once_with(True)

    @patch.object(config, "set_tun_enabled")
    @patch.object(config, "get_settings", return_value={"tun_enabled": False})
    @patch.object(config, "_env_bool", return_value=None)
    def test_skips_when_already_configured(self, _env, _settings, set_tun) -> None:
        with patch.object(config.sys, "platform", "darwin"):
            self.assertFalse(config.ensure_macos_service_tun())
        set_tun.assert_not_called()


class FormatScanTest(unittest.TestCase):
    @patch("clashpilot.selector.rank_nodes", return_value=[("node-a", 120.0), ("node-b", 200.0)])
    @patch("clashpilot.selector.eligible_nodes", return_value=["node-a", "node-b"])
    @patch("clashpilot.selector.fetch_proxies", return_value={})
    @patch("clashpilot.selector.target_group", return_value="AUTO")
    @patch("clashpilot.proxy_ctrl.current_node", return_value="node-a")
    @patch("clashpilot.proxy_ctrl.current_mode", return_value="rule")
    @patch.object(config, "opus_whitelist", return_value=["node-a"])
    def test_marks_current_node(self, *_mocks) -> None:
        text = selector.format_scan(top_n=5)
        self.assertIn("*", text)
        self.assertIn("node-a  *", text)
        self.assertIn("no switch", text)


if __name__ == "__main__":
    unittest.main()
