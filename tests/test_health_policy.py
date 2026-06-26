"""Tests for health sliding window and switch policy."""

from __future__ import annotations

import unittest

from clashpilot import health
from clashpilot.switch_policy import SwitchContext, decide


class HealthFailoverTest(unittest.TestCase):
    def setUp(self) -> None:
        health.reset_health_failures()

    def test_failover_after_threshold_confirmed_fails(self) -> None:
        threshold = 2
        self.assertFalse(health.health_failover_update(True, threshold))
        self.assertTrue(health.health_failover_update(True, threshold))

    def test_success_resets_consecutive_fails(self) -> None:
        health.health_failover_update(True, 2)
        self.assertFalse(health.health_failover_update(False, 2))
        self.assertEqual(health.health_fail_snapshot(), 0)


class SwitchPolicyTest(unittest.TestCase):
    def test_keeps_when_not_faster(self) -> None:
        ctx = SwitchContext(
            group="AUTO",
            cur="node-a",
            cur_score=100.0,
            best="node-b",
            best_score=90.0,
            ranking=[("node-b", 90.0), ("node-a", 100.0)],
            nodes=["node-a", "node-b"],
            last_switch_ts=0.0,
            defer_count=0,
            faster_candidate=None,
            faster_since=0.0,
        )
        decision = decide(ctx)
        self.assertEqual(decision.action, "kept")

    def test_pending_when_faster_but_not_sustained(self) -> None:
        ctx = SwitchContext(
            group="AUTO",
            cur="node-a",
            cur_score=100.0,
            best="node-b",
            best_score=60.0,
            ranking=[("node-b", 60.0), ("node-a", 100.0)],
            nodes=["node-a", "node-b"],
            last_switch_ts=0.0,
            defer_count=0,
            faster_candidate=None,
            faster_since=0.0,
        )
        decision = decide(ctx)
        self.assertEqual(decision.action, "pending")


class ConfigLastSwitchTest(unittest.TestCase):
    def test_save_and_load_last_switch(self) -> None:
        import unittest.mock as mock

        from clashpilot import config

        saved: dict = {}

        def fake_get() -> dict:
            return dict(saved)

        def fake_save(data: dict) -> None:
            saved.clear()
            saved.update(data)

        with mock.patch.object(config, "get_settings", side_effect=fake_get), mock.patch.object(
            config, "save_settings", side_effect=fake_save
        ):
            config.save_last_switch("node-a", "node-b", "optimization", forced=True)
            last = config.last_switch()
        self.assertEqual(last["from"], "node-a")
        self.assertEqual(last["to"], "node-b")
        self.assertEqual(last["reason"], "optimization")
        self.assertTrue(last["forced"])


if __name__ == "__main__":
    unittest.main()
