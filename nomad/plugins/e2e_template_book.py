#!/usr/bin/env python3
"""E2E with elabFTW template item + NOMAD xlsx upload."""
import sys, requests, json, time, os, glob, warnings
from datetime import datetime
warnings.filterwarnings("ignore")

ELAB_URL = "https://elntest.ub.tum.de/api/v2"
NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"
# Read elabFTW API key from environment or file
import os as _os
if _os.environ.get("ELABFTW_API_KEY"):
    API_KEY = _os.environ["ELABFTW_API_KEY"]
else:
    # Fallback to hardcoded key for container usage
    API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
PAT = open("/app/.nomad_pat").read().strip()

print("=" * 60)
print("E2E TEST — Template item + xlsx upload")
print("=" * 60)

elab_h = {"Authorization": API_KEY, "Content-Type": "application/json"}
nomad_h = {"Authorization": f"Bearer {PAT}"}

# [1] Create item from template
print("\n[1] Creating elabFTW item from TGA template...")
ts = datetime.now().strftime("%H%M%S")
cr = requests.post(ELAB_URL + "/items", headers=elab_h,
    json={"title": f"TGA E2E {ts}", "category": "5", "status": "67",
          "metadata": json.dumps({
              "procedure_name": "Ramp 10K to 600C",
              "sample_name": "Polymer-X",
              "sample_mass_mg": 53.504})},
    verify=False, timeout=15)
item_id = int(cr.headers.get("Location","").split("/")[-1])
print(f"  Created item {item_id}")

# [2] Book the item
print("\n[2] Booking elabFTW item...")
bk = requests.post(ELAB_URL + f"/items/{item_id}/status", headers=elab_h,
    data={"status": "72"}, verify=False, timeout=15)
print(f"  Book: {bk.status_code}")
ru = requests.get(ELAB_URL + f"/items/{item_id}", headers=elab_h, verify=False, timeout=15)
s = ru.json().get("status", {})
print(f"  Status: {s.get('title', s) if isinstance(s, dict) else s}")

# [3] Upload xlsx
print("\n[3] Uploading real TGA xlsx to NOMAD...")
xlsx_path = "/app/plugins/sample_files/TGA_AC1BAPO UV CURED 5KMIN 1000C N2.xlsx"
filename = f"Polymer-X_item{item_id}.xlsx"
with open(xlsx_path, "rb") as f:
    xlsx_data = f.read()
r = requests.post(NOMAD_URL + "/uploads", headers=nomad_h,
    files={"file": (filename, xlsx_data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    timeout=15)
print(f"  Upload: {r.status_code}")
time.sleep(5)

ru = requests.get(NOMAD_URL + "/uploads?order=desc&per_page=2", headers=nomad_h, timeout=10)
uid = ru.json().get("data", [{}])[0].get("upload_id", "")
print(f"  Upload ID: {uid}")

# [4] Wait for parser
print("\n[4] Waiting for NOMAD parser...")
for i in range(18):
    time.sleep(10)
    ru = requests.get(NOMAD_URL + f"/uploads/{uid}", headers=nomad_h, timeout=10)
    u = ru.json().get("data", ru.json())
    proc = u.get("process_status", "?")
    ent = u.get("entries", 0)
    run = u.get("process_running", False)
    print(f"  {i}: {proc} entries={ent}")
    if not run and proc in ("SUCCESS", "FAILURE"):
        break

archive_dir = f"/app/.volumes/fs/staging/{uid[:2]}/{uid}/archive"
msg = glob.glob(os.path.join(archive_dir, "*.msg"))
entry_id = os.path.basename(msg[0]).split("-")[0] if msg else "N/A"
print(f"  Entry ID: {entry_id}")

# [5] Push to elabFTW if entry created
if entry_id != "N/A":
    print("\n[5] Processing and pushing to elabFTW...")
    sys.path.insert(0, "/app/plugins")
    from instrument_data.processor import process_tga_file
    raw_dir = f"/app/.volumes/fs/staging/{uid[:2]}/{uid}/raw"
    files = os.listdir(raw_dir)
    filepath = os.path.join(raw_dir, files[0])
    r = process_tga_file(filepath=filepath, elab_item_id=item_id,
        upload_id=uid, elabftw_api_key=API_KEY, elabftw_team=29)
    print(f"  Result: {r.get('status')}")

# [6] Verify
print("\n[6] Verifying elabFTW item...")
ru = requests.get(ELAB_URL + f"/items/{item_id}", headers=elab_h, verify=False, timeout=15)
b = ru.json().get("body", "")
print(f"  Body: {len(b)} chars")
for s in ["Parameters", "Atmosphere", "Raw Measurement", "Plot", "Residue", "NOMAD Entry"]:
    print(f"    {s}: {'OK' if s in b else 'MISSING'}")
ru2 = requests.get(ELAB_URL + f"/items/{item_id}/uploads", headers=elab_h, verify=False, timeout=15)
uploads = ru2.json() if isinstance(ru2.json(), list) else []
print(f"  Uploaded: {len(uploads)} files")
print(f"\nelabFTW: https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")
