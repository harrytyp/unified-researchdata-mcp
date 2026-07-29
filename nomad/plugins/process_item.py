#!/usr/bin/env python3
"""Process a specific NOMAD upload through nomad_processor."""
import sys, requests, json, os
sys.path.insert(0, "/app/plugins")
from nomad_processor import process_upload, NOMAD_API_URL

PAT = open("/app/.nomad_pat").read().strip()
h = {"Authorization": "Bearer " + PAT}

uid = "S7bkz1C6TjKFOQ9Qydwqhg"
r = requests.get(NOMAD_API_URL + "/uploads/" + uid, headers=h, timeout=10)
upload = r.json()
upl = upload.get("data", upload)
print("Upload ID:", upl.get("upload_id"))
print("Files:", upl.get("files"))
print("Server path:", upl.get("upload_files_server_path"))

result = process_upload(upload, elab_item_id=1475)
print("Result:", result)
