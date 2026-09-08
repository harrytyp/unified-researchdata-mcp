#!/usr/bin/env python3
"""Find TGA items in elabFTW and upload a CSV with _item{id} filename."""
import sys, requests, json, time, os, warnings
warnings.filterwarnings("ignore")

ELAB_URL = "https://elntest.ub.tum.de/api/v2"
API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# Find TGA items in Ready status (status_id=67)
print("=== elabFTW TGA items in Ready status ===")
resp = requests.get(f"{ELAB_URL}/teams/29/items?cat=5&limit=20", headers=headers, verify=False, timeout=15)
items = resp.json() if resp.status_code == 200 else []
ready_items = []
for item in items:
    sid = item.get("status", item.get("status_id", 0))
    title = item.get("title", "?")
    iid = item.get("id", "?")
    print(f"  ID {iid}: {title} status={sid}")
    if str(sid) == "67":
        ready_items.append(item)

if not ready_items:
    print("\nNo TGA items in Ready status (67). Creating one...")
    # Create a new TGA item (item type 145)
    from datetime import datetime
    create_data = {
        "title": f"E2E Test Item {datetime.now().strftime('%H%M%S')}",
        "category": "5",
        "status": "67",
        "metadata": {
            "procedure_name": "Test",
            "sample_name": "E2E Sample",
            "sample_mass_mg": "53.504",
            "pan_type": "Platinum",
            "gas_atmosphere": "N2"
        }
    }
    cr = requests.post(f"{ELAB_URL}/teams/29/items", headers=headers,
                       json=create_data, verify=False, timeout=15)
    print(f"Create item: {cr.status_code} {cr.text[:200]}")
    if cr.status_code == 201:
        ready_items = [cr.json()]
else:
    print(f"\nUsing item {ready_items[0].get('id')}: {ready_items[0].get('title')}")

# Get item ID
if ready_items:
    item_id = ready_items[0].get("id")
    print(f"\nItem ID: {item_id}")
    print(f"Upload a CSV with filename containing _item{item_id}")
else:
    print("FAILED: No items available")
    sys.exit(1)
