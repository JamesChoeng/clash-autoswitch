import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

paths = [
    r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb",
    r"C:\Users\james\AppData\Roaming\Cursor\User\workspaceStorage\52c4496b712f874f0c511ebbab545ef9\state.vscdb",
]

for p in paths:
    print("===", p)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    q = """
    SELECT key, length(value) FROM ItemTable
    WHERE lower(key) LIKE '%model%'
       OR lower(key) LIKE '%composer%'
       OR lower(key) LIKE '%cpp%'
       OR lower(key) LIKE '%catalog%'
       OR lower(key) LIKE '%aichat%'
    """
    for k, ln in con.execute(q):
        val = con.execute("SELECT value FROM ItemTable WHERE key=?", (k,)).fetchone()[0]
        s = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        if len(s) > 800:
            s = s[:800] + "..."
        print(k, ln, "=>", s)
    con.close()
