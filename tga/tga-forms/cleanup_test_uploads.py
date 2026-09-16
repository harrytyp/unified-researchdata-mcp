"""Remove the uploads the UI test runs created (TGA Request: UI-*)."""
import json
import os
import urllib.request

cfg = json.load(open(os.path.expanduser('~/.tga_nomad_config.json'), encoding='utf-8'))
TOK = 'Bearer ' + cfg['nomad_pat']
API = cfg['nomad_url'].rstrip('/') + '/api/v1'
PREFIXES = ('TGA Request: UI-', 'TGA Request: FRESH-', 'TGA Request: SHOT-')   # safety: only these


def req(method, path):
    r = urllib.request.Request(API + path, headers={'Authorization': TOK},
                               method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, resp.read().decode()
    except Exception as e:
        return getattr(e, 'code', 'ERR'), str(e)


def list_uploads():
    st, body = req('GET', '/uploads?page_size=80&order=desc')
    if st != 200:
        raise SystemExit(f'Uploads nicht lesbar: HTTP {st} {body[:200]}')
    return json.loads(body)['data']


targets = [u for u in list_uploads()
           if str(u.get('upload_name') or '').startswith(PREFIXES)]
print(f'Test-Uploads gefunden: {len(targets)}')
for u in targets:
    st, _ = req('DELETE', f"/uploads/{u['upload_id']}")
    print(f"  {u['upload_id']}  {u.get('upload_name')}  -> HTTP {st}")

rest = [u for u in list_uploads()
        if str(u.get('upload_name') or '').startswith(PREFIXES)]
print()
print('verbleibend mit Test-Prefix:', len(rest))
