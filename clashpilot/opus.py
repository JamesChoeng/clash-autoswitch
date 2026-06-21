"""Opus-region whitelist scanning and node eligibility filtering."""

from __future__ import annotations

import json
import time
import urllib.request

from . import config, opus_regions
from .env_config import CLAUDE_TARGET, DELAY_TIMEOUT_MS, GEO_IP_URL, GEO_PROBE_DELAY_S
from .logutil import log, notify
from .proxy_ctrl import (
    delay,
    fetch_proxies,
    list_nodes,
    set_node,
    target_group,
)


def _parse_exit_country(body: str, fmt: str) -> str | None:
    if fmt == "plain":
        code = body.strip().upper()
        return code if len(code) == 2 and code.isalpha() else None
    if fmt == "cf_trace":
        for line in body.splitlines():
            if line.startswith("loc="):
                code = line.split("=", 1)[1].strip().upper()
                return code if len(code) == 2 else None
        return None
    if fmt == "json":
        try:
            data = json.loads(body)
            code = str(data.get("countryCode") or "").strip().upper()
            return code if len(code) == 2 else None
        except (ValueError, TypeError):
            return None
    return None


def _geo_probe_chain() -> list[tuple[str, str]]:
    if GEO_IP_URL:
        fmt = "json" if "json" in GEO_IP_URL else "plain"
        return [(GEO_IP_URL, fmt)]
    return [
        ("https://1.1.1.1/cdn-cgi/trace", "cf_trace"),
        ("http://ip-api.com/json/?fields=countryCode", "json"),
        ("https://ipapi.co/country_code/", "plain"),
    ]


def _name_likely_blocked(node: str) -> bool:
    upper = node.upper()
    return any(hint in node or hint in upper for hint in opus_regions.NAME_BLOCKLIST)


def _proxy_opener(port: int) -> urllib.request.OpenerDirector:
    proxy = f"http://127.0.0.1:{port}"
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def probe_exit_country(group: str, node: str, port: int) -> str | None:
    if not set_node(group, node):
        return None
    time.sleep(0.15)
    opener = _proxy_opener(port)
    headers = {"User-Agent": "clashpilot"}
    for url, fmt in _geo_probe_chain():
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=12) as resp:
                code = _parse_exit_country(resp.read().decode("utf-8", "replace"), fmt)
                if code:
                    return code
        except Exception:  # noqa: BLE001
            continue
    return None


def reaches_claude(node: str, timeout_ms: int = DELAY_TIMEOUT_MS) -> bool:
    return delay(node, CLAUDE_TARGET, timeout_ms) is not None


def opus_eligible(node: str, country: str | None, regions: frozenset[str]) -> bool:
    if not country or country not in regions:
        return False
    return reaches_claude(node)


def refresh_opus_whitelist(nodes: list[str] | None = None) -> list[str]:
    """Probe exit country + Anthropic reachability; keep Opus-region nodes only."""
    nodes = nodes or list_nodes()
    regions = config.opus_region_codes()
    proxies = fetch_proxies()
    group = target_group(proxies)
    prev = (proxies.get(group) or {}).get("now")
    port = config.mixed_port()
    ok: list[str] = []
    meta: dict[str, str] = {}
    skipped = 0

    log(f"opus whitelist scan: {len(nodes)} nodes | regions={len(regions)} iso codes")
    try:
        for i, node in enumerate(nodes, 1):
            if _name_likely_blocked(node):
                skipped += 1
                continue
            country = probe_exit_country(group, node, port)
            if country and opus_eligible(node, country, regions):
                ok.append(node)
                meta[node] = country
                log(f"  + {node} ({country})")
            elif country:
                log(f"  - {node} ({country} not Opus-eligible or Anthropic blocked)")
            else:
                log(f"  - {node} (geo probe failed)")
            if i % 5 == 0 or i == len(nodes):
                notify(f"  ... whitelist scan {i}/{len(nodes)}")
            if GEO_PROBE_DELAY_S > 0:
                time.sleep(GEO_PROBE_DELAY_S)
    finally:
        if prev:
            set_node(group, prev)

    config.save_opus_whitelist(ok, meta)
    log(
        f"opus whitelist: {len(ok)}/{len(nodes)} nodes "
        f"({skipped} skipped by name, {len(nodes) - skipped - len(ok)} rejected)"
    )
    return ok


def eligible_nodes(proxies: dict | None = None) -> list[str]:
    nodes = list_nodes(proxies)
    wl = config.opus_whitelist()
    if wl is None:
        return nodes
    wl_set = set(wl)
    filtered = [n for n in nodes if n in wl_set]
    if filtered:
        return filtered
    if nodes:
        log("!! opus whitelist empty or stale -> rescanning")
        return refresh_opus_whitelist(nodes)
    return []


def maybe_refresh_opus_whitelist(force: bool = False) -> None:
    wl = config.opus_whitelist()
    if wl is None:
        return
    if wl and not force:
        notify(f"using saved Opus whitelist ({len(wl)} nodes)")
        return
    notify("scanning all nodes for Opus whitelist (first run or empty cache)...")
    refresh_opus_whitelist()
