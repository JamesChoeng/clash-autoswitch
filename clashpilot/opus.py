"""Opus-region whitelist scanning and node eligibility filtering."""

from __future__ import annotations

import json
import time
import urllib.request

from . import config, opus_regions
from .env_config import CLAUDE_TARGET, DELAY_TIMEOUT_MS, GEO_IP_URL, GEO_PROBE_DELAY_S, OPUS_RESCAN_COOLDOWN
from .logutil import log, notify
from .proxy_ctrl import (
    delay,
    fetch_proxies,
    has_active_target_connection,
    list_nodes,
    set_node,
    target_group,
)

_LAST_RESCAN_TS = 0.0

_NAME_COUNTRY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("🇺🇸", "美国", "US-", "-US", "USA", "AMERICA", "洛杉矶", "硅谷", "西雅图", "纽约"), "US"),
    (("🇯🇵", "日本", "JP-", "-JP", "JAPAN", "东京", "大阪"), "JP"),
    (("🇸🇬", "新加坡", "SG-", "-SG", "SINGAPORE"), "SG"),
    (("🇹🇼", "台湾", "TW-", "-TW", "TAIWAN"), "TW"),
    (("🇰🇷", "韩国", "KR-", "-KR", "KOREA", "首尔"), "KR"),
    (("🇬🇧", "英国", "UK-", "-UK", "GB-", "-GB", "BRITAIN", "LONDON"), "GB"),
    (("🇩🇪", "德国", "DE-", "-DE", "GERMANY"), "DE"),
    (("🇫🇷", "法国", "FR-", "-FR", "FRANCE"), "FR"),
    (("🇨🇦", "加拿大", "CA-", "-CA", "CANADA"), "CA"),
    (("🇦🇺", "澳大利亚", "AU-", "-AU", "AUSTRALIA"), "AU"),
    (("🇳🇱", "荷兰", "NL-", "-NL", "NETHERLANDS"), "NL"),
    (("🇮🇳", "印度", "IN-", "-IN", "INDIA"), "IN"),
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


def _country_from_name(node: str) -> str | None:
    upper = node.upper()
    for hints, code in _NAME_COUNTRY_HINTS:
        for hint in hints:
            if hint in node or hint in upper:
                return code
    return None


def _confirmed_geo(meta_value: str | None) -> str | None:
    if not meta_value or meta_value.startswith("~"):
        return None
    return meta_value


def _country_for_node(node: str, prev_meta: dict[str, str]) -> str | None:
    confirmed = _confirmed_geo(prev_meta.get(node))
    if confirmed:
        return confirmed
    return _country_from_name(node)


def _proxy_opener(port: int) -> urllib.request.OpenerDirector:
    proxy = f"http://127.0.0.1:{port}"
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def probe_exit_country(group: str, node: str, port: int) -> str | None:
    """Geo probe via the active selector -- switches the user's node temporarily."""
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


def opus_eligible_light(node: str, country: str | None, regions: frozenset[str]) -> bool:
    if not reaches_claude(node):
        return False
    if country and country not in regions:
        return False
    return True


def _fallback_pool(nodes: list[str]) -> list[str]:
    pool = [n for n in nodes if not _name_likely_blocked(n)]
    return pool if pool else nodes


def _save_whitelist(ok: list[str], meta: dict[str, str]) -> None:
    global _LAST_RESCAN_TS
    _LAST_RESCAN_TS = time.time()
    config.save_opus_whitelist(ok, meta)


def _geo_backfill_pending(ok: list[str], meta: dict[str, str]) -> None:
    """Full geo for nodes that only have name-based country hints, when idle."""
    pending = [n for n in ok if _confirmed_geo(meta.get(n)) is None]
    if not pending or has_active_target_connection():
        return
    regions = config.opus_region_codes()
    proxies = fetch_proxies()
    group = target_group(proxies)
    prev = (proxies.get(group) or {}).get("now")
    port = config.mixed_port()
    log(f"opus geo backfill: {len(pending)} nodes without confirmed exit country")
    try:
        for node in pending:
            country = probe_exit_country(group, node, port)
            if country and country in regions and reaches_claude(node):
                meta[node] = country
                log(f"  geo backfill + {node} ({country})")
            elif country:
                log(f"  geo backfill - {node} ({country} not eligible)")
            if GEO_PROBE_DELAY_S > 0:
                time.sleep(GEO_PROBE_DELAY_S)
    finally:
        if prev:
            set_node(group, prev)
    config.save_opus_whitelist(ok, meta)


def refresh_opus_whitelist_light(nodes: list[str] | None = None) -> list[str]:
    """Build whitelist via per-node delay probes; never switches the active selector."""
    nodes = nodes or list_nodes()
    regions = config.opus_region_codes()
    prev_meta = dict(config.opus_whitelist_meta())
    ok: list[str] = []
    meta: dict[str, str] = {}
    skipped = 0

    log(f"opus light scan: {len(nodes)} nodes | regions={len(regions)} iso codes")
    for i, node in enumerate(nodes, 1):
        if _name_likely_blocked(node):
            skipped += 1
            continue
        country = _country_for_node(node, prev_meta)
        if opus_eligible_light(node, country, regions):
            ok.append(node)
            if confirmed := _confirmed_geo(prev_meta.get(node)):
                meta[node] = confirmed
            elif country:
                meta[node] = country if node in prev_meta else f"~{country}"
            log(f"  + {node}" + (f" ({meta.get(node, '?')})" if node in meta else " (Anthropic ok)"))
        else:
            hint = f" ({country} blocked)" if country else ""
            log(f"  - {node}{hint}")
        if i % 5 == 0 or i == len(nodes):
            notify(f"  ... light whitelist scan {i}/{len(nodes)}")
    _save_whitelist(ok, meta)
    log(
        f"opus light whitelist: {len(ok)}/{len(nodes)} nodes "
        f"({skipped} skipped by name, {len(nodes) - skipped - len(ok)} rejected)"
    )
    _geo_backfill_pending(ok, meta)
    return ok


