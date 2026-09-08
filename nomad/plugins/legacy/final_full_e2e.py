#!/usr/bin/env python3
"""Create a realistic TGA CSV, new elab item, upload to NOMAD, verify elabFTW output."""
import sys, requests, json, time, os, warnings
from datetime import datetime
warnings.filterwarnings("ignore")

ELAB_URL = "https://elntest.ub.tum.de/api/v2"
API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"
PAT = open("/app/.nomad_pat").read().strip()
elab_headers = {"Authorization": API_KEY, "Content-Type": "application/json"}
nomad_headers = {"Authorization": f"Bearer {PAT}"}

# Step 1: Create a realistic TGA CSV with metadata header
print("=== Step 1: Create realistic TGA CSV ===")
csv = """Instrument type\tTGA
Instrument name\tDiscovery TGA 5500
Sample name\tPolymer-X
Sample weight\t53.504 mg
Pan type\tPlatinum HT
Gas atmosphere\tN2
Heating rate\t10.00 K/min
Temperature end\t600.00 °C
Operator\tKolja
Procedure name\tRamp 10K to 600C

Index\tTime/s\tTime/Min\tValue/mg\tTemp./C\tDelta/C/min\tSample Weight/mg
1\t0.0\t0.00\t53.504\t35.00\t0.00\t53.504
2\t6.0\t0.10\t53.502\t36.00\t10.00\t53.504
3\t12.0\t0.20\t53.500\t37.00\t10.00\t53.504
4\t18.0\t0.30\t53.498\t38.00\t10.00\t53.504
5\t24.0\t0.40\t53.496\t39.00\t10.00\t53.504
6\t30.0\t0.50\t53.494\t40.00\t10.00\t53.504
7\t60.0\t1.00\t53.466\t45.00\t0.17\t53.504
8\t120.0\t2.00\t53.426\t50.00\t0.00\t53.504
9\t180.0\t3.00\t53.385\t55.00\t0.00\t53.504
10\t300.0\t5.00\t53.310\t65.00\t0.00\t53.504
11\t600.0\t10.00\t53.093\t90.00\t0.17\t53.504
12\t900.0\t15.00\t52.811\t115.00\t0.17\t53.504
13\t1200.0\t20.00\t52.034\t140.00\t0.17\t53.504
14\t1500.0\t25.00\t47.896\t165.00\t0.17\t53.504
15\t1800.0\t30.00\t43.224\t190.00\t0.17\t53.504
16\t2100.0\t35.00\t40.845\t215.00\t0.17\t53.504
17\t2400.0\t40.00\t40.031\t240.00\t0.17\t53.504
18\t2700.0\t45.00\t39.800\t265.00\t0.17\t53.504
19\t3000.0\t50.00\t39.696\t290.00\t0.17\t53.504
20\t3300.0\t55.00\t39.629\t315.00\t0.17\t53.504
21\t3600.0\t60.00\t39.589\t335.00\t0.17\t53.504
"""

# Step 2: Create new elabFTW item
print("=== Step 2: Create elabFTW item ===")
ts = datetime.now().strftime("%H%M%S")
cr = requests.post(f"{ELAB_URL}/items", headers=elab_headers,
    json={"title": f"Polymer-X {ts}", "category": "5", "status": "67",
          "metadata": json.dumps({
              "procedure_name": "Ramp 10K to 600C", "sample_name": "Polymer-X",
              "sample_mass_mg": 53.504, "pan_type": "Platinum HT",
              "gas_atmosphere": "N2", "operator": "Kolja",
              "heating_rate": "10.00 K/min", "temperature_end": "600.00 C"
          })}, verify=False, timeout=15)
loc = cr.headers.get("Location", "")
item_id = loc.split("/")[-1] if loc else "?"
print(f"Item {item_id}: {cr.status_code}")

# Step 3: Upload CSV to NOMAD
print("\n=== Step 3: Upload to NOMAD ===")
filename = f"Polymer-X_item{item_id}.csv"
r = requests.post(NOMAD_URL + "/uploads", headers=nomad_headers,
    files={"file": (filename, csv, "text/csv")}, timeout=15)
print(f"Upload: {r.status_code}")
time.sleep(5)

# Get upload ID
ru = requests.get(NOMAD_URL + "/uploads?order=desc&per_page=2", headers=nomad_headers, timeout=10)
uid = None
for u in ru.json().get("data", []):
    if f"item{item_id}" in u.get("filename", ""):
        uid = u.get("upload_id", "")
        break
if not uid:
    uid = ru.json().get("data", [{}])[0].get("upload_id", "")

# Step 4: Wait for NOMAD parser
print("\n=== Step 4: Wait for NOMAD parser ===")
for i in range(18):
    time.sleep(10)
    ru = requests.get(NOMAD_URL + f"/uploads/{uid}", headers=nomad_headers, timeout=10)
    u = ru.json().get("data", ru.json())
    proc = u.get("process_status", "?")
    ent = u.get("entries", 0)
    run = u.get("process_running", False)
    print(f"  {i}: proc={proc} entries={ent}")
    if not run and proc in ("SUCCESS", "FAILURE"):
        break

print(f"\nNOMAD: entries={u.get('entries',0)} status={u.get('process_status','?')}")

# Step 5: Wait for processor to pick it up
print("\n=== Step 5: Wait for processor ===")
time.sleep(20)

# Check processor logs
print("\n=== Step 6: Check processor log ===")
import subprocess
log = subprocess.run(["tail", "-5", "/app/logs/tga-nomad-processor.log"], capture_output=True, text=True, timeout=5)
print(log.stdout)

# Step 7: Check elabFTW result
print("\n=== Step 7: Check elabFTW item ===")
time.sleep(5)
r = requests.get(f"{ELAB_URL}/items/{item_id}", headers=elab_headers, verify=False, timeout=15)
item = r.json()
body = item.get("body") or ""
print(f"Body length: {len(body)}")
print(f"Has parameters: {'Measurement Parameters' in body}")
print(f"Has plot: {'<img' in body}")
print(f"Has NOMAD link: {'NOMAD' in body}")

# Check uploads
r = requests.get(f"{ELAB_URL}/items/{item_id}/uploads", headers=elab_headers, verify=False, timeout=15)
uploads = r.json() if isinstance(r.json(), list) else []
print(f"Uploads: {len(uploads)} - {[u.get('real_name') for u in uploads]}")

print(f"\n=== LINKS ===")
print(f"elabFTW: https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")
print(f"NOMAD upload: {uid}")
if u.get("entries", 0) > 0:
    print(f"NOMAD entry: (check GUI for entry linked to upload {uid})")
