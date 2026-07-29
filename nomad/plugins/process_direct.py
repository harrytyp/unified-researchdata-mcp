#!/usr/bin/env python3
"""Process a NOMAD upload directly using internal Python API,
bypassing Temporal workflow. Useful when Temporal workers aren't available."""
import sys, os, json, requests, time, shutil

NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"

# Get PAT
try:
    PAT = open("/app/.nomad_pat").read().strip()
except FileNotFoundError:
    PAT = open("/app/plugins/.nomad_pat").read().strip()
headers = {"Authorization": f"Bearer {PAT}"}

# Step 1: Upload a fresh TGA CSV
print("=== Uploading TGA CSV ===")
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
    files={"file": ("TGA_Direct.csv", csv_content, "text/csv")},
    timeout=15
)
print(f"Upload: {resp.status_code}")
if resp.status_code != 200:
    print(f"FAILED: {resp.text[:200]}")
    sys.exit(1)

# Step 2: Get upload_id
time.sleep(5)
ru = requests.get(f"{NOMAD_URL}/uploads?order=desc&per_page=1", headers=headers, timeout=10)
upload_id = ru.json().get("data", [{}])[0].get("upload_id", "")
print(f"Upload ID: {upload_id}")

# Step 3: Process the upload directly using internal API
print("\n=== Processing upload directly ===")
# We need to run inside the NOMAD container to use internal Python API
# Use the pat to authenticate
proc_url = f"{NOMAD_URL}/uploads/{upload_id}/process"
pr = requests.post(
    proc_url,
    headers={**headers, "Content-Type": "application/json"},
    json={},
    timeout=30
)
print(f"Process trigger: {pr.status_code} {pr.text[:200]}")

# Step 4: Poll
print("\n=== Polling ===")
for i in range(30):
    time.sleep(10)
    ru = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers, timeout=10)
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

# Step 5: Final
print("\n=== Final ===")
rd = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers, timeout=10)
u = rd.json().get("data", rd.json())
print(f"Status: {u.get('process_status', '?')}")
print(f"Entries: {u.get('entries', 0)}")
if int(u.get('entries', 0)) > 0:
    print("SUCCESS: Parser created entries!")
    eresp = requests.get(f"{NOMAD_URL}/entries?upload_id={upload_id}", headers=headers, timeout=10)
    print(f"Entries: {eresp.text[:500]}")
else:
    print("FAILED: No entries created")
