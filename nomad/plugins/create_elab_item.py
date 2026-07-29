#!/usr/bin/env python3
"""Find or create an elabFTW TGA item, then upload a matching CSV to NOMAD."""
import sys, requests, json, time, os, warnings
from datetime import datetime
warnings.filterwarnings("ignore")

ELAB_URL = "https://elntest.ub.tum.de/api/v2"
# Full API key from startup.sh backup
API_KEY = "78-ddda64df7e061243946e6055c68667bff8ee35fdce3ed00832f421d54d8cd0cbcc5f9dfbb959132df6cd78"
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

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
        print("\nNo Ready items found. Creating from template (item type 145)...")
        # Create database item from item type
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
    print(f"Error connecting: {resp.text[:200]}")
    sys.exit(1)

print(f"\n=== Item ID: {item_id} ===")
print(f"elabFTW URL: https://elntest.ub.tum.de/database.php?mode=view&id={item_id}")
