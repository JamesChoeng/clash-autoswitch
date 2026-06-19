"""Make the `clashpilot` / `clp` console scripts reachable from a bare shell.

pip/PEP-517 wheels have no reliable post-install hook, and `pip install --user`
often drops console scripts into a directory that isn't on PATH. So we do it
ourselves: locate the directory the entry-point executables live in and add it
to the *user* PATH persistently.

  - Windows : write HKCU\\Environment\\Path via winreg + broadcast WM_SETTINGCHANGE
              (new processes pick it up; already-open shells need a restart).
              Also drop a PowerShell profile shim so `clp` shadows the built-in
              `clp` alias (Clear-ItemProperty), which otherwise wins.
  - macOS/Linux : append an idempotent `export PATH=...` line to the shell rc
                  files (~/.profile plus ~/.bashrc / ~/.zshrc).

Everything here is idempotent and best-effort: failures never abort the caller.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

_MARKER = "# clashpilot (added by `clashpilot setup-path`)"


# --- Locate the directory holding the console scripts ------------------------


def _exe_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("clashpilot.exe", "clp.exe")
    return ("clashpilot", "clp")


def _candidate_dirs() -> list[Path]:
    cands: list[Path] = []

    # 1. The launcher we were invoked as (console-script case): most reliable.
    argv0 = (sys.argv[0] or "").strip()
    if argv0:
        name = Path(argv0).name.lower()
        if name not in ("__main__.py", "python.exe", "pythonw.exe", "python", "pythonw"):
            cands.append(Path(argv0).resolve().parent)

    # 2. sysconfig scripts dirs for the current + user install schemes.
    try:
        cands.append(Path(sysconfig.get_path("scripts")))
    except Exception:  # noqa: BLE001
        pass
    for scheme in ("nt_user", "posix_user"):
        try:
            if scheme in sysconfig.get_scheme_names():
                cands.append(Path(sysconfig.get_path("scripts", scheme)))
        except Exception:  # noqa: BLE001
            pass

    seen: set[str] = set()
    out: list[Path] = []
    for d in cands:
        try:
            key = os.path.normcase(str(d.resolve()))
        except Exception:  # noqa: BLE001
            key = os.path.normcase(str(d))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def scripts_dir() -> Path | None:
    """The directory containing the clashpilot/clp executables, if found."""
    names = _exe_names()
    for d in _candidate_dirs():
        try:
            if any((d / n).exists() for n in names):
                return d
        except Exception:  # noqa: BLE001
            continue
    # Fall back to the first existing candidate even if we can't see the exes
    # (e.g. running from source before the wheel scripts were generated).
    for d in _candidate_dirs():
        try:
            if d.exists():
                return d
        except Exception:  # noqa: BLE001
            continue
    return None


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
    except Exception:  # noqa: BLE001
        return a == b


def _on_path(d: Path) -> bool:
    target = str(d)
    for p in (os.environ.get("PATH") or "").split(os.pathsep):
        if p and _same_dir(p, target):
            return True
    return False


# --- Windows -----------------------------------------------------------------


def _win_broadcast_env_change() -> None:
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x1A
        SMTO_ABORTIFHUNG = 0x2
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(res),
        )
    except Exception:  # noqa: BLE001
        pass


def _win_add_to_path(d: Path) -> tuple[bool, str]:
    """Add `d` to the persistent user PATH (HKCU\\Environment). Returns (changed, msg)."""
    import winreg

    target = str(d)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except OSError as e:
        return False, f"could not open HKCU\\Environment: {e}"
    try:
        try:
            cur, typ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            cur, typ = "", winreg.REG_EXPAND_SZ
        parts = [p for p in str(cur).split(";") if p]
        if any(_same_dir(p, target) for p in parts):
            return False, f"already on user PATH: {target}"
        parts.append(target)
        new_val = ";".join(parts)
        winreg.SetValueEx(key, "Path", 0, typ or winreg.REG_EXPAND_SZ, new_val)
    finally:
        winreg.CloseKey(key)
    _win_broadcast_env_change()
    return True, f"added to user PATH: {target}"


def _win_powershell_profiles() -> list[Path]:
    docs = Path.home() / "Documents"
    return [
        docs / "WindowsPowerShell" / "profile.ps1",  # Windows PowerShell 5.x
        docs / "PowerShell" / "profile.ps1",          # PowerShell 7+ (pwsh)
    ]


def _win_install_ps_alias() -> list[str]:
    """Shim so `clp` runs clashpilot instead of the built-in Clear-ItemProperty alias."""
    block = (
        f"{_MARKER}\n"
        "if (Test-Path Alias:clp) { Remove-Item Alias:clp -Force -ErrorAction SilentlyContinue }\n"
        "function clp { clashpilot @args }\n"
    )
    msgs: list[str] = []
    for prof in _win_powershell_profiles():
        try:
            existing = prof.read_text(encoding="utf-8") if prof.exists() else ""
            if _MARKER in existing:
                msgs.append(f"PowerShell shim already present: {prof}")
                continue
            prof.parent.mkdir(parents=True, exist_ok=True)
            sep = "" if existing.endswith("\n") or existing == "" else "\n"
            prof.write_text(existing + sep + block, encoding="utf-8")
            msgs.append(f"wrote PowerShell `clp` shim: {prof}")
        except OSError as e:
            msgs.append(f"could not write {prof}: {e}")
    return msgs


# --- POSIX (macOS / Linux) ---------------------------------------------------


def _posix_rc_files() -> list[Path]:
    home = Path.home()
    files = [home / ".profile"]
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        files.append(home / ".zshrc")
    elif "bash" in shell:
        files.append(home / ".bashrc")
    else:
        for name in (".bashrc", ".zshrc"):
            if (home / name).exists():
                files.append(home / name)
    seen: set[str] = set()
    out: list[Path] = []
    for f in files:
        k = str(f)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _posix_add_to_path(d: Path) -> list[str]:
    line = f'export PATH="{d}:$PATH"'
    block = f"\n{_MARKER}\n{line}\n"
    msgs: list[str] = []
    for rc in _posix_rc_files():
        try:
            existing = rc.read_text(encoding="utf-8") if rc.exists() else ""
            if _MARKER in existing or line in existing:
                msgs.append(f"already configured: {rc}")
                continue
            rc.parent.mkdir(parents=True, exist_ok=True)
            with open(rc, "a", encoding="utf-8") as f:
                f.write(block)
            msgs.append(f"added PATH export to {rc}")
        except OSError as e:
            msgs.append(f"could not write {rc}: {e}")
    return msgs


# --- Public API --------------------------------------------------------------


def setup_path() -> list[str]:
    """Persistently put the console-scripts dir on the user PATH. Idempotent."""
    d = scripts_dir()
    if d is None:
        return ["could not locate the clashpilot scripts directory; nothing changed"]
    msgs = [f"scripts directory: {d}"]
    if sys.platform == "win32":
        _changed, msg = _win_add_to_path(d)
        msgs.append(msg)
        msgs.extend(_win_install_ps_alias())
        msgs.append("open a NEW terminal for `clashpilot` / `clp` to be found.")
    else:
        msgs.extend(_posix_add_to_path(d))
        msgs.append("run `source ~/.profile` (or open a new shell) to pick it up.")
    return msgs


def ensure_path_quiet() -> bool:
    """Best-effort, silent PATH setup for first-run bring-up.

    Returns True iff it attempted a change. Skips entirely when the scripts dir
    is already reachable on the live PATH, so we don't fight a user who removed
    it on purpose.
    """
    try:
        d = scripts_dir()
        if d is None or _on_path(d):
            return False
        if sys.platform == "win32":
            _win_add_to_path(d)
            _win_install_ps_alias()
        else:
            _posix_add_to_path(d)
        return True
    except Exception:  # noqa: BLE001
        return False
