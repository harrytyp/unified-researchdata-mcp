#!/usr/bin/env python3
"""Process a NOMAD upload using the internal Python API.
This bypasses Temporal and processes directly in the app container."""
import sys, os, json, time

sys.path.insert(0, "/app/plugins")

# Get the upload ID from args or use latest
import requests
NOMAD_URL = "http://localhost:8000/nomad-oasis/api/v1"
PAT = open("/app/.nomad_pat").read().strip()
headers = {"Authorization": f"Bearer {PAT}"}

# Find the latest PENDING upload
ru = requests.get(f"{NOMAD_URL}/uploads?order=desc&per_page=1", headers=headers, timeout=10)
upload_id = ru.json().get("data", [{}])[0].get("upload_id", "")
proc = ru.json().get("data", [{}])[0].get("process_status", "")
print(f"Latest upload: {upload_id} status={proc}")

if not upload_id:
    print("No uploads found")
    sys.exit(1)

# Now process it using internal API (this bypasses Temporal)
# We need to use the NOMAD Python API directly
from nomad.processing import Upload
from nomad import files as nomad_files

print(f"Processing upload {upload_id} directly...")

# Get the upload object
upload = Upload.get(upload_id)
if not upload:
    print(f"Upload {upload_id} not found in database")
    sys.exit(1)

print(f"Found upload: {upload.upload_name}")
print(f"Current status: {upload.process_status}")

if upload.process_status == "PENDING":
    print("Processing upload...")
    try:
        upload.process_upload(trigger_processing=True)
        print("process_upload() completed")
    except Exception as e:
        print(f"process_upload() error: {e}")
        import traceback
        traceback.print_exc()

# Check result
time.sleep(5)
ru = requests.get(f"{NOMAD_URL}/uploads/{upload_id}", headers=headers, timeout=10)
u = ru.json().get("data", ru.json())
print(f"Final status: {u.get('process_status', '?')}")
print(f"Entries: {u.get('entries', 0)}")
if int(u.get('entries', 0)) > 0:
    print("SUCCESS!")
else:
    print(f"Upload data: {json.dumps(u, indent=2)[:500]}")
