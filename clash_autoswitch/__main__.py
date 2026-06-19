"""Command-line entry point for clash-autoswitch.

    clash-autoswitch run        # run the daemon in the foreground (blocks)
    clash-autoswitch once       # one scan + switch, then exit
    clash-autoswitch ensure     # start the daemon in the background if not running
    clash-autoswitch stop       # stop the background daemon
    clash-autoswitch status     # show controller / node / daemon status
    clash-autoswitch scan       # rank all nodes by latency (no switch)
    clash-autoswitch switch X   # manually switch to node matching X
    clash-autoswitch log        # tail the daemon log
    clash-autoswitch install-service     # auto-start at login (launchd/systemd/schtasks)
    clash-autoswitch uninstall-service

Legacy flags from the original script still work: `--once`, `--ensure`.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clash-autoswitch",
        description="Auto-pick the fastest Clash/Mihomo node and fail over when it dies.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # Legacy flags (pre-subcommand interface).
    p.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--ensure", action="store_true", help=argparse.SUPPRESS)

    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="run the daemon in the foreground (blocks)")
    sub.add_parser("once", help="one scan + switch, then exit")
    sub.add_parser("ensure", help="start the daemon in the background if not running")
    sub.add_parser("stop", help="stop the background daemon")
    sub.add_parser("status", help="show controller / node / daemon status")
    sub.add_parser("scan", help="rank all nodes by latency (no switch)")
    sw = sub.add_parser("switch", help="manually switch to a node")
    sw.add_argument("node", help="node name or unique substring")
    lg = sub.add_parser("log", help="tail the daemon log")
    lg.add_argument("-n", "--lines", type=int, default=15, help="number of lines (default 15)")
    sub.add_parser("install-service", help="auto-start at login")
    sub.add_parser("uninstall-service", help="remove the login auto-start")
    return p


def _make_output_unicode_safe() -> None:
    """Node names often contain emoji flags; default Windows consoles are GBK
    and would raise UnicodeEncodeError on print(). Reconfigure to UTF-8 with a
    replacement fallback so output never crashes the command."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> None:
    _make_output_unicode_safe()
    args = _build_parser().parse_args(argv)

    # Defer importing the daemon until after arg parsing so `--help`/`--version`
    # never touch the controller or filesystem state.
    from . import daemon

    cmd = args.cmd
    if args.ensure and not cmd:
        cmd = "ensure"
    if args.once and not cmd:
        cmd = "once"

    if cmd == "once":
        daemon.log(f"== autoswitch once | targets={daemon.TARGETS}")
        print(daemon.pick_and_switch())
    elif cmd == "ensure":
        print(daemon.start_daemon())
    elif cmd == "stop":
        print(daemon.stop_daemon())
    elif cmd == "status":
        print(daemon.format_status())
    elif cmd == "scan":
        print(daemon.format_scan())
    elif cmd == "switch":
        print(daemon.switch_to(args.node))
    elif cmd == "log":
        print(daemon.tail_log(args.lines))
    elif cmd == "install-service":
        from . import service
        print(service.install_service())
    elif cmd == "uninstall-service":
        from . import service
        print(service.uninstall_service())
    else:
        # Default (`run` or no subcommand): foreground daemon.
        daemon.run_daemon()


if __name__ == "__main__":
    sys.exit(main())
