"""clashpilot: scan nodes, pick best, daemon + standalone lifecycle.

Drives Mihomo via its external-controller (TCP on macOS/Linux/Windows, with a
Windows named-pipe fallback -- see api). Targets Cursor + Anthropic by default.
Process management (pid check / start / stop) is cross-platform.

In standalone mode (bring_up/bring_down) clashpilot also downloads + supervises
its own mihomo core and sets the system proxy; in legacy mode (run_daemon) it
just attaches to a core someone else runs.

Tunable knobs are read from CLASHPILOT_* environment variables at import time;
sensible defaults preserve the original behavior when nothing is set.

State (downloaded core, managed config, pid + log files) lives under a per-user
directory, overridable with CLASHPILOT_STATE_DIR.
"""

from __future__ import annotations

import concurrent.futures as cf
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from . import api, config, core, sysproxy
from .api import ControllerError, ControllerUnreachable, get_json, request
from .config import STATE_DIR

LOG_FILE = STATE_DIR / "clashpilot.log"
PID_FILE = STATE_DIR / "clashpilot.pid"


def _python_exe() -> Path:
    """Interpreter used to (re)spawn the background daemon.

    Prefer pythonw.exe on Windows so the detached daemon never flashes a
    console window; otherwise use the running interpreter.
    """
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            return pyw
    return exe


PYTHON = _python_exe()


# --- Configuration (env-overridable) ----------------------------------------


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


_DEFAULT_TARGETS = [
    "https://api2.cursor.sh",
    "https://api.anthropic.com/v1/messages",
]
TARGETS = [t.strip() for t in _env_str("CLASHPILOT_TARGETS", "").split(",") if t.strip()] or _DEFAULT_TARGETS

# Latency probe (full scan / scoring) -- generous so slow-but-usable nodes rank.
DELAY_TIMEOUT_MS = _env_int("CLASHPILOT_DELAY_TIMEOUT_MS", 4000)
# Liveness probe (health loop) -- shorter; we only care "up or not", not how fast.
HEALTH_TIMEOUT_MS = _env_int("CLASHPILOT_HEALTH_TIMEOUT_MS", 2500)
# Which HTTP statuses count as a successful probe (Mihomo `expected` syntax).
DELAY_EXPECTED = _env_str("CLASHPILOT_DELAY_EXPECTED", "200-599")

FULL_SCAN_INTERVAL = _env_int("CLASHPILOT_FULL_SCAN_INTERVAL", 180)
HEALTH_INTERVAL = _env_int("CLASHPILOT_HEALTH_INTERVAL", 15)
HEALTH_RETRIES = _env_int("CLASHPILOT_HEALTH_RETRIES", 3)
HEALTH_FAIL_THRESHOLD = _env_int("CLASHPILOT_HEALTH_FAIL_THRESHOLD", 3)
SWITCH_TOLERANCE_MS = _env_int("CLASHPILOT_SWITCH_TOLERANCE_MS", 150)
MAX_WORKERS = _env_int("CLASHPILOT_MAX_WORKERS", 10)

# Don't optimization-switch more often than this many seconds (failover bypasses
# it). Prevents flapping between near-equal nodes across consecutive scans.
SWITCH_COOLDOWN = _env_int("CLASHPILOT_SWITCH_COOLDOWN", 60)
# How many consecutive scans we may defer an optimization switch because of an
# in-flight Cursor/Anthropic connection before forcing it through.
MAX_DEFER = _env_int("CLASHPILOT_MAX_DEFER", 5)
# Rotate the log once it grows past this many bytes (single .1 backup kept).
LOG_MAX_BYTES = _env_int("CLASHPILOT_LOG_MAX_BYTES", 1_000_000)
# Standalone mode: re-fetch the subscription + reload the core this often (0=off).
SUB_REFRESH_INTERVAL = _env_int("CLASHPILOT_SUB_REFRESH_INTERVAL", 21600)

