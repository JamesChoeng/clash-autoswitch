"""clashpilot command-line interface.

The `hook` subcommand is what the Cursor `sessionStart` hook invokes: it brings
the whole stack up idempotently and prints `{}` so the hook stays valid. The
other subcommands are for interactive use.

Run as `clashpilot <cmd>` (installed console script) or `python -m clashpilot <cmd>`.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sys
import urllib.request
from pathlib import Path

# Mirror so first-time / refresh downloads survive GitHub being blocked in CN.
os.environ.setdefault("CLASHPILOT_GH_PROXY", "https://ghfast.top")

from . import __version__, config, core, daemon, pathsetup, service, sysproxy

_GEO_BASE = "https://ghfast.top/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/"
_GEO_FILES = ("geoip.metadb", "geosite.dat")


def _log(msg: str) -> None:
    try:
        with open(config.STATE_DIR / "autostart.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _ensure_geo() -> None:
    """mihomo refuses to start without the geo DBs the generated rules reference."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    config.MANAGED_DIR.mkdir(parents=True, exist_ok=True)
    for fn in _GEO_FILES:
        dest = config.MANAGED_DIR / fn
        if dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            req = urllib.request.Request(_GEO_BASE + fn, headers={"User-Agent": "clashpilot"})
            with opener.open(req, timeout=120) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            _log(f"downloaded {fn} ({dest.stat().st_size} bytes)")
        except Exception as e:  # noqa: BLE001
            _log(f"geo {fn} download failed: {e}")


def _ensure_path_once() -> None:
    """First-run only: put the console-scripts dir on PATH, then never auto-touch
    it again (so a user who later removes it isn't fought on every bring-up)."""
    try:
        s = config.get_settings()
        if s.get("path_setup_done"):
            return
        pathsetup.ensure_path_quiet()
        s["path_setup_done"] = True
        config.save_settings(s)
        _log("path setup attempted on first run")
    except Exception as e:  # noqa: BLE001
        _log(f"path setup skipped: {e}")


def _prepare() -> None:
    """First-run prep shared by foreground/background bring-up: PATH, config,
    geo DBs, and the mihomo core binary. All steps are idempotent / cached."""
    _ensure_path_once()
    config.ensure_config()
    _ensure_geo()
    core.ensure_core()


# --- Subcommands -------------------------------------------------------------


def _cmd_hook(_args: argparse.Namespace) -> int:
    """Cursor sessionStart entrypoint: ensure a background daemon is running,
    then print `{}` and return fast (downloads happen in the daemon)."""
    try:
        msg = daemon.start_daemon()
        _log(f"hook: {msg}")
    except Exception as e:  # noqa: BLE001
        _log(f"error: {e}")
    try:
        if sys.stdout is not None:
            sys.stdout.write("{}")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    return 0


def _cmd_up(_args: argparse.Namespace) -> int:
    """Foreground: core + system proxy + autoswitch loop. Blocks until Ctrl-C."""
    running = daemon.daemon_pid()
    if running:
        print(f"clashpilot already running (pid {running}); nothing to do.")
        print("  stop it with: clashpilot down")
        return 0
    print("clashpilot: preparing (config, geo databases, core)...")
    _prepare()
    print("clashpilot up: core + system proxy + autoswitch (foreground, Ctrl-C to stop)")
    print(f"  proxy:      127.0.0.1:{config.mixed_port()} (http+socks)")
    print(f"  controller: 127.0.0.1:{config.controller_port()}")
    print(f"  core:       mihomo {core.core_version()}")
    print(f"  logs:       {daemon.LOG_FILE}")
    daemon.bring_up()  # blocks in the autoswitch loop; tears down on exit
    return 0


def _cmd_down(_args: argparse.Namespace) -> int:
    dmsg = daemon.stop_daemon()  # stop foreground/background loop if any
    stopped = core.stop_core()   # ensure the core is down (idempotent)
    unset = sysproxy.unset_system_proxy()
    print(f"clashpilot down: daemon {dmsg}; core {'stopped' if stopped else 'not running'}, "
          f"system proxy {'unset' if unset else 'unchanged'}")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    print(f"clashpilot {__version__}")
    print(f"  autoswitch:   {'running' if daemon.daemon_pid() else 'stopped'} (pid {daemon.daemon_pid()})")
    print(f"  core running: {core.core_running()} (pid {core.core_pid()})")
    print(f"  core version: {core.core_version()}")
    if config.using_default_subscription():
        print(f"  subscription: (default) {config.DEFAULT_SUBSCRIPTION_URL}")
    else:
        print(f"  subscription: {config.subscription_url()}")
    print(f"  proxy:        127.0.0.1:{config.mixed_port()}")
    print(f"  controller:   127.0.0.1:{config.controller_port()}")
    print(f"  state dir:    {config.STATE_DIR}")
    return 0


def _cmd_install_service(_args: argparse.Namespace) -> int:
    print(service.install_service())
    return 0


def _cmd_uninstall_service(_args: argparse.Namespace) -> int:
    print(service.uninstall_service())
    return 0


def _cmd_set_sub(args: argparse.Namespace) -> int:
    config.set_subscription_url(args.url)
    print(f"saved subscription URL -> {config.SETTINGS_FILE}")
    return 0


def _cmd_setup_path(_args: argparse.Namespace) -> int:
    for line in pathsetup.setup_path():
        print(line)
    # Don't auto-redo on the next bring-up: the user has configured it explicitly.
    try:
        s = config.get_settings()
        s["path_setup_done"] = True
        config.save_settings(s)
    except Exception:  # noqa: BLE001
        pass
    return 0


def _cmd_update(_args: argparse.Namespace) -> int:
    path = config.update_subscription()
    print(f"subscription refreshed; managed config rebuilt at {path}")
    if core.core_running():
        print("note: restart the core to apply (clashpilot down && clashpilot up)")
    return 0


def _prog_name() -> str:
    """Reflect how the user invoked us (e.g. `clp`) in help/usage text."""
    name = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "clashpilot"
    if name.endswith(".py") or name in ("__main__.py", "-c", ""):
        return "clashpilot"
    return name


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=_prog_name(), description="Standalone Clash/Mihomo client.")
    p.add_argument("--version", action="version", version=f"clashpilot {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("hook", help="Cursor sessionStart entrypoint: ensure the background daemon is running.").set_defaults(func=_cmd_hook)
    sub.add_parser("up", help="Core + system proxy + autoswitch in the foreground (Ctrl-C to stop).").set_defaults(func=_cmd_up)
    sub.add_parser("down", help="Stop the daemon/core and unset the system proxy.").set_defaults(func=_cmd_down)
    sub.add_parser("status", help="Show core / proxy / subscription status.").set_defaults(func=_cmd_status)

    sp = sub.add_parser("set-sub", help="Save your Clash/Mihomo subscription URL.")
    sp.add_argument("url")
    sp.set_defaults(func=_cmd_set_sub)

    sub.add_parser("update", help="Re-fetch the subscription and rebuild the config.").set_defaults(func=_cmd_update)
    sub.add_parser(
        "setup-path",
        help="Add the clashpilot/clp scripts dir to your user PATH (idempotent).",
    ).set_defaults(func=_cmd_setup_path)
    sub.add_parser(
        "install-service",
        help="Run clashpilot in the background at login (restarts on crash).",
    ).set_defaults(func=_cmd_install_service)
    sub.add_parser(
        "uninstall-service",
        help="Remove the login-launched background service.",
    ).set_defaults(func=_cmd_uninstall_service)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except core.CoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
