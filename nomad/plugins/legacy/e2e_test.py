#!/usr/bin/env python3
"""E2E test: upload TGA CSV to NOMAD, check if parser creates entries."""
import sys, requests, json, time, re

NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"

try:
    PAT = open("/app/.nomad_pat").read().strip()
except FileNotFoundError:
    PAT = open("/app/plugins/.nomad_pat").read().strip()

headers = {"Authorization": f"Bearer {PAT}"}

# Generate test TGA data
rows = []
for i in range(1, 201):
    t = (i - 1) * 6  # 6 second intervals = ~20 min total
    tm = t / 60
    val = 53.504 - (53.504 - 39.589) * (i - 1) / 199  # linear from 53.504 to 39.589
    temp = 35.0 + 300.0 * (i - 1) / 199  # 35C to 335C
    rows.append(f"{i},{t},{tm:.2f},{val:.3f},{temp:.2f},1.67,53.504")

csv_content = "Index,Time/s,Time/Min,Value/mg,Temp./C,Delta/C/min,Sample Weight/mg\n"
csv_content += "\n".join(rows)

# Step 1: Upload
print("=== Step 1: Upload TGA CSV ===")
resp = requests.post(
    f"{NOMAD_URL}/uploads",
    headers=headers,
    files={"file": ("tga_parser_test.csv", csv_content, "text/csv")}
)
print(f"Upload status: {resp.status_code}")

# Step 2: Wait and poll for processing
print("\n=== Step 2: Poll for processing ===")
time.sleep(5)

# Find the latest upload
ru = requests.get(f"{NOMAD_URL}/uploads?order=desc&per_page=5", headers=headers)
upload_id = None
if ru.status_code == 200:
    data = ru.json()
    for u in data.get("data", []):
        if "tga_parser_test" in u.get("filename", ""):
            upload_id = u["upload_id"]
            break
    if not upload_id and data.get("data"):
        upload_id = data["data"][0]["upload_id"]
        print(f"No match, using latest: {upload_id} {data['data'][0].get('filename','')}")

print(f"Upload ID: {upload_id}")

if upload_id:
    for i in range(20):
        time.sleep(5)
        ru = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers)
        if ru.status_code == 200:
            u = ru.json()
            if isinstance(u, dict) and "data" in u:
                u = u["data"]
            entries = u.get("entries", 0)
            errors = u.get("errors", [])
            proc = u.get("process_status", "unknown")
            name = u.get("upload_name", u.get("filename", ""))
            print(f"  Poll {i}: entries={entries} errors={len(errors) if isinstance(errors, list) else errors} status={proc} file={name}")
            if entries and int(entries) > 0:
                print(f"\n  SUCCESS: Parser created {entries} entries!")
                # Get entry details
                eresp = requests.get(f"{NOMAD_URL}/entries?upload_id={upload_id}", headers=headers)
                if eresp.status_code == 200:
                    ejson = eresp.json()
                    print(f"  Entries: {json.dumps(ejson, indent=2)[:1000]}")
                break
            if proc == "FAILURE" or errors:
                print(f"  FAILED: {u}")
                break
    else:
        print(f"\n  TIMEOUT: Not processed after 100s")
        rd = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers)
        if rd.status_code == 200:
            print(f"  Final state: {json.dumps(rd.json(), indent=2)[:1500]}")
else:
    print("FAILED: Could not find upload")
    # List all uploads
    ru = requests.get(f"{NOMAD_URL}/uploads", headers=headers)
    if ru.status_code == 200:
        print(f"All uploads: {json.dumps(ru.json(), indent=2)[:1000]}")
