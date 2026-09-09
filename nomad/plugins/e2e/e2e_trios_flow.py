#!/usr/bin/env python3
"""E2E test: TRIOS measurement result through the NOMAD processing stack.

Runs INSIDE the nomad_oasis_app container (local API + NOMAD_PAT from env).
Tests the full input->output cycle with REAL uploads:

  1. Create a fresh upload carrying a TgaMeasurement entry (400 C @ 10 K/min,
     process_now) -> the worker generates the .tprc procedure file
  2. Verify the .tprc appeared in the upload's raw files
  3. Upload a TRIOS measurement as plain .json -> reprocess -> verify result_*
  4. Upload the SAME measurement as compressed .gz (real TRIOS naming: NO
     ".json" in the filename) -> reprocess -> verify result_*
  5. Both files present; both processing runs produced results
  6. Cleanup: delete the test upload

Exit code 0 = all green. Run:  docker exec nomad_oasis_app python3 /app/e2e/e2e_trios_flow.py
"""
import gzip
import io
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get('NOMAD_API_URL', 'http://localhost:8000/nomad-oasis/api/v1')
TOKEN = os.environ.get('NOMAD_PAT', '')
MARKER = f'E2E{int(time.time()) % 100000}'

TRIOS_JSON = {
    "Schema": {"Url": "https://software.tainstruments.com/schemas/TRIOSJSONExportSchema"},
    "Sample": {"Name": f"E2E-Kollidon-{MARKER}",
               "Mass": {"Value": 12.333, "Unit": {"Name": "mg"}}},
    "Procedure": {"Name": "E2E 10K to 400"},
    "Results": {"Processed": {
        "Classification": {"Id": "Latest", "Description": "x"},
        "ColumnHeaders": {
            "Time_min": {"DisplayName": "Time", "ValueType": "Number", "Unit": {"Name": "min"}},
            "Temperature_C": {"DisplayName": "Temperature", "ValueType": "Number", "Unit": {"Name": "degC"}},
            "Weight_pct": {"DisplayName": "Weight", "ValueType": "Number", "Unit": {"Name": "%"}},
            "Weight_mg": {"DisplayName": "Weight", "ValueType": "Number", "Unit": {"Name": "mg"}}
        },
        "Rows": [
            {"Time_min": 0.0, "Temperature_C": 30.0, "Weight_pct": 100.0, "Weight_mg": 12.333},
            {"Time_min": 1.0, "Temperature_C": 130.0, "Weight_pct": 99.0, "Weight_mg": 12.209},
            {"Time_min": 2.0, "Temperature_C": 230.0, "Weight_pct": 98.0, "Weight_mg": 12.086},
            {"Time_min": 3.0, "Temperature_C": 330.0, "Weight_pct": 97.0, "Weight_mg": 11.963},
            {"Time_min": 4.0, "Temperature_C": 400.0, "Weight_pct": 96.5, "Weight_mg": 11.901},
            {"Time_min": 5.0, "Temperature_C": 400.0, "Weight_pct": 96.0, "Weight_mg": 11.840}
        ]
    }},
    "StartTime": "2026-09-09T08:00:00"
}
JSON_NAME = f'{MARKER}_MEASUREMENT.json'
GZ_NAME = f'{MARKER}_MEASUREMENT.gz'   # real TRIOS naming: no .json in name

passed = []


def check(name, ok, detail=''):
    passed.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  [{detail}]' if detail else ''))


def api_raw(method, path, data=None, headers=None, timeout=120):
    h = {'Authorization': f'Bearer {TOKEN}'}
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def api_json(method, path, data=None, timeout=120):
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode()
    st, raw = api_raw(method, path, data,
                      {'Content-Type': 'application/json'} if data else None, timeout)
    try:
        return st, json.loads(raw) if raw else {}
    except Exception:
        return st, {'raw': raw[:200].decode('utf-8', 'replace')}


