"""Node scoring, ranking, and autoswitch decisions."""

from __future__ import annotations

import concurrent.futures as cf
import time

from . import config
from .api import ControllerError, get_json
from .bench import bench_nodes, drop_benched, is_benched
from .env_config import (
    ACTIVE_HOSTS,
    CLAUDE_TARGET,
    MAX_DEFER,
    MAX_WORKERS,
    SWITCH_CONFIRM_ATTEMPTS,
    SWITCH_CONFIRM_CANDIDATES,
    SWITCH_COOLDOWN,
    SWITCH_IMPROVEMENT_PCT,
    SWITCH_SUSTAIN_SECONDS,
    TARGETS,
)
from .health import is_alive
from .logutil import log, notify
from .opus import eligible_nodes
from .proxy_ctrl import delay, fetch_proxies, set_node, target_group

_LAST_SWITCH_TS = 0.0
_DEFER_COUNT = 0
_FASTER_CANDIDATE: str | None = None
_FASTER_SINCE = 0.0


def significantly_faster(candidate_score: float, current_score: float) -> bool:
    """True when candidate latency is at least SWITCH_IMPROVEMENT_PCT% lower."""
    if current_score <= 0:
        return False
    return (current_score - candidate_score) / current_score >= SWITCH_IMPROVEMENT_PCT / 100


def improvement_pct(candidate_score: float, current_score: float) -> int:
    if current_score <= 0:
        return 0
    return int((current_score - candidate_score) / current_score * 100)


def _reset_faster_tracking() -> None:
    global _FASTER_CANDIDATE, _FASTER_SINCE
    _FASTER_CANDIDATE = None
    _FASTER_SINCE = 0.0


def has_active_target_connection() -> bool:
    try:
        conns = get_json("/connections").get("connections") or []
    except ControllerError:
        return False
    for c in conns:
        meta = c.get("metadata") or {}
        host = (meta.get("host") or meta.get("sniffHost") or "").lower()
        if any(k in host for k in ACTIVE_HOSTS):
            return True
    return False


def score(node: str) -> float | None:
    results = [delay(node, u) for u in TARGETS]
    vals = [r for r in results if r is not None]
    if not vals:
        return None
    if CLAUDE_TARGET in TARGETS:
        idx = TARGETS.index(CLAUDE_TARGET)
        if results[idx] is None:
            return None
    penalty = (len(results) - len(vals)) * 600
    return sum(vals) / len(vals) + penalty


def rank_nodes(nodes: list[str] | None = None) -> list[tuple[str, float]]:
    from .proxy_ctrl import list_nodes

    nodes = nodes or list_nodes()
    scored: list[tuple[str, float]] = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for node, s in zip(nodes, pool.map(score, nodes)):
            if s is not None:
                scored.append((node, s))
    scored.sort(key=lambda t: t[1])
    return scored


def do_switch(group: str, node: str) -> bool:
    global _LAST_SWITCH_TS, _DEFER_COUNT
    if set_node(group, node):
        _LAST_SWITCH_TS = time.time()
        _DEFER_COUNT = 0
        _reset_faster_tracking()
        return True
    return False


def confirm_stable(node: str, attempts: int = SWITCH_CONFIRM_ATTEMPTS) -> bool:
    """Re-probe a switch candidate `attempts` times and require *every* probe to
    pass (Anthropic included). One reachable probe at scan time isn't enough --
    this catches nodes that flap, so we don't switch onto something unstable."""
    if attempts <= 0:
        return True
    for _ in range(attempts):
        if score(node) is None:
            return False
    return True


def confirmed_target(ranking: list[tuple[str, float]]) -> tuple[str, float] | None:
    """First node (top-down) that survives `confirm_stable`. Only the top
    SWITCH_CONFIRM_CANDIDATES are re-probed so a fully-flaky scan can't turn into
    a probe storm. Returns None when none of them re-confirm."""
    cap = SWITCH_CONFIRM_CANDIDATES if SWITCH_CONFIRM_CANDIDATES > 0 else len(ranking)
    for node, s in ranking[:cap]:
        if confirm_stable(node):
            return node, s
    return None


