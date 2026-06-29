"""Quit Cursor, patch model catalog, and restart Cursor.

Requires clashpilot proxy on 127.0.0.1:7890 before running.

Usage:
  python tools/repair_cursor_models.py
  python tools/repair_cursor_models.py --no-restart
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from patch_cursor_models import PROXY, cursor_running, patch_catalog  # noqa: E402

CURSOR_EXE_CANDIDATES = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "cursor" / "Cursor.exe",
    Path(r"C:\Program Files\Cursor\Cursor.exe"),
    Path(r"C:\Program Files (x86)\Cursor\Cursor.exe"),
)
QUIT_GRACE_SECONDS = 12
QUIT_FORCE_WAIT_SECONDS = 20
PROXY_WAIT_SECONDS = 15


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)


def find_cursor_exe() -> Path | None:
    which = shutil.which("cursor")
    if which:
        path = Path(which)
        if path.name.lower() == "cursor.cmd":
            for candidate in CURSOR_EXE_CANDIDATES:
                if candidate.exists():
                    return candidate
        if path.exists():
            return path
    for candidate in CURSOR_EXE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def proxy_ready() -> bool:
    host, port = "127.0.0.1", 7890
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def wait_for_proxy(timeout: float = PROXY_WAIT_SECONDS) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proxy_ready():
            return True
        time.sleep(0.5)
    return False


def quit_cursor() -> None:
    if not cursor_running():
        print("Cursor is not running.")
        return

    print("Requesting Cursor to quit...")
    _run(["taskkill", "/IM", "Cursor.exe"])
    deadline = time.time() + QUIT_GRACE_SECONDS
    while time.time() < deadline:
        if not cursor_running():
            print("Cursor exited.")
            return
        time.sleep(0.5)

    print("Force-killing remaining Cursor processes...")
    _run(["taskkill", "/IM", "Cursor.exe", "/F"])
    deadline = time.time() + QUIT_FORCE_WAIT_SECONDS
    while time.time() < deadline:
        if not cursor_running():
            print("Cursor exited.")
            return
        time.sleep(0.5)

    raise SystemExit("ERROR: Cursor.exe still running after force kill")


def start_cursor(exe: Path) -> None:
    print(f"Starting Cursor -> {exe}")
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Quit Cursor, patch model catalog, optionally restart Cursor.",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="patch only; do not relaunch Cursor",
    )
    parser.add_argument(
        "--skip-proxy-check",
        action="store_true",
        help="do not verify clashpilot proxy on 7890",
    )
    args = parser.parse_args()

    if not args.skip_proxy_check:
        if not proxy_ready():
            print(f"Waiting for proxy on {PROXY}...", file=sys.stderr)
            if not wait_for_proxy():
                print(
                    f"ERROR: proxy not listening on {PROXY}. "
                    "Start clashpilot first: clp up",
                    file=sys.stderr,
                )
                return 1
        print(f"proxy OK -> {PROXY}")

    quit_cursor()

    print("\n=== patching model catalog ===")
    rc = patch_catalog(require_quit=True)
    if rc != 0:
        return rc

    if args.no_restart:
        print("\nPatch complete. Start Cursor manually when ready.")
        return 0

    exe = find_cursor_exe()
    if exe is None:
        print("ERROR: could not find Cursor.exe to restart.", file=sys.stderr)
        print("Patch succeeded — launch Cursor manually.", file=sys.stderr)
        return 1

    start_cursor(exe)
    print("\nDone. Cursor restarted with patched model catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
