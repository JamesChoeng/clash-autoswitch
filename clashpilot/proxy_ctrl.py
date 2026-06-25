"""Mihomo external-controller reads and node delay probes."""

from __future__ import annotations

import json
import urllib.parse

from .api import ControllerError, ControllerUnreachable, get_json, request
from .env_config import (
    ACTIVE_HOSTS,
    CLAUDE_EXPECTED,
    CLAUDE_TARGET,
    DELAY_EXPECTED,
    DELAY_TIMEOUT_MS,
    GROUP_TYPES,
    INFO_KEYWORDS,
)


def fetch_proxies() -> dict:
    """One /proxies snapshot. Reuse across a decision to avoid redundant calls."""
    return get_json("/proxies")["proxies"]


def list_nodes(proxies: dict | None = None) -> list[str]:
    data = proxies if proxies is not None else fetch_proxies()
    out = []
    for name, info in data.items():
        if info.get("type") in GROUP_TYPES or "all" in info:
            continue
        if any(k in name for k in INFO_KEYWORDS):
            continue
        out.append(name)
    return sorted(out)


def current_mode() -> str:
    try:
        return get_json("/configs").get("mode", "rule").lower()
    except ControllerError:
        return "rule"


def target_group(proxies: dict | None = None) -> str:
    if current_mode() == "global":
        return "GLOBAL"
    proxies = proxies if proxies is not None else fetch_proxies()
    best, best_n = "GLOBAL", -1
    for name, info in proxies.items():
        if info.get("type") == "Selector" and name != "GLOBAL":
            n = len(info.get("all", []))
            if n > best_n:
                best, best_n = name, n
    return best


def current_node(group: str | None = None, proxies: dict | None = None) -> str | None:
    """Active node for `group`, or None if the group simply has no selection.

    Raises ControllerUnreachable if the controller can't be reached -- callers
    must treat that as "unknown", NOT as "node is dead".
    """
    if proxies is not None:
        group = group or target_group(proxies)
        return (proxies.get(group) or {}).get("now")
    group = group or target_group()
    try:
        return get_json(f"/proxies/{urllib.parse.quote(group, safe='')}").get("now")
    except ControllerUnreachable:
        raise
    except ControllerError:
        return None


def current_node_chain(group: str | None = None, proxies: dict | None = None) -> list[str]:
    """Selection chain from the target group to the final proxy node."""
    proxies = proxies if proxies is not None else fetch_proxies()
    group = group or target_group(proxies)
    node = (proxies.get(group) or {}).get("now")
    chain = []
    seen = set()
    while node and node not in seen:
        chain.append(node)
        seen.add(node)
        info = proxies.get(node) or {}
        if info.get("type") not in GROUP_TYPES and "all" not in info:
            break
        node = info.get("now")
    return chain


def set_node(group: str, node: str) -> bool:
    try:
        status, _ = request(
            "PUT",
            f"/proxies/{urllib.parse.quote(group, safe='')}",
            body=json.dumps({"name": node}),
        )
    except ControllerError:
        return False
    return status in (204, 200)


def _connection_targets(conn: dict) -> str:
    meta = conn.get("metadata") or {}
    parts = [
        meta.get("host") or "",
        meta.get("sniffHost") or "",
        meta.get("destinationIP") or "",
        meta.get("destinationPort") or "",
        conn.get("rule") or "",
    ]
    chains = conn.get("chains") or []
    if isinstance(chains, list):
        parts.extend(str(c) for c in chains)
    return " ".join(str(p) for p in parts if p).lower()


def has_active_target_connection() -> bool:
    """True when mihomo has in-flight traffic to Cursor or Anthropic endpoints."""
    try:
        conns = get_json("/connections").get("connections") or []
    except ControllerError:
        return False
    for c in conns:
        blob = _connection_targets(c)
        if any(k in blob for k in ACTIVE_HOSTS):
            return True
    return False


def delay(
    node: str,
    url: str,
    timeout_ms: int = DELAY_TIMEOUT_MS,
    expected: str | None = None,
) -> int | None:
    if expected is None:
        expected = CLAUDE_EXPECTED if url == CLAUDE_TARGET else DELAY_EXPECTED
    q = urllib.parse.urlencode({"url": url, "timeout": timeout_ms, "expected": expected})
    path = f"/proxies/{urllib.parse.quote(node, safe='')}/delay?{q}"
    try:
        status, body = request("GET", path)
        if status != 200:
            return None
        return int(json.loads(body).get("delay") or 0) or None
    except Exception:  # noqa: BLE001
        return None