def _switch_to_confirmed(group: str, ranking: list[tuple[str, float]]) -> tuple[str, float, bool]:
    """Switch to the best re-confirmed node. Falls back to the top-ranked node
    when none re-confirm (a forced switch still has to land somewhere).
    Returns (node, score, unconfirmed)."""
    confirmed = confirmed_target(ranking)
    node, s = confirmed if confirmed else ranking[0]
    do_switch(group, node)
    return node, s, confirmed is None


def pick_and_switch(group: str | None = None, nodes: list[str] | None = None) -> dict:
    global _DEFER_COUNT, _FASTER_CANDIDATE, _FASTER_SINCE
    proxies = fetch_proxies()
    group = group or target_group(proxies)
    nodes = nodes or eligible_nodes(proxies)
    candidates = drop_benched(nodes)
    cur = (proxies.get(group) or {}).get("now")

    ranking = rank_nodes(candidates)
    if not ranking:
        log("!! no reachable node found this scan")
        return {"action": "none", "reason": "no reachable nodes", "group": group}

    best, best_score = ranking[0]
    cur_score = next((s for n, s in ranking if n == cur), None)
    top = ", ".join(f"{n.split('|')[0]}({int(s)})" for n, s in ranking[:3])
    benched = len(nodes) - len(candidates)
    scan_line = (
        f"scan: {len(ranking)}/{len(candidates)} ok"
        + (f" ({benched} benched)" if benched else "")
        + f" | top: {top}"
    )
    log(scan_line)
    notify(scan_line)

    unconfirmed_note = " (no candidate passed re-check; best effort)"

    if cur is None:
        node, s, unconfirmed = _switch_to_confirmed(group, ranking)
        log(f"no current node -> switch to '{node}' ({int(s)})" + (unconfirmed_note if unconfirmed else ""))
        return {"action": "switched", "from": None, "to": node, "score": int(s), "group": group}

    if cur_score is None:
        if config.opus_whitelist() is not None and cur not in nodes:
            node, s, unconfirmed = _switch_to_confirmed(group, ranking)
            log(f"enforce Opus whitelist: '{cur}' is not an eligible node -> switch to '{node}' ({int(s)})"
                + (unconfirmed_note if unconfirmed else ""))
            return {
                "action": "switched", "from": cur, "to": node,
                "score": int(s), "group": group,
                "reason": "whitelist enforcement",
            }
        if is_benched(cur):
            node, s, unconfirmed = _switch_to_confirmed(group, ranking)
            log(f"current '{cur}' is benched -> switch to '{node}' ({int(s)})"
                + (unconfirmed_note if unconfirmed else ""))
            return {"action": "switched", "from": cur, "to": node, "score": int(s),
                    "group": group, "reason": "benched"}
        if is_alive(cur):
            log(f"keep '{cur}' (didn't rank this scan but still alive)")
            return {"action": "kept", "node": cur, "best": best, "group": group}
        bench_nodes(cur, "confirmed dead at scan")
        node, s, unconfirmed = _switch_to_confirmed(group, ranking)
        log(f"current '{cur}' confirmed dead -> switch to '{node}' ({int(s)})"
            + (unconfirmed_note if unconfirmed else ""))
        return {"action": "switched", "from": cur, "to": node, "score": int(s), "group": group}

    if best != cur and significantly_faster(best_score, cur_score):
        now = time.time()
        if best != _FASTER_CANDIDATE:
            _FASTER_CANDIDATE = best
            _FASTER_SINCE = now
        sustained = now - _FASTER_SINCE
        pct = improvement_pct(best_score, cur_score)
        if sustained < SWITCH_SUSTAIN_SECONDS:
            log(
                f"hold '{cur}'({int(cur_score)}): '{best}'({int(best_score)}) "
                f"{pct}% faster, waiting {int(sustained)}/{SWITCH_SUSTAIN_SECONDS}s sustained"
            )
            return {
                "action": "pending",
                "node": cur,
                "score": int(cur_score),
                "best": best,
                "best_score": int(best_score),
                "improvement_pct": pct,
                "sustained_s": int(sustained),
                "required_s": SWITCH_SUSTAIN_SECONDS,
                "group": group,
            }
        since = time.time() - _LAST_SWITCH_TS
        if since < SWITCH_COOLDOWN:
            log(
                f"hold '{cur}'({int(cur_score)}): '{best}'({int(best_score)}) "
                f"{pct}% faster for {int(sustained)}s "
                f"but within {SWITCH_COOLDOWN}s cooldown ({int(since)}s elapsed)"
            )
            return {
                "action": "cooldown",
                "node": cur,
                "score": int(cur_score),
                "best": best,
                "best_score": int(best_score),
                "group": group,
            }
        if has_active_target_connection() and _DEFER_COUNT < MAX_DEFER:
            _DEFER_COUNT += 1
            log(
                f"defer switch '{cur}'({int(cur_score)}) -> '{best}'({int(best_score)}) "
                f"({_DEFER_COUNT}/{MAX_DEFER}): active Cursor/Anthropic connection in flight"
            )
            return {
                "action": "deferred",
                "node": cur,
                "score": int(cur_score),
                "best": best,
                "best_score": int(best_score),
                "defer_count": _DEFER_COUNT,
                "reason": "active connection",
                "group": group,
            }
        if not confirm_stable(best):
            _DEFER_COUNT = 0
            log(
                f"hold '{cur}'({int(cur_score)}): '{best}'({int(best_score)}) "
                f"failed stability re-check -- not switching"
            )
            return {
                "action": "kept",
                "node": cur,
                "score": int(cur_score),
                "best": best,
                "best_score": int(best_score),
                "group": group,
                "reason": "candidate unstable",
            }
        forced = _DEFER_COUNT >= MAX_DEFER
        do_switch(group, best)
        log(
            f"switch '{cur}'({int(cur_score)}) -> '{best}'({int(best_score)}) "
            f"({pct}% faster, sustained {int(sustained)}s)"
            + (" (forced after max defers)" if forced else "")
        )
        return {
            "action": "switched",
            "from": cur,
            "to": best,
            "from_score": int(cur_score),
            "to_score": int(best_score),
            "forced": forced,
            "group": group,
        }

    _reset_faster_tracking()
    _DEFER_COUNT = 0
    log(
        f"keep '{cur}' ({int(cur_score)}); best '{best}' ({int(best_score)}) "
        f"not {SWITCH_IMPROVEMENT_PCT}%+ faster for {SWITCH_SUSTAIN_SECONDS}s"
    )
    return {
        "action": "kept",
        "node": cur,
        "score": int(cur_score),
        "best": best,
        "best_score": int(best_score),
        "group": group,
    }


