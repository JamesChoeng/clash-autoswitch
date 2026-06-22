"""Environment-overridable tuning knobs for probes, health checks, and switching."""

from __future__ import annotations

import os

DEFAULT_TARGETS = (
    "https://api2.cursor.sh",
    "https://api.anthropic.com/v1/messages",
)

INFO_KEYWORDS = ("流量", "剩余", "套餐", "到期", "expire", "重置", "官网", "订阅", "GB", "购买", "续费")
GROUP_TYPES = {
    "Selector", "URLTest", "Fallback", "LoadBalance", "Relay",
    "Direct", "Reject", "RejectDrop", "Compatible", "Pass", "Dns",
}


def env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


TARGETS = [t.strip() for t in env_str("CLASHPILOT_TARGETS", "").split(",") if t.strip()] or list(DEFAULT_TARGETS)
CLAUDE_TARGET = env_str("CLASHPILOT_CLAUDE_TARGET", "https://api.anthropic.com/v1/messages")

DELAY_TIMEOUT_MS = env_int("CLASHPILOT_DELAY_TIMEOUT_MS", 4000)
HEALTH_TIMEOUT_MS = env_int("CLASHPILOT_HEALTH_TIMEOUT_MS", 2500)
DELAY_EXPECTED = env_str("CLASHPILOT_DELAY_EXPECTED", "200-428/430-501/505-599")
CLAUDE_EXPECTED = env_str("CLASHPILOT_CLAUDE_EXPECTED", "200-402/404-428/430-450/452-501/505-599")

FULL_SCAN_INTERVAL = env_int("CLASHPILOT_FULL_SCAN_INTERVAL", 180)
HEALTH_INTERVAL = env_int("CLASHPILOT_HEALTH_INTERVAL", 15)
HEALTH_RETRIES = env_int("CLASHPILOT_HEALTH_RETRIES", 3)
HEALTH_FAIL_THRESHOLD = env_int("CLASHPILOT_HEALTH_FAIL_THRESHOLD", 3)
ANTHROPIC_FAIL_THRESHOLD = env_int("CLASHPILOT_ANTHROPIC_FAIL_THRESHOLD", 2)
# Consecutive Anthropic failovers (no healthy round in between) that signal an
# upstream/Anthropic-wide outage rather than a bad node. Past this, hold the
# current node instead of benching + jumping through the whole pool. 0 disables.
ANTHROPIC_OUTAGE_FAILOVERS = env_int("CLASHPILOT_ANTHROPIC_OUTAGE_FAILOVERS", 3)
SWITCH_TOLERANCE_MS = env_int("CLASHPILOT_SWITCH_TOLERANCE_MS", 150)
MAX_WORKERS = env_int("CLASHPILOT_MAX_WORKERS", 10)
SWITCH_COOLDOWN = env_int("CLASHPILOT_SWITCH_COOLDOWN", 60)
MAX_DEFER = env_int("CLASHPILOT_MAX_DEFER", 5)
LOG_MAX_BYTES = env_int("CLASHPILOT_LOG_MAX_BYTES", 1_000_000)
SUB_REFRESH_INTERVAL = env_int("CLASHPILOT_SUB_REFRESH_INTERVAL", 21600)
NODE_BENCH_SECONDS = env_int("CLASHPILOT_NODE_BENCH_SECONDS", 600)

GEO_IP_URL = env_str("CLASHPILOT_GEO_IP_URL", "")
GEO_PROBE_DELAY_S = env_int("CLASHPILOT_GEO_PROBE_DELAY_MS", 350) / 1000.0

ACTIVE_HOSTS = ("cursor.sh", "cursor.com", "anthropic")