INFO_KEYWORDS = ("流量", "剩余", "套餐", "到期", "expire", "重置", "官网", "订阅", "GB", "购买", "续费")
GROUP_TYPES = {
    "Selector", "URLTest", "Fallback", "LoadBalance", "Relay",
    "Direct", "Reject", "RejectDrop", "Compatible", "Pass", "Dns",
}


# On Windows, any console child flashes a window unless we suppress it. Belt and
# suspenders: CREATE_NO_WINDOW *and* a hidden STARTUPINFO, since on some setups
# (GUI/pythonw parents, certain shells) the creation flag alone still flashes.
def _win_no_window() -> dict:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}


_NO_WINDOW = _win_no_window() if sys.platform == "win32" else {}
_WIN_STILL_ACTIVE = 259

# Cross-call state for hysteresis / anti-flap. Module-level because pick_and_switch
# is otherwise stateless and may be invoked once-off or from the daemon loop.
_LAST_SWITCH_TS = 0.0
_DEFER_COUNT = 0


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
    try:
        # Rotate before writing so a single oversized line can't blow past the cap.
        if LOG_MAX_BYTES > 0 and LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))
    except OSError:
        pass
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


# --- Controller reads --------------------------------------------------------


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


def delay(node: str, url: str, timeout_ms: int = DELAY_TIMEOUT_MS) -> int | None:
    q = urllib.parse.urlencode({"url": url, "timeout": timeout_ms, "expected": DELAY_EXPECTED})
    path = f"/proxies/{urllib.parse.quote(node, safe='')}/delay?{q}"
    try:
        status, body = request("GET", path)
        if status != 200:
            return None
        return int(json.loads(body).get("delay") or 0) or None
    except Exception:  # noqa: BLE001
        return None


def is_alive(node: str) -> bool:
    """Liveness check: probe all targets in parallel, success on first hit."""
    for _ in range(HEALTH_RETRIES):
        with cf.ThreadPoolExecutor(max_workers=max(1, len(TARGETS))) as pool:
            results = list(pool.map(lambda u: delay(node, u, HEALTH_TIMEOUT_MS), TARGETS))
        if any(r is not None for r in results):
            return True
    return False


# Hosts whose in-flight connections we must not interrupt with an optional
# (optimization) node switch. A failover off a *dead* node ignores this --
# there's nothing alive to protect at that point.
ACTIVE_HOSTS = ("cursor.sh", "cursor.com", "anthropic")


def has_active_target_connection() -> bool:
    """True if Mihomo reports a live connection to Cursor/Anthropic right now."""
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
    penalty = (len(results) - len(vals)) * 600
    return sum(vals) / len(vals) + penalty


def rank_nodes(nodes: list[str] | None = None) -> list[tuple[str, float]]:
    nodes = nodes or list_nodes()
    scored: list[tuple[str, float]] = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for node, s in zip(nodes, pool.map(score, nodes)):
            if s is not None:
                scored.append((node, s))
    scored.sort(key=lambda t: t[1])
    return scored


def _do_switch(group: str, node: str) -> bool:
    global _LAST_SWITCH_TS, _DEFER_COUNT
    if set_node(group, node):
        _LAST_SWITCH_TS = time.time()
        _DEFER_COUNT = 0
        return True
    return False