def switch_to(node: str) -> str:
    proxies = fetch_proxies()
    group = target_group(proxies)
    nodes = eligible_nodes(proxies)
    if node not in nodes:
        matches = [n for n in nodes if node in n]
        if len(matches) == 1:
            node = matches[0]
        elif matches:
            return f"ambiguous ({len(matches)} matches). Be more specific:\n" + "\n".join(matches[:5])
        else:
            return f"node not found: {node!r}"
    if do_switch(group, node):
        log(f"manual switch -> '{node}'")
        return f"switched {group} -> {node}"
    return f"failed to switch to {node}"


def format_scan(top_n: int = 10, *, all_nodes: bool = False) -> str:
    from .proxy_ctrl import current_mode, current_node, list_nodes

    proxies = fetch_proxies()
    if all_nodes or config.opus_whitelist() is None:
        nodes = list_nodes(proxies)
        pool_label = "all nodes"
    else:
        nodes = eligible_nodes(proxies)
        pool_label = "Opus-eligible nodes"
    ranking = rank_nodes(nodes)
    cur = current_node(proxies=proxies)
    lines = [
        f"mode={current_mode()} group={target_group(proxies)} current={cur}",
        f"scanned {len(nodes)} {pool_label}, {len(ranking)} reachable",
        "",
        f"{'SCORE':>6}  NODE",
        "-" * 60,
    ]
    for name, s in ranking[:top_n]:
        mark = "  *" if name == cur else ""
        lines.append(f"{int(s):>6}  {name}{mark}")
    if not ranking:
        lines.append("(no reachable nodes)")
    elif cur and not any(n == cur for n, _ in ranking[:top_n]):
        lines.append(f"  ... current node '{cur}' not in top {top_n}")
    if ranking:
        lines.append("")
        lines.append("* = current node (scan only — no switch)")
    return "\n".join(lines)