def refresh_opus_whitelist_incremental(nodes: list[str] | None = None) -> list[str]:
    """Update whitelist after subscription changes: re-verify known nodes, probe only new ones."""
    nodes = nodes or list_nodes()
    regions = config.opus_region_codes()
    prev_wl = set(config.opus_whitelist() or [])
    prev_meta = dict(config.opus_whitelist_meta())
    current = set(nodes)
    ok: list[str] = []
    meta: dict[str, str] = {}
    skipped = 0
    probe_targets: list[str] = []

    for node in nodes:
        if _name_likely_blocked(node):
            skipped += 1
            continue
        if node in prev_wl and node in current:
            country = _country_for_node(node, prev_meta)
            if opus_eligible_light(node, country, regions):
                ok.append(node)
                if confirmed := _confirmed_geo(prev_meta.get(node)):
                    meta[node] = confirmed
                elif country:
                    meta[node] = prev_meta.get(node, f"~{country}")
                continue
        probe_targets.append(node)

    if probe_targets:
        log(f"opus incremental: probing {len(probe_targets)} new/changed nodes")
        for i, node in enumerate(probe_targets, 1):
            country = _country_from_name(node)
            if opus_eligible_light(node, country, regions):
                ok.append(node)
                if country:
                    meta[node] = f"~{country}"
                log(f"  + {node}" + (f" (~{country})" if country else " (Anthropic ok)"))
            else:
                log(f"  - {node}")
            if i % 5 == 0 or i == len(probe_targets):
                notify(f"  ... incremental scan {i}/{len(probe_targets)}")
    else:
        log("opus incremental: subscription node set unchanged, re-verified cached whitelist")

    _save_whitelist(ok, meta)
    log(f"opus incremental whitelist: {len(ok)} nodes ({skipped} skipped by name)")
    _geo_backfill_pending(ok, meta)
    return ok


def _refresh_opus_whitelist_full(nodes: list[str] | None = None) -> list[str]:
    global _LAST_RESCAN_TS
    if has_active_target_connection():
        log("defer full geo whitelist scan: active Cursor/Anthropic connection -> incremental")
        return refresh_opus_whitelist_incremental(nodes)

    nodes = nodes or list_nodes()
    regions = config.opus_region_codes()
    proxies = fetch_proxies()
    group = target_group(proxies)
    prev = (proxies.get(group) or {}).get("now")
    port = config.mixed_port()
    ok: list[str] = []
    meta: dict[str, str] = {}
    skipped = 0

    log(f"opus full geo scan: {len(nodes)} nodes | regions={len(regions)} iso codes")
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
                notify(f"  ... full whitelist scan {i}/{len(nodes)}")
            if GEO_PROBE_DELAY_S > 0:
                time.sleep(GEO_PROBE_DELAY_S)
    finally:
        if prev:
            set_node(group, prev)

    _save_whitelist(ok, meta)
    log(
        f"opus full whitelist: {len(ok)}/{len(nodes)} nodes "
        f"({skipped} skipped by name, {len(nodes) - skipped - len(ok)} rejected)"
    )
    return ok


def refresh_opus_whitelist(
    nodes: list[str] | None = None,
    *,
    full: bool = False,
    incremental: bool = False,
) -> list[str]:
    if full:
        return _refresh_opus_whitelist_full(nodes)
    if incremental:
        return refresh_opus_whitelist_incremental(nodes)
    return refresh_opus_whitelist_light(nodes)


def eligible_nodes(proxies: dict | None = None) -> list[str]:
    nodes = list_nodes(proxies)
    wl = config.opus_whitelist()
    if wl is None:
        return nodes
    wl_set = set(wl)
    filtered = [n for n in nodes if n in wl_set]
    if filtered:
        return filtered
    if not nodes:
        return []
    now = time.time()
    if now - _LAST_RESCAN_TS < OPUS_RESCAN_COOLDOWN:
        pool = _fallback_pool(nodes)
        log(
            f"opus whitelist stale, rescan on cooldown "
            f"({int(now - _LAST_RESCAN_TS)}s/{OPUS_RESCAN_COOLDOWN}s) -> temporary pool ({len(pool)} nodes)"
        )
        return pool
    log("!! opus whitelist empty or stale -> light rescan")
    return refresh_opus_whitelist_light(nodes)


def maybe_refresh_opus_whitelist(force: bool = False) -> None:
    wl = config.opus_whitelist()
    if wl is None:
        return
    if wl and not force:
        notify(f"using saved Opus whitelist ({len(wl)} nodes)")
        return
    notify("scanning nodes for Opus whitelist (light scan, no active-node switching)...")
    refresh_opus_whitelist_light()
