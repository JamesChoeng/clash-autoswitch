import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
needles = ("gpt", "claude", "opus", "composer-2", "selected", "enabled", "catalog", "available", "provider", "pricing", "membership", "subscription")
for k, ln in con.execute("SELECT key, length(value) FROM ItemTable ORDER BY key"):
    lk = k.lower()
    if any(n in lk for n in needles) or any(n in lk for n in ("model",)):
        val = con.execute("SELECT value FROM ItemTable WHERE key=?", (k,)).fetchone()[0]
        s = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        if len(s) > 1200:
            s = s[:1200] + "..."
        print(f"{k} ({ln})\n{s}\n---")
con.close()
