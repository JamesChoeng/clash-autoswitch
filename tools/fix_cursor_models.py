"""Reset Cursor's stale model catalog so it refetches Claude/GPT on next launch.

Run only while Cursor is fully quit.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

STATE_DB = Path(
    r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
)
APP_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl"
    ".persistentStorage.applicationUser"
)

# Models the user had working earlier today (from Cursor logs).
RESTORE_MODELS = [
    "claude-opus-4-8",
    "gpt-5.5",
    "default",
]


def main() -> int:
    if not STATE_DB.exists():
        print(f"missing: {STATE_DB}", file=sys.stderr)
        return 1

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
        print(f"  - {m.get('name')}")

    data.pop("availableDefaultModels2", None)

    ai = data.setdefault("aiSettings", {})
    ai["userAddedModels"] = list(dict.fromkeys(RESTORE_MODELS + (ai.get("userAddedModels") or [])))

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

    con.commit()
    con.close()

    print("\nfixed:")
    print("  - cleared availableDefaultModels2 (force refetch on launch)")
    print("  - userAddedModels =", ai["userAddedModels"])
    print("  - default composer model -> claude-opus-4-8")
    print("\nNow fully quit Cursor, then reopen it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
