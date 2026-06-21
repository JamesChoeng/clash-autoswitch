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
import hashlib
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

# Fallback download mirror, used ONLY when a direct github.com fetch fails (helps
# users where github.com is blocked). We never route through a third party by
# default when the direct connection works; binary integrity is verified against
# the GitHub API regardless of which URL actually served the bytes. Override or
# force-prefer a mirror with CLASHPILOT_GH_PROXY.
_DEFAULT_GH_FALLBACK = "https://ghfast.top"

# On Windows, the mihomo console child flashes a window unless suppressed. Belt
# and suspenders: CREATE_NO_WINDOW *and* a hidden STARTUPINFO, since the creation
# flag alone still flashes on some setups (GUI/pythonw parents, certain shells).
def _win_no_window() -> dict:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}


_NO_WINDOW = _win_no_window() if sys.platform == "win32" else {}
_WIN_STILL_ACTIVE = 259

CORE_PID_FILE = CORE_DIR / "mihomo.pid"
CORE_VERSION_FILE = CORE_DIR / "version.txt"
CORE_LOG_FILE = CORE_DIR / "mihomo.log"

# Rotate the core log on (re)launch once it grows past this; mihomo holds the
# handle while running, so a single .1 backup swapped at startup is enough.
try:
    CORE_LOG_MAX_BYTES = int(os.getenv("CLASHPILOT_CORE_LOG_MAX_BYTES") or "")
except ValueError:
    CORE_LOG_MAX_BYTES = 2_000_000


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


def _download_candidates(github_url: str) -> list[str]:
    """Ordered URLs to try for a github.com asset.

    Default: direct GitHub first, then the built-in fallback mirror. When the
    user explicitly sets CLASHPILOT_GH_PROXY they've opted into a mirror (likely
    because direct access is blocked), so try it first and fall back to direct.
    """
    env = (os.getenv("CLASHPILOT_GH_PROXY") or "").strip().rstrip("/")
    if env:
        # e.g. CLASHPILOT_GH_PROXY=https://ghproxy.com -> https://ghproxy.com/https://github.com/...
        return [f"{env}/{github_url}", github_url]
    return [github_url, f"{_DEFAULT_GH_FALLBACK}/{github_url}"]


def _fetch(url: str, dest: Path, timeout: int = 120) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "clashpilot"})
    with _opener().open(req, timeout=timeout) as r, open(dest, "wb") as out:
        shutil.copyfileobj(r, out)


def download_github(github_url: str, dest: Path, timeout: int = 120) -> None:
    """Download a github.com URL, trying a mirror fallback when direct fails."""
    last: Exception | None = None
    for url in _download_candidates(github_url):
        try:
            _fetch(url, dest, timeout)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise CoreError(f"download failed ({github_url}): {last}")


def _asset_digest(version: str, asset: str) -> str | None:
    """SHA-256 hex for a release asset, read from the authoritative GitHub API.

    Fetched directly from api.github.com over HTTPS (never via a download
    mirror), so a compromised mirror cannot serve a tampered binary together
    with a matching checksum. Returns None if the API is unreachable or doesn't
    expose a digest for this asset.
    """
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{version}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "clashpilot"},
        )
        with _opener().open(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for a in data.get("assets") or []:
        if a.get("name") == asset:
            digest = str(a.get("digest") or "")
            if digest.startswith("sha256:"):
                return digest.split(":", 1)[1].strip().lower()
            return None
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_checksum() -> bool:
    return (os.getenv("CLASHPILOT_REQUIRE_CHECKSUM") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _verify_archive(archive: Path, version: str, asset: str) -> None:
    """Abort if the downloaded asset doesn't match its published SHA-256.

    When no checksum can be obtained (e.g. api.github.com is blocked) we proceed
    with a warning so blocked-region users aren't bricked -- unless the user opts
    into strict mode with CLASHPILOT_REQUIRE_CHECKSUM=1.
    """
    expected = _asset_digest(version, asset)
    if not expected:
        if _require_checksum():
            raise CoreError(
                f"no checksum available for {asset} (GitHub API unreachable) and "
                "CLASHPILOT_REQUIRE_CHECKSUM=1; refusing to run an unverified core"
            )
        print(
            f"clashpilot: WARNING -- could not verify {asset} checksum "
            "(GitHub API unreachable); proceeding without integrity check",
            file=sys.stderr,
        )
        return
    actual = _sha256_file(archive)
    if actual != expected:
        archive.unlink(missing_ok=True)
        raise CoreError(
            f"checksum mismatch for {asset}: expected {expected}, got {actual}. "
            "Refusing to run a possibly tampered mihomo binary."
        )


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
    download_github(f"https://github.com/{GITHUB_REPO}/releases/download/{version}/{asset}", archive)
    try:
        _verify_archive(archive, version, asset)
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
    try:
        if CORE_LOG_MAX_BYTES > 0 and CORE_LOG_FILE.exists() and CORE_LOG_FILE.stat().st_size > CORE_LOG_MAX_BYTES:
            CORE_LOG_FILE.replace(CORE_LOG_FILE.with_name(CORE_LOG_FILE.name + ".1"))
    except OSError:
        pass
    kwargs: dict = {**_NO_WINDOW}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    # The child inherits its own copy of the fd; close ours so the handle isn't
    # leaked for the lifetime of this process.
    with open(CORE_LOG_FILE, "ab") as logf:
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