def _multipart(fname, content):
    boundary = '----e2eboundary'
    body = io.BytesIO()
    body.write(('--' + boundary + '\r\n').encode())
    body.write(('Content-Disposition: form-data; name="file"; filename="' + fname + '"\r\n').encode())
    body.write(b'Content-Type: application/octet-stream\r\n\r\n')
    body.write(content)
    body.write(('\r\n--' + boundary + '--\r\n').encode())
    return body.getvalue(), boundary


def create_upload_with_file(fname, content):
    """POST /uploads with a file — CREATES a new upload (used for the
    initial TgaMeasurement entry; the response is HTML, so the upload is
    located afterwards via the list API)."""
    body, boundary = _multipart(fname, content)
    return api_raw('POST', '/uploads', body,
                   {'Content-Type': f'multipart/form-data; boundary={boundary}'})


def upload_raw_to(upload_id, fname, content):
    """PUT a file INTO an existing upload — NOMAD 1.4.2 streaming method 2
    (same as the operator EXE's nomad_client.upload_raw): URL path = target
    directory (empty = root), filename as 'file_name' query param, body =
    raw bytes. Multipart PUT is NOT accepted by this route. NO
    wait_for_processing: a single-file PUT only creates its own entry; the
    results land in the TgaMeasurement entry via an upload-wide reprocess
    (POST /action/process), which the EXE also triggers after uploads."""
    import urllib.parse
    qs = urllib.parse.urlencode({'file_name': fname})
    return api_raw('PUT', f'/uploads/{upload_id}/raw/?{qs}', content,
                   {'Content-Type': 'application/octet-stream'}, timeout=300)


def find_upload_id(timeout=60):
    """Newest upload whose name starts with our marker (POST /uploads answers
    with HTML, so we locate the created upload via the list API). Polls — the
    upload may take a few seconds to appear in the indexed list.
    Response shape: {'query','pagination','data': [upload, ...]}."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, resp = api_json('GET', f'/uploads?page_size=20&order=desc')
        data = resp.get('data', resp) if isinstance(resp, dict) else []
        ups = data.get('uploads', []) if isinstance(data, dict) else data
        if not isinstance(ups, list):
            ups = []
        for u in ups:
            if str(u.get('upload_name', '')).startswith(MARKER):
                return u.get('upload_id')
        time.sleep(3)
    return None


def newest_archive_mtime(upload_id):
    import glob
    paths = glob.glob(f'/app/.volumes/fs/staging/*/*{upload_id}*/archive/*.msg')
    if not paths:
        return 0.0
    return max(os.path.getmtime(p) for p in paths)


def wait_process_done(upload_id, timeout=240, after_mtime=None):
    """Wait until a NEW processing run finished: returns once an archive
    newer than after_mtime exists (the run wrote its entry archive) — or,
    without after_mtime, once process_status is final and no process runs.
    This avoids the race where the previous run's lingering SUCCESS status
    is seen before the new run even starts."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if after_mtime is not None:
            if newest_archive_mtime(upload_id) > after_mtime:
                return 'SUCCESS'
        else:
            st, resp = api_json('GET', f'/uploads/{upload_id}')
            data = resp.get('data', resp) if isinstance(resp, dict) else {}
            if isinstance(data, dict):
                ps = data.get('process_status', '')
                running = data.get('process_running', False)
                if not running and ps in ('SUCCESS', 'FAILED', 'READY'):
                    return ps or 'READY'
        time.sleep(3)
    return 'TIMEOUT'


def staging_raw_dir(upload_id):
    import glob
    dirs = glob.glob(f'/app/.volumes/fs/staging/*/*{upload_id}*/raw')
    return dirs[0] if dirs else None


def raw_names(upload_id):
    """List raw files of the upload via the shared staging fs (the API raw
    listing endpoint needs a path arg; the fs is mounted in this container)."""
    import glob
    d = staging_raw_dir(upload_id)
    if not d:
        return []
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, '*')))


