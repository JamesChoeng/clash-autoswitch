import json, sqlite3, urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')
p = r'C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb'
con = sqlite3.connect('file:'+p+'?mode=ro', uri=True)
token = con.execute("SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'").fetchone()[0]
token = token.decode() if isinstance(token, bytes) else token
con.close()
proxy = urllib.request.ProxyHandler({'http':'http://127.0.0.1:7890','https':'http://127.0.0.1:7890'})
opener = urllib.request.build_opener(proxy)
req = urllib.request.Request('https://api2.cursor.sh/aiserver.v1.AiService/AvailableModels', data=b'{}', method='POST', headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Connect-Protocol-Version':'1'})
models = json.loads(opener.open(req, timeout=30).read())['models']
print('total', len(models))
for m in models:
    n = m['name']
    if 'opus-4-8' in n or n.startswith('gpt-5.5') or n == 'claude-opus-4-8':
        print(n, 'defaultOn=', m.get('defaultOn'), 'legacy=', m.get('legacySlugs'))
