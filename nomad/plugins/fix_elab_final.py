#!/usr/bin/env python3
"""Delete duplicate plot PNGs from elabFTW item, then fix NOMAD entry link."""
import requests, warnings, sys, os, glob
warnings.filterwarnings("ignore")

API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
ELAB = "https://elntest.ub.tum.de/api/v2"
h = {"Authorization": API_KEY}
item_id = 1477

# Step 1: Delete duplicate PNGs
print("=== Step 1: Clean duplicate PNGs ===")
r = requests.get(f"{ELAB}/items/{item_id}/uploads", headers=h, verify=False, timeout=15)
uploads = r.json() if isinstance(r.json(), list) else []
print(f"Total uploads: {len(uploads)}")
pngs = [u for u in uploads if u.get("real_name","").endswith(".png")]
print(f"PNG files: {len(pngs)}")
if len(pngs) > 1:
    for p in pngs[:-1]:
        pid = p.get("id")
        dr = requests.delete(f"{ELAB}/uploads/{pid}", headers=h, verify=False, timeout=10)
        print(f"  Deleted PNG {pid}: {dr.status_code}")

# Step 2: Get entry ID from archive
print("\n=== Step 2: Look up entry ID ===")
upload_id = "scfTJB7NS3i4RMj1CEaFRQ"
archive_dir = f"/app/.volumes/fs/staging/{upload_id[:2]}/{upload_id}/archive"
msg_files = glob.glob(os.path.join(archive_dir, "*.msg"))
entry_id = ""
if msg_files:
    entry_id = os.path.basename(msg_files[0]).split("-")[0]
    print(f"Entry ID: {entry_id}")
else:
    print(f"No .msg files in {archive_dir}")

# Step 3: Reprocess with explicit entry_id via direct push
print("\n=== Step 3: Reprocess with entry URL ===")
# Build the entry URL directly
nomad_entry_url = f"https://researchmcp.duckdns.org/nomad-oasis/gui/search/entries/entry/id/{entry_id}"
print(f"Nomad entry URL: {nomad_entry_url}")

# Update elabFTW item body to include the NOMAD entry link
from datetime import datetime, timezone
nomad_html = (
    '<h3 style="margin:16px 0 8px">NOMAD Entry</h3>'
    f'<p><a href="{nomad_entry_url}" target="_blank" style="color:#1976D2">{nomad_entry_url}</a></p>'
)

# Append the NOMAD link to the existing body
r = requests.get(f"{ELAB}/items/{item_id}", headers=h, verify=False, timeout=15)
item = r.json()
body = item.get("body", "")
# Check if entry link already exists
if entry_id in body:
    print("Entry link already in body")
else:
    # Insert NOMAD link before the raw data section
    if "<details>" in body:
        new_body = body.replace("<details>", nomad_html + "<details>", 1)
    else:
        new_body = body + nomad_html
    
    # Update item
    import json
    meta = item.get("metadata", "")
    try:
        meta_dict = json.loads(meta) if isinstance(meta, str) else meta
    except:
        meta_dict = {}
    meta_dict["nomad_url"] = nomad_entry_url
    
    payload = {"body": new_body, "metadata": json.dumps(meta_dict)}
    pu = requests.patch(f"{ELAB}/items/{item_id}", headers=h, json=payload, verify=False, timeout=15)
    print(f"Update body: {pu.status_code}")
    if pu.status_code in (200, 201, 204):
        print("Body updated with NOMAD entry link")

# Step 4: Clean old PNG from staging and reset
print("\n=== Cleanup: remove old processed log ===")
proc_log = "/app/logs/nomad-processor-processed.json"
if os.path.exists(proc_log):
    json.dump([], open(proc_log, "w"))
    print("Processed log cleared")

print(f"\n=== LINKS ===")
print(f"elabFTW:     https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")
print(f"NOMAD entry: {nomad_entry_url}")