def pick_and_switch(group: str | None = None, nodes: list[str] | None = None) -> dict:
    """One scan + switch decision. Returns a summary dict.

    Fetches a single /proxies snapshot and derives group / nodes / current node
    from it to avoid redundant controller round-trips within one decision.
    """
    global _DEFER_COUNT
    proxies = fetch_proxies()
    group = group or target_group(proxies)
    nodes = nodes or list_nodes(proxies)
    cur = (proxies.get(group) or {}).get("now")

    ranking = rank_nodes(nodes)
    if not ranking:
        log("!! no reachable node found this scan")
        return {"action": "none", "reason": "no reachable nodes", "group": group}

    best, best_score = ranking[0]
    cur_score = next((s for n, s in ranking if n == cur), None)
    top = ", ".join(f"{n.split('|')[0]}({int(s)})" for n, s in ranking[:3])
    log(f"scan: {len(ranking)}/{len(nodes)} ok | top: {top}")

    if cur is None:
        _do_switch(group, best)
        log(f"no current node -> switch to '{best}' ({int(best_score)})")
        return {"action": "switched", "from": None, "to": best, "score": int(best_score), "group": group}

    if cur_score is None:
        # Didn't rank this scan: confirm with a dedicated liveness check before
        # failing over, since a single slow scan shouldn't evict a live node.
        if is_alive(cur):
            log(f"keep '{cur}' (didn't rank this scan but still alive)")
            return {"action": "kept", "node": cur, "best": best, "group": group}
        _do_switch(group, best)  # dead-node failover: bypasses cooldown
        log(f"current '{cur}' confirmed dead -> switch to '{best}' ({int(best_score)})")
        return {"action": "switched", "from": cur, "to": best, "score": int(best_score), "group": group}

    if best != cur and best_score < cur_score - SWITCH_TOLERANCE_MS:
        # Optimization switch (current node is alive, just slower). Subject to
        # cooldown, defer-on-active-connection, and a defer cap.
        since = time.time() - _LAST_SWITCH_TS
        if since < SWITCH_COOLDOWN:
            log(
                f"hold '{cur}'({int(cur_score)}): better '{best}'({int(best_score)}) "
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
        forced = _DEFER_COUNT >= MAX_DEFER
        _do_switch(group, best)
        log(
            f"switch '{cur}'({int(cur_score)}) -> '{best}'({int(best_score)})"
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

    _DEFER_COUNT = 0
    log(f"keep '{cur}' ({int(cur_score)}); best '{best}' ({int(best_score)}) within tolerance")
    return {
        "action": "kept",
        "node": cur,
        "score": int(cur_score),
        "best": best,
        "best_score": int(best_score),
        "group": group,
    }


def format_scan(top_n: int = 10) -> str:
    proxies = fetch_proxies()
    nodes = list_nodes(proxies)
    ranking = rank_nodes(nodes)
    lines = [
        f"mode={current_mode()} group={target_group(proxies)} current={current_node(proxies=proxies)}",
        f"scanned {len(nodes)} nodes, {len(ranking)} reachable",
        "",
        f"{'SCORE':>6}  NODE",
        "-" * 60,
    ]
    for name, s in ranking[:top_n]:
        lines.append(f"{int(s):>6}  {name}")
    if not ranking:
        lines.append("(no reachable nodes)")
    return "\n".join(lines)


def format_status() -> str:
    core_line = (
        f"core_running={core.core_running()}\n"
        f"core_version={core.core_version() or 'n/a'}\n"
        f"subscription={'(default)' if config.using_default_subscription() else '(set)'}\n"
        f"mixed_port={config.mixed_port()}\n"
    )
    try:
        proxies = fetch_proxies()
        group = target_group(proxies)
        node = current_node(group, proxies)
        alive = is_alive(node) if node else False
        mode = current_mode()
    except ControllerUnreachable as e:
        return (
            f"controller_unreachable: {e}\n"
            f"{core_line}"
            f"daemon_running={daemon_pid() is not None}"
        )
    daemon = daemon_pid()
    return (
        f"mode={mode}\n"
        f"group={group}\n"
        f"current_node={node}\n"
        f"node_alive={alive}\n"
        f"{core_line}"
        f"daemon_running={daemon is not None}\n"
        f"daemon_pid={daemon or 'n/a'}\n"
        f"state_dir={STATE_DIR}\n"
        f"targets={TARGETS}"
    )


def tail_log(lines: int = 15) -> str:
    if not LOG_FILE.exists():
        return "(no log yet)"
    # Seek the tail instead of reading the whole (rotating) file into memory.
    try:
        with LOG_FILE.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            data = fh.read()
    except OSError:
        return "(log unreadable)"
    text = data.decode("utf-8", "replace").splitlines()
    return "\n".join(text[-lines:])


# --- Process management ------------------------------------------------------


def _proc_cmdline(pid: int) -> str:
    """Best-effort command line of a pid, lowercased. Empty string if unknown."""
    try:
        proc = Path(f"/proc/{pid}/cmdline")
        if proc.exists():
            return proc.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip().lower()
        r = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip().lower()
    except Exception:  # noqa: BLE001
        return ""


def _win_pid_alive(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _WIN_STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _win_terminate(pid: int) -> bool:
    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.TerminateProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)  # signal 0 = existence check, doesn't kill
        return True
    except (OSError, ProcessLookupError):
        return False


def _is_our_daemon(pid: int) -> bool:
    """Guard against PID reuse: the live pid must actually be our daemon."""
    if not _pid_alive(pid):
        return False
    if sys.platform == "win32":
        # Avoid spawning PowerShell/WMI just to read command lines; those helpers
        # are the common source of visible console flashes during Cursor hooks.
        return True
    cmd = _proc_cmdline(pid)
    # If we couldn't read the command line, fall back to existence (best effort).
    if not cmd:
        return True
    return "clashpilot" in cmd


def daemon_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        return pid if _is_our_daemon(pid) else None
    except Exception:  # noqa: BLE001
        return None


def start_daemon() -> str:
    existing = daemon_pid()
    if existing:
        return f"already running (pid {existing})"
    kwargs: dict = {**_NO_WINDOW}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True  # detach so it survives parent exit
    # Detach stdio: the loop logs to LOG_FILE, and inheriting the caller's
    # stdout (e.g. the `hook` process) would corrupt its `{}` output.
    subprocess.Popen(
        [str(PYTHON), "-m", "clashpilot", "up"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **kwargs,
    )
    # Poll instead of a fixed sleep so we return as soon as the pid file lands.
    deadline = time.time() + 5
    while time.time() < deadline:
        time.sleep(0.25)
        pid = daemon_pid()
        if pid:
            return f"started (pid {pid})"
    return f"start requested (check {LOG_FILE})"


def stop_daemon() -> str:
    pid = daemon_pid()
    if not pid:
        PID_FILE.unlink(missing_ok=True)
        return "not running"
    if sys.platform == "win32":
        _win_terminate(pid)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)
    return f"stopped (pid {pid})"


def switch_to(node: str) -> str:
    proxies = fetch_proxies()
    group = target_group(proxies)
    nodes = list_nodes(proxies)
    if node not in nodes:
        matches = [n for n in nodes if node in n]
        if len(matches) == 1:
            node = matches[0]
        elif matches:
            return f"ambiguous ({len(matches)} matches). Be more specific:\n" + "\n".join(matches[:5])
        else:
            return f"node not found: {node!r}"
    if _do_switch(group, node):
        log(f"manual switch -> '{node}'")
        return f"switched {group} -> {node}"
    return f"failed to switch to {node}"


def run_daemon() -> None:
    """Legacy controller-only loop: attach to a core/Verge someone else runs."""
    if not _acquire_singleton():
        return

    def _cleanup(*_args) -> None:
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _cleanup)
        except (ValueError, OSError):
            pass  # not on main thread / unsupported signal

    try:
        _run_loop()
    finally:
        PID_FILE.unlink(missing_ok=True)


def _wait_controller(timeout: int = 20) -> bool:
    """Poll the freshly-launched core's controller until it answers."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            get_json("/version")
            return True
        except ControllerError:
            time.sleep(0.5)
    return False


def bring_up() -> None:
    """Standalone: download core, build config, launch core, set proxy, run.

    Blocks in the autoswitch loop; on any exit path the core is stopped and the
    system proxy is restored.
    """
    if not _acquire_singleton():
        return

    def _cleanup(*_args) -> None:
        bring_down()
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _cleanup)
        except (ValueError, OSError):
            pass

    try:
        log("== standalone up: ensuring mihomo core")
        core.ensure_core()
        if config.using_default_subscription():
            log("== no user subscription set -- using built-in default "
                "(set your own with: clashpilot set-sub <url>)")
        config.ensure_config()
        api.reconfigure()
        pid = core.start_core()
        log(f"== core started (pid {pid}); version {core.core_version()}")
        if not _wait_controller(20):
            log("!! controller not reachable after start -- check core log")
        if sysproxy.set_system_proxy("127.0.0.1", config.mixed_port()):
            log(f"== system proxy set -> 127.0.0.1:{config.mixed_port()}")
        else:
            log("!! could not set system proxy automatically (set it manually)")
        _run_loop(manage_subscription=True)
    finally:
        bring_down()
        PID_FILE.unlink(missing_ok=True)


def bring_down() -> None:
    """Tear down standalone mode: remove the system proxy and stop the core."""
    if sysproxy.unset_system_proxy():
        log("== system proxy removed")
    if core.stop_core():
        log("== core stopped")


def _reload_core_config() -> bool:
    """Ask the running core to reload our managed config from disk."""
    try:
        status, _ = request(
            "PUT", "/configs?force=true",
            body=json.dumps({"path": str(config.CONFIG_FILE)}),
        )
        return status in (204, 200)
    except ControllerError:
        return False


def _run_loop(manage_subscription: bool = False) -> None:
    group: str | None = None
    log(f"== clashpilot start | targets={TARGETS}")
    fails = 0
    last_full = time.time()
    last_sub = time.time()

    # Immediate scan + switch at startup (mirrors original behavior), tolerant
    # of a controller that isn't up yet.
    try:
        group = target_group()
        log(f"== mode group='{group}'")
        pick_and_switch(group)
    except ControllerUnreachable:
        log("startup: controller unreachable -- will retry in loop")
        group = None
    except Exception as e:  # noqa: BLE001
        log(f"!! startup scan error: {type(e).__name__}: {e}")

    while True:
        time.sleep(HEALTH_INTERVAL)
        try:
            if (
                manage_subscription
                and SUB_REFRESH_INTERVAL > 0
                and time.time() - last_sub >= SUB_REFRESH_INTERVAL
            ):
                last_sub = time.time()
                try:
                    config.update_subscription()
                    if _reload_core_config():
                        log("subscription refreshed + core reloaded")
                    else:
                        log("subscription refreshed (core reload failed)")
                except Exception as e:  # noqa: BLE001
                    log(f"!! subscription refresh failed: {type(e).__name__}: {e}")

            if group is None:
                group = target_group()
                log(f"== mode group='{group}'")

            try:
                cur = current_node(group)
            except ControllerUnreachable:
                log("health: controller unreachable -- skipping round (not counted)")
                continue

            if cur is None or not is_alive(cur):
                fails += 1
                log(f"health: current '{cur}' unhealthy ({fails}/{HEALTH_FAIL_THRESHOLD})")
                if fails >= HEALTH_FAIL_THRESHOLD:
                    log("current node confirmed DOWN -> failover")
                    pick_and_switch(group)
                    fails = 0
                    last_full = time.time()
            else:
                if fails:
                    log(f"current '{cur}' recovered, reset fail counter")
                    fails = 0
                if time.time() - last_full >= FULL_SCAN_INTERVAL:
                    pick_and_switch(group)
                    last_full = time.time()
        except ControllerUnreachable:
            log("controller unreachable mid-iteration -- retrying next round")
            group = None  # re-derive group once the controller is back
        except Exception as e:  # noqa: BLE001
            log(f"!! loop error: {type(e).__name__}: {e}")


def _acquire_singleton() -> bool:
    """Atomically claim the pid file; reclaim it only if the old pid is stale."""
    for _ in range(2):
        try:
            fd = os.open(str(PID_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            if daemon_pid() is not None:
                return False  # a live daemon already owns it
            PID_FILE.unlink(missing_ok=True)  # stale -> drop and retry once
    return False
