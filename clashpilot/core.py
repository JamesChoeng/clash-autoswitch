"""Download and supervise the mihomo core binary.

Standalone mode bundles its own mihomo: we fetch the right release asset for the
current platform from GitHub, cache it under the per-user state dir, and run it
as a child process pointed at our managed config. No Clash Verge / pre-installed
mihomo required.

Downloads bypass any system HTTP proxy (which we may be about to set ourselves,
so it can't be relied on to reach GitHub).
"""

from __future__ import annotations

import gzip
import ctypes
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from .config import CONFIG_FILE, CORE_DIR, MANAGED_DIR

GITHUB_REPO = "MetaCubeX/mihomo"

# On Windows, console helpers flash a window unless explicitly suppressed.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
_WIN_STILL_ACTIVE = 259

CORE_PID_FILE = CORE_DIR / "mihomo.pid"
CORE_VERSION_FILE = CORE_DIR / "version.txt"
CORE_LOG_FILE = CORE_DIR / "mihomo.log"


class CoreError(RuntimeError):
    """Raised when the mihomo core can't be downloaded or launched."""


# --- Platform / asset resolution --------------------------------------------


def _os_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _arch() -> str:
    """mihomo arch token for the current machine.

    amd64 resolves to the `-compatible` (GOAMD64=v1) variant elsewhere; here we
    just return the bare arch and let _asset_name decide on the variant.
    """
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("i386", "i686", "x86"):
        return "386"
    if m.startswith("armv7") or m == "armv7l":
        return "armv7"
    return m


def core_binary() -> Path:
    return CORE_DIR / ("mihomo.exe" if sys.platform == "win32" else "mihomo")


def _asset_name(version: str) -> str:
    os_name = _os_name()
    arch = _arch()
    ext = "zip" if os_name == "windows" else "gz"
    # amd64: the `compatible` build (GOAMD64=v1) runs on the widest range of CPUs.
    if arch == "amd64":
        return f"mihomo-{os_name}-amd64-compatible-{version}.{ext}"
    return f"mihomo-{os_name}-{arch}-{version}.{ext}"


def _opener() -> urllib.request.OpenerDirector:
    # Empty ProxyHandler => ignore any system/env proxy for these requests.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _latest_version() -> str:
    env = os.getenv("CLASHPILOT_CORE_VERSION")
    if env:
        return env if env.startswith("v") else f"v{env}"
    # Preferred: the GitHub releases API.
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "clashpilot"},
        )
        with _opener().open(req, timeout=15) as r:
            tag = json.loads(r.read().decode("utf-8")).get("tag_name")
            if tag:
                return tag
    except Exception:  # noqa: BLE001
        pass
    # Fallback: /releases/latest 302-redirects to /releases/tag/<version>.
    try:
        url = f"https://github.com/{GITHUB_REPO}/releases/latest"
        with _opener().open(urllib.request.Request(url), timeout=15) as r:
            final = r.geturl()
        tag = final.rstrip("/").rsplit("/", 1)[-1]
        if tag.startswith("v"):
            return tag
    except Exception:  # noqa: BLE001
        pass
    raise CoreError("could not determine latest mihomo version; set CLASHPILOT_CORE_VERSION")


def _download_url(version: str, asset: str) -> str:
    base = f"https://github.com/{GITHUB_REPO}/releases/download/{version}/{asset}"
    proxy = (os.getenv("CLASHPILOT_GH_PROXY") or "").strip().rstrip("/")
    # e.g. CLASHPILOT_GH_PROXY=https://ghproxy.com -> https://ghproxy.com/https://github.com/...
    return f"{proxy}/{base}" if proxy else base


def _fetch(url: str, dest: Path) -> None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "clashpilot"})
        with _opener().open(req, timeout=120) as r, open(dest, "wb") as out:
            shutil.copyfileobj(r, out)
    except Exception as e:  # noqa: BLE001
        raise CoreError(f"download failed ({url}): {e}") from e


def _extract(archive: Path, dest: Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            exe = next((n for n in z.namelist() if n.lower().endswith(".exe")), None)
            if not exe:
                raise CoreError(f"no .exe found inside {archive.name}")
            with z.open(exe) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    else:  # gzipped single binary
        with gzip.open(archive, "rb") as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)


def ensure_core(force: bool = False) -> Path:
    """Return the path to a ready-to-run mihomo binary, downloading if needed."""
    dest = core_binary()
    if dest.exists() and not force:
        return dest
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    version = _latest_version()
    asset = _asset_name(version)
    archive = CORE_DIR / asset
    _fetch(_download_url(version, asset), archive)
    try:
        _extract(archive, dest)
    finally:
        archive.unlink(missing_ok=True)
    if sys.platform != "win32":
        dest.chmod(0o755)
    CORE_VERSION_FILE.write_text(version, encoding="utf-8")
    return dest


def core_version() -> str | None:
    try:
        return CORE_VERSION_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# --- Process lifecycle -------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
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
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


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


def core_pid() -> int | None:
    if not CORE_PID_FILE.exists():
        return None
    try:
        pid = int(CORE_PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    return pid if _pid_alive(pid) else None


def core_running() -> bool:
    return core_pid() is not None


def start_core() -> int:
    """Launch mihomo against the managed config; return its pid (idempotent)."""
    existing = core_pid()
    if existing:
        return existing
    binary = ensure_core()
    MANAGED_DIR.mkdir(parents=True, exist_ok=True)
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(CORE_LOG_FILE, "ab")
    kwargs: dict = {**_NO_WINDOW}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [str(binary), "-d", str(MANAGED_DIR), "-f", str(CONFIG_FILE)],
        stdout=logf, stderr=logf, **kwargs,
    )
    CORE_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def stop_core() -> bool:
    pid = core_pid()
    if not pid:
        CORE_PID_FILE.unlink(missing_ok=True)
        return False
    if sys.platform == "win32":
        _win_terminate(pid)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    CORE_PID_FILE.unlink(missing_ok=True)
    return True
