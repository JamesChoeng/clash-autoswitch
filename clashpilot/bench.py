"""Temporary relay/node benching after probe failures."""

from __future__ import annotations

import re
import time

from . import config
from .env_config import NODE_BENCH_SECONDS
from .logutil import log

_BENCH_UNTIL: dict[str, float] = {}
_NODE_SERVER_CACHE: tuple[float, dict[str, str]] = (0.0, {})


def _flow_value(line: str, key: str) -> str | None:
    m = re.search(rf"(?:^|[,{{]\s*){re.escape(key)}:\s*('[^']*'|\"[^\"]*\"|[^,}}]+)", line)
    if not m:
        return None
    val = m.group(1).strip().strip("'\"").strip()
    return val or None


def _node_servers() -> dict[str, str]:
    global _NODE_SERVER_CACHE
    try:
        mtime = config.CONFIG_FILE.stat().st_mtime
    except OSError:
        return {}
    if _NODE_SERVER_CACHE[0] == mtime and _NODE_SERVER_CACHE[1]:
        return _NODE_SERVER_CACHE[1]
    mapping: dict[str, str] = {}
    try:
        in_proxies = False
        for raw in config.CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if re.match(r"^[A-Za-z0-9_.-]+:", raw) and not raw[:1].isspace():
                in_proxies = raw.startswith("proxies:")
                continue
            if not in_proxies or not stripped.startswith("-"):
                continue
            name = _flow_value(stripped, "name")
            server = _flow_value(stripped, "server")
            if name and server:
                mapping[name] = server
    except OSError:
        return {}
    _NODE_SERVER_CACHE = (mtime, mapping)
    return mapping


def bench_nodes(node: str, reason: str = "") -> int:
    """Bench `node` and every sibling sharing its relay server for NODE_BENCH_SECONDS."""
    if NODE_BENCH_SECONDS <= 0 or not node:
        return 0
    until = time.time() + NODE_BENCH_SECONDS
    servers = _node_servers()
    server = servers.get(node)
    targets = {node}
    if server:
        targets |= {n for n, s in servers.items() if s == server}
    for n in targets:
        _BENCH_UNTIL[n] = until
    where = f" (relay {server}, {len(targets)} nodes)" if server else ""
    log(f"bench '{node}'{where} for {NODE_BENCH_SECONDS}s"
        + (f": {reason}" if reason else ""))
    return len(targets)


def is_benched(node: str) -> bool:
    until = _BENCH_UNTIL.get(node)
    if until is None:
        return False
    if time.time() >= until:
        _BENCH_UNTIL.pop(node, None)
        return False
    return True


def drop_benched(nodes: list[str]) -> list[str]:
    """Filter benched nodes, but never return empty if there were candidates."""
    active = [n for n in nodes if not is_benched(n)]
    return active if active else nodes
