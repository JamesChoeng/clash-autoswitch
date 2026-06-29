"""Restore Cursor model picker after a degraded catalog fetch.

Run while Cursor is fully quit. Requires clashpilot/proxy to be up BEFORE
restarting Cursor so the catalog refetch succeeds.

Steps:
  1. clp up          # proxy must be listening on 7890
  2. quit Cursor completely
  3. python tools/restore_cursor_models.py
  4. reopen Cursor
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

STATE_DB = Path(
    r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
)
APP_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl"
    ".persistentStorage.applicationUser"
)

# Models the user had working earlier today.
RESTORE_USER_MODELS = [
    "claude-opus-4-8",
    "gpt-5.5",
    "default",
    "composer-2.5",
]


def main() -> int:
    if not STATE_DB.exists():
        print(f"missing: {STATE_DB}", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = STATE_DB.with_name(f"state.vscdb.pre-restore-{stamp}")
    shutil.copy2(STATE_DB, backup)
    print(f"backup -> {backup}")

    con = sqlite3.connect(STATE_DB)
    row = con.execute(
        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
    ).fetchone()
    if not row:
        print("applicationUser blob not found", file=sys.stderr)
        return 1

    raw = row[0]
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)

    before = data.get("availableDefaultModels2") or []
    print(f"cached catalog: {len(before)} models")
    for m in before:
        print(f"  - {m.get('name')} (defaultOn={m.get('defaultOn')})")

    # Force Cursor to refetch the full catalog on next launch.
    data.pop("availableDefaultModels2", None)

    ai = data.setdefault("aiSettings", {})
    ai["userAddedModels"] = list(
        dict.fromkeys(RESTORE_USER_MODELS + (ai.get("userAddedModels") or []))
    )

    composer_cfg = ai.setdefault("modelConfig", {}).setdefault("composer", {})
    composer_cfg["modelName"] = "claude-opus-4-8"
    composer_cfg["maxMode"] = False
    composer_cfg["selectedModels"] = [
        {"modelId": "claude-opus-4-8", "parameters": []}
    ]

    blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
    con.execute("UPDATE ItemTable SET value=? WHERE key=?", (blob, APP_USER_KEY))

    if con.execute(
        "SELECT 1 FROM ItemTable WHERE key='cursor/initialModelState'"
    ).fetchone():
        con.execute(
            "UPDATE ItemTable SET value=? WHERE key='cursor/initialModelState'",
            (b"pending",),
        )
    else:
        con.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("cursor/initialModelState", b"pending"),
        )

    con.commit()
    con.close()

    print("\nrestored:")
    print("  - cleared availableDefaultModels2 (force refetch)")
    print("  - userAddedModels =", ai["userAddedModels"])
    print("  - default composer model -> claude-opus-4-8")
    print("  - initialModelState -> pending")
    print("\nNow reopen Cursor (proxy must already be running).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
