#!/usr/bin/env python3
"""
elabFTW → NOMAD Webhook.

A lightweight HTTP endpoint that receives elabFTW experiment IDs and
creates corresponding NOMAD entries. Designed to be called from elabFTW
custom links/buttons.

Usage:
  # From elabFTW extra field / button:
  # "Send to NOMAD" → https://researchmcp.duckdns.org/integrations/import/42

  # Direct API call:
  curl -X POST https://researchmcp.duckdns.org/integrations/import \\
    -H "Content-Type: application/json" \\
    -d '{"experiment_id": 42}'

Returns NOMAD URL for the created entry.
"""

import json
import os
import sys
from urllib.parse import quote

import requests
import yaml


def load_config():
    """Load shared config from the NOMAD plugin directory."""
    paths = [
        '/app/plugins/three_way_sync/config.yaml',
        os.path.join(os.path.dirname(__file__), 'config.yaml'),
    ]
    for path in paths:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f)
    return {}


def import_experiment(experiment_id, config=None):
    """Import an elabFTW experiment into NOMAD and return the NOMAD entry URL.

    Steps:
    1. Fetch experiment from elabFTW API
    2. Create NOMAD upload (if needed)
    3. Create NOMAD entry with external_id set
    4. Write NOMAD URL back into elabFTW experiment
    """
    if config is None:
        config = load_config()

    elab = config.get('elabftw', {})
    nomad_cfg = config.get('nomad', {})

    elab_url = elab.get('api_url', 'https://elntest.ub.tum.de/api/v2')
    elab_key = elab.get('api_key', '')
    nomad_url = nomad_cfg.get('api_url', 'http://localhost:8000/nomad-oasis/api/v1')
    nomad_key = nomad_cfg.get('api_key', '')

    # Step 1: Fetch from elabFTW
    headers = {"Authorization": elab_key}
    resp = requests.get(
        f"{elab_url}/experiments/{experiment_id}?format=json&json=true",
        headers=headers, timeout=15,
    )
    if resp.status_code != 200:
        return {"error": f"elabFTW returned HTTP {resp.status_code}"}

    exp = resp.json()
    title = exp.get('title', exp.get('name', f'elabFTW Experiment {experiment_id}'))

    # Step 2: Create NOMAD upload
    nomad_headers = {"Authorization": f"Bearer {nomad_key}"} if nomad_key else {}
    upload_resp = requests.post(
        f"{nomad_url}/uploads",
        headers=nomad_headers,
        json={"upload_name": f"elabFTW Import: {title[:50]}"},
        timeout=15,
    )
    if upload_resp.status_code not in (200, 201):
        return {"error": f"NOMAD upload failed: HTTP {upload_resp.status_code}"}

    upload_id = upload_resp.json().get('upload_id') or upload_resp.json().get('pid')

    # Step 3: Create NOMAD entry
    entry_payload = {
        "entry_name": title,
        "data": {
            "m_def": "nomad_external_eln_integrations.schema_packages.elabftw:elabftw_schema.ElabftwProject",
            "project_url": f"https://elntest.ub.tum.de/experiments.php?mode=view&id={experiment_id}",
            "api_key": elab_key,
            "Sync_Project": True,
        },
        "metadata": {
            "external_id": str(experiment_id),
        }
    }
    entry_resp = requests.post(
        f"{nomad_url}/uploads/{upload_id}/archive",
        headers=nomad_headers,
        json=entry_payload,
        timeout=30,
    )
    if entry_resp.status_code not in (200, 201):
        return {"error": f"NOMAD entry creation: HTTP {entry_resp.status_code}"}

    entry_data = entry_resp.json()
    entry_id = entry_data.get('entry_id') or entry_data.get('pid')

    # Step 4: Write NOMAD link back into elabFTW
    nomad_entry_url = f"https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/entry/{upload_id}/{entry_id}"
    requests.put(
        f"{elab_url}/experiments/{experiment_id}",
        headers=headers,
        json={"extra_fields": {"NOMAD URL": nomad_entry_url}},
        timeout=15,
    )

    return {
        "status": "ok",
        "elabftw_id": experiment_id,
        "nomad_entry_id": entry_id,
        "nomad_upload_id": upload_id,
        "nomad_url": nomad_entry_url,
        "title": title,
    }


# === WSGI/ASGI app for serving behind Caddy ===

try:
    from flask import Flask, request, jsonify, redirect

    app = Flask(__name__)

    @app.route("/integrations/import", methods=["POST"])
    def webhook_import():
        """POST webhook: import an elabFTW experiment."""
        data = request.get_json(force=True) or {}
        exp_id = data.get("experiment_id") or request.args.get("id")
        if not exp_id:
            return jsonify({"error": "Missing experiment_id"}), 400
        result = import_experiment(str(exp_id))
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)

    @app.route("/integrations/import/<path:exp_id>", methods=["GET", "POST"])
    def webhook_import_path(exp_id):
        """GET or POST with experiment ID in URL path."""
        result = import_experiment(str(exp_id))
        if "error" in result:
            return jsonify(result), 500
        # If GET from browser, redirect to the NOMAD entry
        if request.method == "GET" and "nomad_url" in result:
            return redirect(result["nomad_url"])
        return jsonify(result)

    @app.route("/integrations/health")
    def health():
        return jsonify({"status": "ok", "service": "elabftw-nomad-bridge"})

except ImportError:
    app = None
    print("Flask not available. Run: pip install flask")
    print("The webhook server needs Flask to run.")


# === CLI mode ===

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        # Run as HTTP server
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
        if app:
            app.run(host="0.0.0.0", port=port, debug=False)
        else:
            print("Flask required for serve mode.")
            sys.exit(1)
    elif len(sys.argv) > 1:
        # Import specific experiment from CLI
        result = import_experiment(sys.argv[1])
        print(json.dumps(result, indent=2))
    else:
        print("Usage:")
        print("  python3 webhook.py serve [port]     # Start webhook server")
        print("  python3 webhook.py <experiment_id>   # Import experiment")
        print("  curl ...                             # POST to /integrations/import")
