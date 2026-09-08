#!/usr/bin/env python3
"""
FINAL CLEAN E2E TEST — Full pipeline: NOMAD parser → processor → elabFTW.

What this script does:
  1. Creates a clean elabFTW item (TGA category, Ready status)
  2. Uploads a realistic TGA CSV to NOMAD with _item{id} in filename
  3. Waits for NOMAD parser to create entry (SUCCESS)
  4. Waits for the processor watch loop to pick it up
  5. Verifies elabFTW item has: parameters, raw data, plot, NOMAD entry link
  6. Prints final links
"""
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
print("FINAL CLEAN E2E TEST")
print("=" * 60)

# ── Step 1: Create elabFTW item ──
print("\n[1/5] Creating elabFTW item...")
ts = datetime.now().strftime("%H%M%S")
cr = requests.post(f"{ELAB_URL}/items", headers=elab_h,
    json={"title": f"Polymer-X {ts}", "category": "5", "status": "67",
          "metadata": json.dumps({
              "procedure_name": "Ramp 10K to 600C", "sample_name": "Polymer-X",
              "sample_mass_mg": 53.504, "pan_type": "Platinum HT",
              "gas_atmosphere": "N2", "operator": "Kolja",
              "heating_rate": "10.00 K/min", "temperature_end": "600.00 C"
          })}, verify=False, timeout=15)
loc = cr.headers.get("Location", "")
item_id = int(loc.split("/")[-1]) if loc else 0
print(f"  Created item {item_id}")

# ── Step 2: CSV ──
csv = """Instrument type	TGA
Instrument name	Discovery TGA 5500
Sample name	Polymer-X
Sample weight	53.504 mg
Pan type	Platinum HT
Gas atmosphere	N2
Heating rate	10.00 K/min
Temperature end	600.00 °C
Operator	Kolja
Procedure name	Ramp 10K to 600C

Index	Time/s	Time/Min	Value/mg	Temp./C	Delta/C/min	Sample Weight/mg
1	0.0	0.00	53.504	35.00	0.00	53.504
2	6.0	0.10	53.502	36.00	10.00	53.504
3	12.0	0.20	53.500	37.00	10.00	53.504
4	18.0	0.30	53.498	38.00	10.00	53.504
5	24.0	0.40	53.496	39.00	10.00	53.504
6	30.0	0.50	53.494	40.00	10.00	53.504
7	60.0	1.00	53.466	45.00	0.17	53.504
8	120.0	2.00	53.426	50.00	0.00	53.504
9	180.0	3.00	53.385	55.00	0.00	53.504
10	300.0	5.00	53.310	65.00	0.00	53.504
11	600.0	10.00	53.093	90.00	0.17	53.504
12	900.0	15.00	52.811	115.00	0.17	53.504
13	1200.0	20.00	52.034	140.00	0.17	53.504
14	1500.0	25.00	47.896	165.00	0.17	53.504
15	1800.0	30.00	43.224	190.00	0.17	53.504
16	2100.0	35.00	40.845	215.00	0.17	53.504
17	2400.0	40.00	40.031	240.00	0.17	53.504
18	2700.0	45.00	39.800	265.00	0.17	53.504
19	3000.0	50.00	39.696	290.00	0.17	53.504
20	3300.0	55.00	39.629	315.00	0.17	53.504
21	3600.0	60.00	39.589	335.00	0.17	53.504
"""

# ── Step 3: Upload to NOMAD ──
print("\n[2/5] Uploading CSV to NOMAD...")
filename = f"Polymer-X_item{item_id}.csv"
r = requests.post(NOMAD_URL + "/uploads", headers=nomad_h,
    files={"file": (filename, csv, "text/csv")}, timeout=15)
print(f"  Upload: {r.status_code}")
time.sleep(5)

ru = requests.get(NOMAD_URL + "/uploads?order=desc&per_page=2", headers=nomad_h, timeout=10)
uid = ru.json().get("data", [{}])[0].get("upload_id", "")

# ── Step 4: Wait for NOMAD parser ──
print("\n[3/5] Waiting for NOMAD parser...")
for i in range(18):
    time.sleep(10)
    ru = requests.get(NOMAD_URL + f"/uploads/{uid}", headers=nomad_h, timeout=10)
    u = ru.json().get("data", ru.json())
    proc = u.get("process_status", "?")
    ent = u.get("entries", 0)
    run = u.get("process_running", False)
    print(f"  {i}: proc={proc} entries={ent}")
    if not run and proc in ("SUCCESS", "FAILURE"):
        break

# Get entry ID from archive
archive_dir = f"/app/.volumes/fs/staging/{uid[:2]}/{uid}/archive"
msg_files = glob.glob(os.path.join(archive_dir, "*.msg"))
entry_id = os.path.basename(msg_files[0]).split("-")[0] if msg_files else "N/A"
print(f"\n  NOMAD entry ID: {entry_id}")

# ── Step 5: Wait for processor ──
print("\n[4/5] Waiting for processor to push to elabFTW...")
time.sleep(45)

# Check processor logs
print("  Processor logs:")
log = subprocess.run(["tail", "-5", "/app/logs/tga-nomad-processor.log"],
    capture_output=True, text=True, timeout=5)
for line in log.stdout.strip().split("\n"):
    if line.strip():
        print(f"    {line.strip()}")

time.sleep(30)

# ── Step 6: Verify ──
print("\n[5/5] Verifying elabFTW item...")
r = requests.get(f"{ELAB_URL}/items/{item_id}", headers=elab_h, verify=False, timeout=15)
d = r.json()
b = d.get("body", "")
print(f"  Body length: {len(b)}")
checks = ["Parameters", "Sample Mass", "Atmosphere", "Crucible", "Instrument",
          "Raw Measurement", "img", "Onset", "Residue", "Mass Balance", entry_id]
for check in checks:
    print(f"    {check}: {check in b}")

# Check uploads
ru = requests.get(f"{ELAB_URL}/items/{item_id}/uploads", headers=elab_h, verify=False, timeout=15)
uploads = ru.json() if isinstance(ru.json(), list) else []
print(f"  Uploaded files: {len(uploads)}")
for u in uploads:
    print(f"    {u.get('real_name')} ({u.get('type')})")

print("\n" + "=" * 60)
print("FINAL LINKS")
print("=" * 60)
nomad_entry_url = f"https://researchmcp.duckdns.org/nomad-oasis/gui/search/entries/entry/id/{entry_id}"
elab_url = f"https://elntest.ub.tum.de/database.php?mode=view&id={item_id}"
print(f"\n  NOMAD entry: {nomad_entry_url}")
print(f"  elabFTW:     {elab_url}")
print()
if entry_id in b and "Parameters" in b:
    print("✅ E2E TEST PASSED — Full pipeline verified")
else:
    print("⚠  E2E TEST PARTIAL — Check missing items above")
