import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
needles = ("claude-opus", "gpt-5", "composer-2", "availableModels", "enabledModel", "selectedModel", "modelConfig", "modelPicker")
for k, val in con.execute("SELECT key, value FROM ItemTable"):
    s = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
    sl = s.lower()
    if any(n.lower() in sl for n in needles) or any(n.lower() in k.lower() for n in needles):
        preview = s if len(s) <= 2000 else s[:2000] + "..."
        print(f"KEY: {k}\n{preview}\n---")
con.close()
