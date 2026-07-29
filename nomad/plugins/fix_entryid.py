import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/processor.py"
with open(path) as f:
    c = f.read()

# Remove the badly-inserted entry_id block
old_bad = '\nentry_id = ""    if upload_id:        try:            import requests as _req2            resp = _req2.get("http://localhost:8000/nomad-oasis/api/v1/entries?upload_id=" + upload_id,                headers={"Authorization": "Bearer " + os.environ.get("NOMAD_PAT", "")}, timeout=10)            if resp.status_code == 200:                edata = resp.json()                if edata.get("data"):                    entry_id = str(edata["data"][0].get("entry_id", ""))        except: pass\n\n    elab = ElabftwClient('

if old_bad in c:
    c = c.replace(old_bad, '\n\n    # Look up NOMAD entry ID from upload\n    entry_id = ""\n    if upload_id:\n        try:\n            import requests as _req2\n            pat = os.environ.get("NOMAD_PAT", "")\n            if pat:\n                resp = _req2.get(\n                    f"http://localhost:8000/nomad-oasis/api/v1/entries?upload_id={upload_id}",\n                    headers={"Authorization": f"Bearer {pat}"},\n                    timeout=10,\n                )\n                if resp.status_code == 200:\n                    edata = resp.json()\n                    if edata.get("data"):\n                        entry_id = str(edata["data"][0].get("entry_id", ""))\n        except Exception:\n            pass\n\n    elab = ElabftwClient(')
    with open(path, "w") as f:
        f.write(c)
    print("Fixed entry_id lookup")
else:
    print("WARNING: Bad block not found")
    # Check what's actually there
    with open(path) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if "entry_id" in line:
            print(f"  {i+1}: {line.rstrip()}")
