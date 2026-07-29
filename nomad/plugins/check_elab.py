#!/usr/bin/env python3
"""Check elabFTW item uploads and body."""
import requests, warnings, json
warnings.filterwarnings("ignore")

API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
headers = {"Authorization": API_KEY}
ELAB = "https://elntest.ub.tum.de/api/v2"
item_id = 1475

# Check uploads
r = requests.get(f"{ELAB}/items/{item_id}/uploads", headers=headers, verify=False, timeout=15)
uploads = r.json() if r.status_code == 200 else []
print(f"Uploads ({len(uploads)}):")
for u in (uploads if isinstance(uploads, list) else []):
    print(f"  ID={u.get('id')} name={u.get('real_name')} type={u.get('type')}")

# Check body
r = requests.get(f"{ELAB}/items/{item_id}", headers=headers, verify=False, timeout=15)
item = r.json() if r.status_code == 200 else {}
body = item.get("body") or ""
print(f"\nBody length: {len(body)}")
print(f"Has img tag: {'<img' in body}")
print(f"Has raw data: {'Raw Measurement' in body}")
print(f"Has parameters: {'sample' in body.lower() or 'heating' in body.lower()}")
print(f"Has NOMAD link: {'Entry</a>' in body or 'nomad' in body.lower()}")

# Check metadata
meta = item.get("metadata") or "{}"
if isinstance(meta, str):
    try:
        meta_d = json.loads(meta)
        print(f"\nMetadata keys: {list(meta_d.keys())}")
    except:
        print(f"\nMetadata: {meta[:200]}")
else:
    print(f"\nMetadata: {meta}")

# Check extra_fields
ef = item.get("extra_fields") or {}
print(f"Extra fields: {ef}")