def read_entry_archive(upload_id):
    """Read the newest processed entry archive (msgpack) from the shared
    staging fs; return (result-fields dict, figure count, n_archives).
    The msgpack contains many envelope objects; the entry data sits at
    keys like '<entry_id>.data.data.<field>', so we strip any leading
    '<entry_id>.data.data.' prefix from collected keys."""
    import glob
    arch_paths = sorted(glob.glob(f'/app/.volumes/fs/staging/*/*{upload_id}*/archive/*.msg'),
                        key=os.path.getmtime)
    if not arch_paths:
        return None, 0, 0
    import msgpack
    u = msgpack.Unpacker(raw=False)
    with open(arch_paths[-1], 'rb') as f:
        u.feed(f.read())
    objs = list(u)
    found = {}
    figs = [0]

    def count_figs(o):
        if isinstance(o, dict):
            if isinstance(o.get('figure'), dict):
                figs[0] += 1
            for v in o.values():
                count_figs(v)
        elif isinstance(o, list):
            for v in o:
                count_figs(v)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.startswith('result_'):
                    found[k] = v
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for obj in objs:
        if isinstance(obj, dict) and 'data' in obj:
            count_figs(obj)
            walk(obj)
    return found, figs[0], len(arch_paths)


def verify_results(upload_id, tag, expect_gz):
    """Read the entry archive and assert the result fields for one
    processing run. Returns (ok, detail)."""
    res, figs, narch = read_entry_archive(upload_id)
    if res is None:
        return False, f'kein Archiv lesbar (gefunden: {narch})'
    jf = str(res.get('result_json_filename', ''))
    rc = int(res.get('result_row_count', 0) or 0)
    rn = str(res.get('result_sample_name', ''))
    ts = res.get('result_temperature_signal', [])
    ok_name = (jf.endswith('.gz') if expect_gz else jf.endswith('.json')) and MARKER in jf
    details = f'file={jf} sample={rn} rows={rc} pts={len(ts) if isinstance(ts, list) else "?"} figs={figs}'
    return (ok_name and MARKER in rn and rc == 6
            and isinstance(ts, list) and 0 < len(ts) <= 6 and figs >= 1), details


