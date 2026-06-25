"""Node scoring, ranking, and autoswitch decisions."""

from __future__ import annotations

import concurrent.futures as cf
import time

from . import config
from .bench import drop_benched
from .env_config import (
    CLAUDE_TARGET,
    IDLE_SCAN,
    MAX_DEFER,
    MAX_WORKERS,
    SCORE_EMA_ALPHA,
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
from .proxy_ctrl import delay, fetch_proxies, has_active_target_connection, set_node, target_group
from .switch_policy import (
    SwitchContext,
    SwitchDecision,
    decide,
    improvement_pct,
    should_defer_switch,
    significantly_faster,
)

_LAST_SWITCH_TS = 0.0
_DEFER_COUNT = 0
_FASTER_CANDIDATE: str | None = None
_FASTER_SINCE = 0.0
_SCORE_EMA: dict[str, float] = {}


def _reset_faster_tracking() -> None:
    global _FASTER_CANDIDATE, _FASTER_SINCE
    _FASTER_CANDIDATE = None
    _FASTER_SINCE = 0.0


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


def _smooth_score(node: str, raw: float) -> float:
    alpha = SCORE_EMA_ALPHA / 100.0
    if alpha <= 0:
        return raw
    prev = _SCORE_EMA.get(node)
    if prev is None:
        _SCORE_EMA[node] = raw
        return raw
    smoothed = alpha * raw + (1.0 - alpha) * prev
    _SCORE_EMA[node] = smoothed
    return smoothed


def rank_nodes(nodes: list[str] | None = None) -> list[tuple[str, float]]:
    from .proxy_ctrl import list_nodes

    nodes = nodes or list_nodes()
    scored: list[tuple[str, float]] = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for node, s in zip(nodes, pool.map(score, nodes)):
            if s is not None:
                scored.append((node, _smooth_score(node, s)))
    scored.sort(key=lambda t: t[1])
    return scored


def do_switch(
    group: str,
    node: str,
    *,
    force: bool = False,
    reason: str = "manual",
    from_node: str | None = None,
) -> bool:
    global _LAST_SWITCH_TS, _DEFER_COUNT
    if should_defer_switch(force=force):
        return False
    if set_node(group, node):
        _LAST_SWITCH_TS = time.time()
        _DEFER_COUNT = 0
        _reset_faster_tracking()
        config.save_last_switch(from_node, node, reason, forced=force)
        return True
    return False


def confirm_stable(node: str, attempts: int = SWITCH_CONFIRM_ATTEMPTS) -> bool:
    if attempts <= 0:
        return True
    for _ in range(attempts):
        if score(node) is None:
            return False
    return True


def confirmed_target(ranking: list[tuple[str, float]]) -> tuple[str, float] | None:
    cap = SWITCH_CONFIRM_CANDIDATES if SWITCH_CONFIRM_CANDIDATES > 0 else len(ranking)
    for node, s in ranking[:cap]:
        if confirm_stable(node):
            return node, s
    return None


def _switch_to_confirmed(
    group: str,
    ranking: list[tuple[str, float]],
    *,
    force: bool = False,
    reason: str = "failover",
    from_node: str | None = None,
) -> tuple[str, float, bool]:
    confirmed = confirmed_target(ranking)
    node, s = confirmed if confirmed else ranking[0]
    do_switch(group, node, force=force, reason=reason, from_node=from_node)
    return node, s, confirmed is None


def _decision_to_result(decision: SwitchDecision, group: str) -> dict:
    base = {"action": decision.action, "group": group}
    if decision.reason:
        base["reason"] = decision.reason
    base.update(decision.payload)
    if decision.from_node is not None:
        base["from"] = decision.from_node
    if decision.to_node is not None:
        base["to"] = decision.to_node
    return base


def _apply_decision(
    decision: SwitchDecision,
    group: str,
    ranking: list[tuple[str, float]],
    cur: str | None,
) -> dict:
    global _DEFER_COUNT, _FASTER_CANDIDATE, _FASTER_SINCE
    unconfirmed_note = " (no candidate passed re-check; best effort)"

    if decision.action == "idle_skip":
        return _decision_to_result(decision, group)

    if decision.action in ("pending", "cooldown", "deferred", "kept"):
        payload = decision.payload
        if payload.get("_reset_faster"):
            _reset_faster_tracking()
        if payload.get("_reset_defer"):
            _DEFER_COUNT = 0
        if decision.action == "pending":
            _FASTER_CANDIDATE = payload.pop("_faster_candidate", None)
            _FASTER_SINCE = payload.pop("_faster_since", 0.0)
        if decision.action == "deferred" and "defer_count" in payload:
            _DEFER_COUNT = payload["defer_count"]
        return _decision_to_result(decision, group)

    if decision.action == "switched":
        if decision.reason == "optimization":
            best = decision.to_node or ranking[0][0]
            cur_score = decision.payload.get("from_score", 0)
            best_score = decision.payload.get("to_score", 0)
            pct = decision.payload.get("improvement_pct", 0)
            sustained = decision.payload.get("sustained_s", 0)
            forced = decision.payload.get("forced", False)
            if not confirm_stable(best):
                _DEFER_COUNT = 0
                log(
                    f"hold '{cur}'({cur_score}): '{best}'({best_score}) "
                    f"failed stability re-check -- not switching"
                )
                return {
                    "action": "kept",
                    "node": cur,
                    "score": cur_score,
                    "best": best,
                    "best_score": best_score,
                    "group": group,
                    "reason": "candidate unstable",
                }
            if not do_switch(
                group,
                best,
                force=forced,
                reason=decision.reason,
                from_node=cur,
            ):
                if should_defer_switch(force=forced):
                    return {
                        "action": "deferred",
                        "node": cur,
                        "score": cur_score,
                        "best": best,
                        "best_score": best_score,
                        "reason": "active connection",
                        "group": group,
                    }
                return {
                    "action": "kept",
                    "node": cur,
                    "score": cur_score,
                    "best": best,
                    "best_score": best_score,
                    "group": group,
                    "reason": "switch failed",
                }
            log(
                f"switch '{cur}'({cur_score}) -> '{best}'({best_score}) "
                f"({pct}% faster, sustained {sustained}s)"
                + (" (forced after max defers)" if forced else "")
            )
            return {
                "action": "switched",
                "from": cur,
                "to": best,
                "from_score": cur_score,
                "to_score": best_score,
                "forced": forced,
                "group": group,
                "reason": decision.reason,
            }

        node, s, unconfirmed = _switch_to_confirmed(
            group,
            ranking,
            force=decision.force,
            reason=decision.reason,
            from_node=decision.from_node or cur,
        )
        if decision.from_node is None:
            log(f"no current node -> switch to '{node}' ({int(s)})" + (unconfirmed_note if unconfirmed else ""))
            return {"action": "switched", "from": None, "to": node, "score": int(s), "group": group}
        if decision.reason == "whitelist enforcement":
            log(
                f"enforce Opus whitelist: '{decision.from_node}' is not an eligible node "
                f"-> switch to '{node}' ({int(s)})" + (unconfirmed_note if unconfirmed else "")
            )
        elif decision.reason == "benched":
            log(f"current '{decision.from_node}' is benched -> switch to '{node}' ({int(s)})"
                + (unconfirmed_note if unconfirmed else ""))
        elif decision.reason == "confirmed dead at scan":
            log(f"current '{decision.from_node}' confirmed dead -> switch to '{node}' ({int(s)})"
                + (unconfirmed_note if unconfirmed else ""))
        else:
            log(f"switch '{decision.from_node}' -> '{node}' ({int(s)}) [{decision.reason}]"
                + (unconfirmed_note if unconfirmed else ""))
        result = {
            "action": "switched",
            "from": decision.from_node,
            "to": node,
            "score": int(s),
            "group": group,
            "reason": decision.reason,
        }
        if unconfirmed:
            result["unconfirmed"] = True
        return result

    return _decision_to_result(decision, group)


def pick_and_switch(
    group: str | None = None,
    nodes: list[str] | None = None,
    *,
    idle: bool = False,
) -> dict:
    global _DEFER_COUNT, _FASTER_CANDIDATE, _FASTER_SINCE
    proxies = fetch_proxies()
    group = group or target_group(proxies)
    nodes = nodes or eligible_nodes(proxies)
    candidates = drop_benched(nodes)
    cur = (proxies.get(group) or {}).get("now")

    if idle and IDLE_SCAN and cur and is_alive(cur):
        log(f"idle scan: keep '{cur}' (healthy, skipping full rank)")
        return {"action": "idle_skip", "node": cur, "reason": "healthy idle scan", "group": group}

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

    ctx = SwitchContext(
        group=group,
        cur=cur,
        cur_score=cur_score,
        best=best,
        best_score=best_score,
        ranking=ranking,
        nodes=nodes,
        last_switch_ts=_LAST_SWITCH_TS,
        defer_count=_DEFER_COUNT,
        faster_candidate=_FASTER_CANDIDATE,
        faster_since=_FASTER_SINCE,
    )
    decision = decide(ctx)
    if decision.action == "pending":
        cur_score_i = int(cur_score or 0)
        pct = improvement_pct(best_score, cur_score or best_score)
        log(
            f"hold '{cur}'({cur_score_i}): '{best}'({int(best_score)}) "
            f"{pct}% faster, waiting "
            f"{decision.payload.get('sustained_s', 0)}/{SWITCH_SUSTAIN_SECONDS}s sustained"
        )
    elif decision.action == "cooldown":
        log(
            f"hold '{cur}'({int(cur_score or 0)}): '{best}'({int(best_score)}) "
            f"within {SWITCH_COOLDOWN}s cooldown"
        )
    elif decision.action == "deferred" and decision.reason == "whitelist enforcement":
        log(f"defer Opus whitelist enforcement on '{cur}': active Cursor/Anthropic connection")
    elif decision.action == "deferred" and decision.reason == "active connection":
        dc = decision.payload.get("defer_count", 0)
        log(
            f"defer switch '{cur}'({int(cur_score or 0)}) -> '{best}'({int(best_score)}) "
            f"({dc}/{MAX_DEFER}): active Cursor/Anthropic connection in flight"
        )
    elif decision.action == "kept" and decision.reason == "alive but not ranked":
        log(f"keep '{cur}' (didn't rank this scan but still alive)")
    elif decision.action == "kept" and decision.reason == "not significantly faster":
        _reset_faster_tracking()
        _DEFER_COUNT = 0
        log(
            f"keep '{cur}' ({int(cur_score or 0)}); best '{best}' ({int(best_score)}) "
            f"not {SWITCH_IMPROVEMENT_PCT}%+ faster for {SWITCH_SUSTAIN_SECONDS}s"
        )

    return _apply_decision(decision, group, ranking, cur)


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
    if do_switch(group, node, force=True, reason="manual"):
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


# Re-export policy helpers used by tests and daemon.
from .switch_policy import improvement_pct as improvement_pct  # noqa: E402
from .switch_policy import significantly_faster as significantly_faster  # noqa: E402

# Backward-compatible alias.
from .env_config import MAX_DEFER  # noqa: E402
