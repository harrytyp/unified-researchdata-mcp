#!/usr/bin/env python3
"""Create elabFTW item from template and upload matching CSV to NOMAD."""
import sys, requests, json, time, os, warnings
from datetime import datetime
warnings.filterwarnings("ignore")

ELAB_URL = "https://elntest.ub.tum.de/api/v2"
API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
# elabFTW uses API key directly as auth token without "Bearer" prefix
headers = {"Authorization": API_KEY, "Content-Type": "application/json"}

# Step 1: Find TGA items in Ready status (67) or create one
print("=== Finding TGA items in Ready status ===")
resp = requests.get(f"{ELAB_URL}/items?cat=5&limit=50", headers=headers, verify=False, timeout=15)
print(f"List items: {resp.status_code}")
if resp.status_code == 200:
    items = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])
    ready = []
    for item in items:
        sid = item.get("status", item.get("status_id", 0))
        if str(sid) == "67":
            ready.append(item)
            print(f"  Ready: ID {item.get('id')} - {item.get('title', '?')}")
    
    if ready:
        item_id = ready[0]["id"]
        print(f"\nUsing existing item {item_id}")
    else:
        print("\nNo Ready items found. Creating a new one...")
        create_data = {
            "title": f"E2E Test {datetime.now().strftime('%H%M%S')}",
            "category": "5",
            "status": "67",
            "body": "<p>TGA measurement - E2E test</p>",
            "metadata": json.dumps({
                "procedure_name": "Test",
                "sample_name": "E2E Test Sample",
                "sample_mass_mg": 53.504,
                "pan_type": "Platinum HT",
                "gas_atmosphere": "N2"
            })
        }
        cr = requests.post(f"{ELAB_URL}/items", headers=headers,
                          json=create_data, verify=False, timeout=15)
        print(f"Create: {cr.status_code} {cr.text[:200]}")
        if cr.status_code in (200, 201):
            new_item = cr.json()
            item_id = new_item.get("id")
            print(f"Created item {item_id}")
        else:
            print("FAILED to create item")
            sys.exit(1)
else:
    print(f"Error: {resp.status_code} {resp.text[:200]}")
    # Try with Bearer prefix
    print("\nTrying with Bearer prefix...")
    headers2 = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp2 = requests.get(f"{ELAB_URL}/items?cat=5&limit=5", headers=headers2, verify=False, timeout=15)
    print(f"Bearer auth: {resp2.status_code} {resp2.text[:200]}")
    sys.exit(1)

item_id = int(item_id) if item_id else None
print(f"\n=== elabFTW Item ID: {item_id} ===")
print(f"URL: https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")

# Step 2: Upload a matching CSV to NOMAD
print("\n=== Uploading TGA CSV to NOMAD ===")
NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"
PAT = open("/app/.nomad_pat").read().strip()
nomad_headers = {"Authorization": f"Bearer {PAT}"}

csv_lines = ["Index,Time/s,Time/Min,Value/mg,Temp./C,Delta/C/min,Sample Weight/mg"]
for i in range(1, 21):
    t = (i - 1) * 180
    val = round(53.5 - (i - 1) * (53.5 - 39.6) / 20, 3)
    temp = round(35 + (i - 1) * 300 / 20, 1)
    csv_lines.append(f"{i},{t},{t/60:.2f},{val:.3f},{temp:.1f},1.67,53.504")
csv_content = "\n".join(csv_lines)

# Filename includes _item{id} for the processor to match
filename = f"E2E_Final_item{item_id}.csv"
resp = requests.post(
    f"{NOMAD_URL}/uploads",
    headers=nomad_headers,
    files={"file": (filename, csv_content, "text/csv")},
    timeout=15
)
print(f"Upload: {resp.status_code}")
if resp.status_code != 200:
    print(f"Upload failed: {resp.text[:200]}")
    sys.exit(1)

# Poll for processing
time.sleep(5)
ru = requests.get(f"{NOMAD_URL}/uploads?order=desc&per_page=2", headers=nomad_headers, timeout=10)
uid = None
for u in ru.json().get("data", []):
    if f"item{item_id}" in u.get("filename", ""):
        uid = u.get("upload_id", "")
        break
if not uid:
    uid = ru.json().get("data", [{}])[0].get("upload_id", "")

print(f"\nPolling upload {uid}...")
for i in range(18):
    time.sleep(10)
    ru = requests.get(f"{NOMAD_URL}/uploads/{uid}", headers=nomad_headers, timeout=10)
    u = ru.json().get("data", ru.json())
    proc = u.get("process_status", "?")
    ent = u.get("entries", 0)
    run = u.get("process_running", False)
    print(f"  {i:2d}: proc={proc:10s} run={str(run):5s} entries={ent}")
    if not run and proc in ("SUCCESS", "FAILURE"):
        break

print(f"\n=== Final ===")
print(f"NOMAD Upload: {uid} -> entries={u.get('entries',0)} status={u.get('process_status','?')}")
print(f"elabFTW Item: https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")
