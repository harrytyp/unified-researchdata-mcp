#!/usr/bin/env python3
"""Final E2E with real sample files."""
import sys, requests, json, time, os, glob, warnings, subprocess
from datetime import datetime
warnings.filterwarnings("ignore")

ELAB_URL = "https://elntest.ub.tum.de/api/v2"
API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"
PAT = open("/app/.nomad_pat").read().strip()
elab_h = {"Authorization": API_KEY, "Content-Type": "application/json"}
nomad_h = {"Authorization": f"Bearer {PAT}"}

print("=" * 60)
print("FINAL E2E TEST — Real Sample File")
print("=" * 60)

# ── Step 1: Create elabFTW item ──
print("\n[1] Creating elabFTW item...")
ts = datetime.now().strftime("%H%M%S")
cr = requests.post(f"{ELAB_URL}/items", headers=elab_h,
    json={"title": f"AC1BAPO TGA {ts}", "category": "5", "status": "67",
          "metadata": json.dumps({})}, verify=False, timeout=15)
item_id = int(cr.headers.get("Location","").split("/")[-1])
print(f"  Created item {item_id}")

# ── Step 2: Upload real xlsx to NOMAD ──
print("\n[2] Uploading real TGA xlsx to NOMAD...")
xlsx_path = "/app/plugins/sample_files/TGA_AC1BAPO UV CURED 5KMIN 1000C N2.xlsx"
filename = f"AC1BAPO_TGA_item{item_id}.xlsx"
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

# ── Step 3: Wait for NOMAD parser ──
print("\n[3] Waiting for NOMAD parser...")
for i in range(18):
    time.sleep(10)
    ru = requests.get(NOMAD_URL + f"/uploads/{uid}", headers=nomad_h, timeout=10)
    u = ru.json().get("data", ru.json())
    if not u.get("process_running", False):
        break
print(f"  Entries: {u.get('entries',0)}, Status: {u.get('process_status')}")

# Get entry ID from archive
archive_dir = f"/app/.volumes/fs/staging/{uid[:2]}/{uid}/archive"
msg = glob.glob(os.path.join(archive_dir, "*.msg"))
entry_id = os.path.basename(msg[0]).split("-")[0] if msg else "N/A"
print(f"  Entry ID: {entry_id}")

# ── Step 4: Process and push to elabFTW ──
print("\n[4] Processing and pushing to elabFTW...")
sys.path.insert(0, "/app/plugins")
from instrument_data.processor import process_tga_file
raw_dir = f"/app/.volumes/fs/staging/{uid[:2]}/{uid}/raw"
csv_files = os.listdir(raw_dir)
csv_path = os.path.join(raw_dir, csv_files[0])

r = process_tga_file(
    filepath=csv_path,
    elab_item_id=item_id,
    upload_id=uid,
    elabftw_api_key=API_KEY,
    elabftw_team=29,
)
print(f"  Result: {r.get('status')}")

# ── Step 5: Verify ──
print("\n[5] Verifying elabFTW item...")
ru = requests.get(f"{ELAB_URL}/items/{item_id}", headers=elab_h, verify=False, timeout=15)
b = ru.json().get("body", "")
print(f"  Body: {len(b)} chars")
checks = [("Parameters", "Parameters" in b), ("Atmosphere", "Atmosphere" in b),
          ("Raw Measurement", "Raw" in b), ("Plot", "<img" in b),
          ("Residue", "Residue" in b), ("NOMAD entry", entry_id in b if entry_id else False)]
for name, ok in checks:
    print(f"    {name}: {'OK' if ok else 'MISSING'}")

print(f"\n{'='*60}")
print(f"elabFTW:     https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")
print(f"NOMAD entry: https://researchmcp.ducknss.org/nomad-oasis/gui/search/entries/entry/id/{entry_id}")
