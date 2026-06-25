"""Node liveness probes against Cursor + Anthropic targets."""

from __future__ import annotations

import concurrent.futures as cf

from . import config
from .env_config import (
    ANTHROPIC_FAIL_THRESHOLD,
    CLAUDE_TARGET,
    DELAY_TIMEOUT_MS,
    HEALTH_FAIL_THRESHOLD,
    HEALTH_RETRIES,
    HEALTH_TIMEOUT_MS,
    HEALTH_WINDOW_FAILS,
    HEALTH_WINDOW_SIZE,
    TARGETS,
)
from .proxy_ctrl import delay

_HEALTH_WINDOW: list[bool] = []


def reset_health_window() -> None:
    global _HEALTH_WINDOW
    _HEALTH_WINDOW = []


def health_window_snapshot() -> tuple[int, int, int]:
    """Return (rounds_recorded, failures, window_fail_threshold)."""
    failures = sum(1 for ok in _HEALTH_WINDOW if not ok)
    return len(_HEALTH_WINDOW), failures, HEALTH_WINDOW_FAILS


def health_window_update(healthy_round: bool) -> bool:
    """Record one health round; True when the sliding window says failover."""
    global _HEALTH_WINDOW
    _HEALTH_WINDOW.append(healthy_round)
    if len(_HEALTH_WINDOW) > HEALTH_WINDOW_SIZE:
        _HEALTH_WINDOW.pop(0)
    failures = sum(1 for ok in _HEALTH_WINDOW if not ok)
    return failures >= HEALTH_WINDOW_FAILS


def anthropic_reachable(node: str, timeout_ms: int = HEALTH_TIMEOUT_MS) -> bool:
    if CLAUDE_TARGET not in TARGETS:
        return True
    for _ in range(HEALTH_RETRIES):
        if delay(node, CLAUDE_TARGET, timeout_ms) is not None:
            return True
    return False


def is_alive(node: str) -> bool:
    """Liveness check: all targets must pass; Anthropic is always mandatory."""
    targets = TARGETS
    if config.opus_whitelist() is not None:
        targets = [CLAUDE_TARGET]
    for _ in range(HEALTH_RETRIES):
        with cf.ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
            results = list(pool.map(lambda u: delay(node, u, HEALTH_TIMEOUT_MS), targets))
        if all(r is not None for r in results):
            return True
    return False


def health_fail_threshold(cur: str | None) -> tuple[bool, int]:
    """Return (unhealthy, consecutive-fail threshold) for the current node."""
    if cur is None:
        return True, HEALTH_FAIL_THRESHOLD
    if CLAUDE_TARGET in TARGETS and not anthropic_reachable(cur):
        return True, ANTHROPIC_FAIL_THRESHOLD
    if not is_alive(cur):
        return True, HEALTH_FAIL_THRESHOLD
    return False, 0


def node_latency(node: str, timeout_ms: int = DELAY_TIMEOUT_MS) -> dict:
    with cf.ThreadPoolExecutor(max_workers=max(1, len(TARGETS))) as pool:
        delays = list(pool.map(lambda url: delay(node, url, timeout_ms), TARGETS))
    reachable = [d for d in delays if d is not None]
    avg = int(sum(reachable) / len(reachable)) if reachable else None
    return {
        "average": avg,
        "reachable": len(reachable),
        "total": len(TARGETS),
        "targets": list(zip(TARGETS, delays)),
    }
