"""Unit tests for multi-subscription merge and settings."""

from __future__ import annotations

import unittest
from unittest import mock

from clashpilot import config
from clashpilot.subscription_merge import merge_subscription_texts, proxy_item_name, split_top_level_sections


SUB_A = """\
proxies:
  - name: node-a
    type: ss
    server: 1.1.1.1
    port: 443
  - name: node-b
    type: ss
    server: 2.2.2.2
    port: 443
proxy-groups:
  - name: pick
    type: select
    proxies:
      - node-a
      - node-b
rules:
  - MATCH,pick
"""

SUB_B = """\
proxies:
  - name: node-b
    type: vmess
    server: 3.3.3.3
    port: 8443
  - name: node-c
    type: ss
    server: 4.4.4.4
    port: 443
proxy-groups:
  - name: other
    type: select
    proxies:
      - node-c
rules:
  - MATCH,other
"""


class MergeSubscriptionTextsTest(unittest.TestCase):
    def test_single_source_passthrough(self) -> None:
        merged = merge_subscription_texts([SUB_A])
        self.assertEqual(merged.strip(), SUB_A.strip())

    def test_merges_proxies_and_expands_selector(self) -> None:
        merged = merge_subscription_texts([SUB_A, SUB_B])
        sections = split_top_level_sections(merged)
        self.assertIn("proxies", sections)
        from clashpilot.subscription_merge import _split_list_items

        items = _split_list_items(sections["proxies"])
        names = [proxy_item_name(item) for item in items]
        self.assertEqual(set(names), {"node-a", "node-b", "node-c", "node-b [#2]"})
        self.assertIn("node-c", sections["proxy-groups"])
        self.assertIn("node-b [#2]", merged)

    def test_duplicate_names_get_source_suffix(self) -> None:
        merged = merge_subscription_texts([SUB_A, SUB_B])
        self.assertIn("node-b [#2]", merged)
        self.assertIn("name: node-a", merged)


class SubscriptionUrlsSettingsTest(unittest.TestCase):
    def test_legacy_single_url(self) -> None:
        with mock.patch.object(config, "get_settings", return_value={"subscription_url": "https://a"}):
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(config.subscription_urls(), ["https://a"])

    def test_multi_url_list(self) -> None:
        with mock.patch.object(
            config,
            "get_settings",
            return_value={"subscription_urls": ["https://a", "https://b"]},
        ):
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(config.subscription_urls(), ["https://a", "https://b"])

    def test_env_subscriptions_csv(self) -> None:
        with mock.patch.object(config, "get_settings", return_value={}):
            with mock.patch.dict(
                "os.environ",
                {"CLASHPILOT_SUBSCRIPTIONS": "https://a, https://b"},
                clear=True,
            ):
                self.assertEqual(config.subscription_urls(), ["https://a", "https://b"])


if __name__ == "__main__":
    unittest.main()
