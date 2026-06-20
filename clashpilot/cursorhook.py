"""Install/uninstall Cursor hooks for starting clashpilot with Cursor."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


HOOK_EVENT = "sessionStart"


def _hooks_path() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def _command_for_exe(exe: str) -> str:
    return f'"{exe}" hook' if " " in exe else f"{exe} hook"


def _hook_command() -> str:
    name = "clashpilotw" if sys.platform == "win32" else "clashpilot"
    exe = shutil.which(name)
    if exe:
        return _command_for_exe(exe)

    current = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if current and current.parent != Path("."):
        suffix = ".exe" if sys.platform == "win32" else ""
        sibling = current.with_name(f"{name}{suffix}")
        if sibling.exists():
            return _command_for_exe(str(sibling))

    return f"{name} hook"


def _is_clashpilot_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    command = str(entry.get("command", "")).strip().lower()
    normalized = command.replace("\\", "/")
    return (
        normalized.endswith(" hook")
        and (
            "clashpilot hook" in normalized
            or "clashpilot.exe hook" in normalized
            or "clashpilot.exe\" hook" in normalized
            or "clashpilotw hook" in normalized
            or "clashpilotw.exe hook" in normalized
            or "clashpilotw.exe\" hook" in normalized
        )
    )


def _read_hooks(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "hooks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid Cursor hooks file: {path} must contain a JSON object")
    return data


def _write_hooks(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def install_cursor_hook() -> str:
    """Add the clashpilot sessionStart hook to Cursor's per-user hooks file."""
    path = _hooks_path()
    data = _read_hooks(path)
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RuntimeError(f"invalid Cursor hooks file: {path} hooks must be an object")

    entries = hooks.setdefault(HOOK_EVENT, [])
    if not isinstance(entries, list):
        raise RuntimeError(f"invalid Cursor hooks file: {path} hooks.{HOOK_EVENT} must be a list")

    command = _hook_command()
    kept = []
    found_current = False
    changed = False
    for entry in entries:
        if not _is_clashpilot_hook_entry(entry):
            kept.append(entry)
            continue
        if isinstance(entry, dict) and entry.get("command") == command and not found_current:
            kept.append(entry)
            found_current = True
        else:
            changed = True

    entries[:] = kept
    if not found_current:
        entries.append({"command": command})
        _write_hooks(path, data)
        return f"installed Cursor {HOOK_EVENT} hook: {command}\n{path}"

    if changed:
        _write_hooks(path, data)
        return f"updated Cursor {HOOK_EVENT} hook: {command}\n{path}"

    return f"Cursor {HOOK_EVENT} hook already installed: {command}\n{path}"


def uninstall_cursor_hook() -> str:
    """Remove clashpilot's Cursor sessionStart hook if present."""
    path = _hooks_path()
    if not path.exists():
        return f"Cursor hooks not installed (no {path})"

    data = _read_hooks(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return f"Cursor hooks unchanged (no hooks object in {path})"

    entries = hooks.get(HOOK_EVENT)
    if not isinstance(entries, list):
        return f"Cursor hooks unchanged (no {HOOK_EVENT} list in {path})"

    before = len(entries)
    entries[:] = [e for e in entries if not _is_clashpilot_hook_entry(e)]
    if len(entries) == before:
        return f"Cursor {HOOK_EVENT} hook not installed in {path}"

    _write_hooks(path, data)
    return f"removed Cursor {HOOK_EVENT} hook from {path}"
