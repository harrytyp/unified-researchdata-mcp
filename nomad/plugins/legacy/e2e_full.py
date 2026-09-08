#!/usr/bin/env python3
"""Full E2E pipeline verification."""
import sys, requests, json, time

NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"

try:
    PAT = open("/app/.nomad_pat").read().strip()
except FileNotFoundError:
    PAT = open("/app/plugins/.nomad_pat").read().strip()

headers = {"Authorization": f"Bearer {PAT}"}

# Step 1: Clean old test uploads
print("=== Step 1: Clean old test uploads ===")
old = ["Yc7SuqkOSxGN73HMHm158A", "HRkY_YymSwCVgbD_e_9E",
       "wtCvuJaDQe2rt5ba5efL", "f-SL6pV6QoqG8QY0cGo99w",
       "xqiSLLs3R3qK0p8VqRkFVQ"]
for uid in old:
    try:
        resp = requests.delete(f"{NOMAD_URL}/uploads/{uid}", headers=headers)
        if resp.status_code in (200, 204):
            print(f"  Deleted {uid}")
    except:
        pass

# Step 2: Upload test TGA CSV
print("\n=== Step 2: Upload TGA CSV ===")
csv_lines = ["Index,Time/s,Time/Min,Value/mg,Temp./C,Delta/C/min,Sample Weight/mg"]
for i in range(1, 61):
    t = (i - 1) * 60
    val = round(53.5 - (i - 1) * (53.5 - 39.6) / 60, 3)
    temp = round(35 + (i - 1) * 300 / 60, 1)
    csv_lines.append(f"{i},{t},{t/60:.2f},{val:.3f},{temp:.1f},1.67,53.504")
csv_content = "\n".join(csv_lines)

resp = requests.post(
    f"{NOMAD_URL}/uploads",
    headers=headers,
    files={"file": ("TGA_E2E_Test.csv", csv_content, "text/csv")}
)
print(f"Upload status: {resp.status_code}")
if resp.status_code != 200:
    print(f"Upload failed: {resp.text[:200]}")
    sys.exit(1)

# Step 3: Find upload ID
print("\n=== Step 3: Poll for processing ===")
time.sleep(8)
ru = requests.get(f"{NOMAD_URL}/uploads?order=desc&per_page=3", headers=headers)
data = ru.json().get("data", [])
upload_id = None
for u in data:
    if "TGA_E2E_Test" in u.get("filename", u.get("upload_name", "")):
        upload_id = u.get("upload_id", "")
        break
if not upload_id and data:
    upload_id = data[0].get("upload_id", "")
    print(f"  Using latest: {upload_id} ({data[0].get('filename', '?')})")
else:
    print(f"  Found: {upload_id}")

if not upload_id:
    print("FAILED: No upload ID")
    sys.exit(1)

# Step 4: Wait for processing
for i in range(30):
    time.sleep(10)
    ru = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers)
    if ru.status_code == 200:
        u = ru.json()
        if isinstance(u, dict) and "data" in u:
            u = u["data"]
        proc = u.get("process_status", "?")
        ent = u.get("entries", 0)
        run = u.get("process_running", False)
        print(f"  {i:2d}: proc={proc:10s} run={str(run):5s} entries={ent}")
        if not run and proc in ("SUCCESS", "FAILURE"):
            break
else:
    print("\n  TIMEOUT after 300s")

# Step 5: Final result
print("\n=== Step 5: Final Result ===")
rd = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers)
u = rd.json().get("data", rd.json())
ent = u.get("entries", 0)
proc = u.get("process_status", "?")
err = u.get("errors", [])
print(f"  Upload: {upload_id}")
print(f"  File: {u.get('filename', u.get('upload_name', '?'))}")
print(f"  Status: {proc}")
print(f"  Entries: {ent}")
print(f"  Errors: {len(err) if isinstance(err, list) else err}")
if int(ent) > 0:
    print("\n  SUCCESS: Parser created entries!")
    # Get entry details
    eresp = requests.get(f"{NOMAD_URL}/entries?upload_id={upload_id}", headers=headers)
    print(f"  Entry details: {eresp.text[:500]}")
else:
    print("\n  FAILED: No entries created")
    print(f"  Full upload data: {json.dumps(u, indent=2)[:1000]}")