def main():
    print(f'=== E2E {MARKER}: TRIOS-Ergebnis durch NOMAD-Stack (.json UND .gz) ===')
    upload_id = None
    try:
        # 1) Upload mit TgaMeasurement-Entry (process_now -> .tprc wird generiert)
        archive = {
            "data": {
                "m_def": "instrument_data.schema.TgaMeasurement",
                "procedure_name": "E2E Ramp 400 C 10 Kmin",
                "temperature_segments": [
                    {"m_def": "instrument_data.schema.RampSegment", "end_temp": 400, "rate": 10}
                ],
                "process_now": True,
            }
        }
        st, _ = create_upload_with_file(f'{MARKER}.archive.json', json.dumps(archive).encode())
        upload_id = find_upload_id()
        check('1. Test-Upload mit Entry erstellt', bool(upload_id) and st in (200, 201),
              f'upload={upload_id} http={st}')
        if not upload_id:
            sys.exit(1)

        # 2) .tprc muss vom Worker generiert sein (erster Prozess-Lauf)
        status = wait_process_done(upload_id)
        names = raw_names(upload_id)
        tprc = [n for n in names if n.endswith('.tprc')]
        check('2. .tprc vom Worker generiert', bool(tprc), f'files={names} status={status}')

        # 3) Messung als plain .json in den Upload legen + reprocess -> PRUEFEN.
        #    (PUT + anschliessender Upload-Reprocess, wie die EXE es macht.)
        #    NOTE: der PUT stoesst selbst einen MINI-Prozess an (nur
        #    Datei-Registrierung, <3s, leicht zu verpassen). Ein POST
        #    /action/process direkt danach gibt 400 ("processing already
        #    running") — also erst abwarten, bis der Status stabil final ist.
        st, _ = upload_raw_to(upload_id, JSON_NAME, json.dumps(TRIOS_JSON).encode())
        check('3a. .json hochgeladen', st in (200, 201), f'http={st}')
        t_wait = time.time()
        last_state, stable = None, 0
        while time.time() - t_wait < 60:
            stq, respq = api_json('GET', f'/uploads/{upload_id}')
            dq = respq.get('data', respq) if isinstance(respq, dict) else {}
            if isinstance(dq, dict):
                state = (dq.get('process_running'), dq.get('process_status'))
                stable = stable + 1 if state == last_state else 1
                last_state = state
                if not state[0] and state[1] in ('SUCCESS', 'FAILED', 'READY') and stable >= 2:
                    break
            time.sleep(3)
        before = newest_archive_mtime(upload_id)
        pst, presp = api_json('POST', f'/uploads/{upload_id}/action/process', b'{}')
        status = wait_process_done(upload_id, after_mtime=before)
        ok3, det3 = verify_results(upload_id, '.json-Lauf', expect_gz=False)
        check('3b. result_* aus .json verarbeitet', ok3, f'{det3} post={pst} status={status}')

        # 4) gleiche Messung als .gz (TRIOS-Benennung ohne .json) + reprocess.
        #    NOTE: NOMADs Upload-API weigert sich, Dateien mit .gz-Endung
        #    anzunehmen (jede .gz wird als tar-Archiv geprueft -> 400
        #    "Cannot extract file"). Der einzige Weg fuer eine echte
        #    TRIOS-.gz (plain gzip) in einen Upload ist das direkte
        #    Staging-FS — hier im App-Container gemountet.
        #    Die .json aus Schritt 3 wird entfernt: der Upload-Scan nimmt
        #    sonst immer die .json (sortiert vor .gz), und ein Upload traegt
        #    realistisch genau EIN Ergebnis.
        raw_dir = staging_raw_dir(upload_id)
        old_json = os.path.join(raw_dir, JSON_NAME)
        if os.path.exists(old_json):
            os.remove(old_json)
        gz = gzip.compress(json.dumps(TRIOS_JSON).encode('utf-8'))
        with open(os.path.join(raw_dir, GZ_NAME), 'wb') as f:
            f.write(gz)
        gz_ok = raw_dir is not None and os.path.exists(os.path.join(raw_dir, GZ_NAME)) \
            and not os.path.exists(old_json)
        check('4a. .json entfernt, .gz ins Staging gelegt (API kann .gz nicht)', gz_ok,
              f'staging={raw_dir}')
        before = newest_archive_mtime(upload_id)
        api_json('POST', f'/uploads/{upload_id}/action/process', b'{}')
        status = wait_process_done(upload_id, after_mtime=before)
        ok4, det4 = verify_results(upload_id, '.gz-Lauf', expect_gz=True)
        check('4b. result_* aus .gz verarbeitet', ok4, f'{det4} status={status}')

        # 5) Ergebnis-Datei im Upload + beide Läufe ok
        names = raw_names(upload_id)
        check('5a. .gz-Ergebnis im Upload (realer Endzustand)',
              GZ_NAME in names and JSON_NAME not in names, f'names={names}')
        check('5b. .json UND .gz je erfolgreich verarbeitet', ok3 and ok4,
              'beide Pfade produzierten result_*-Felder + Figuren')

        print()
        if all(passed):
            print(f'=== E2E {MARKER}: ALLE CHECKS BESTANDEN (.json UND .gz) ===')
        else:
            print(f'=== E2E {MARKER}: {passed.count(False)} CHECK(S) FEHLGESCHLAGEN ===')
            sys.exit(1)
    finally:
        if upload_id:
            st, _ = api_raw('DELETE', f'/uploads/{upload_id}')
            print(f'Cleanup: Test-Upload {upload_id} geloescht (http={st})')


if __name__ == '__main__':
    main()
