#!/usr/bin/env python3
"""Standalone elabFTW-NOMAD batch sync script.

Usage:
    docker exec nomad_oasis_app python3 /app/plugins/elabftw-linker/sync.py \
        --api-url https://your-elabftw-instance/api/v2 \
        --api-key 72-your-api-key
"""
import argparse
import sys
import requests


def sync_experiments(api_url, api_key):
    headers = {"Authorization": api_key}
    results = {"synced": 0, "errors": 0}
    try:
        resp = requests.get("http://localhost:8000/api/v1/entries?page_size=500", timeout=30)
        if resp.status_code != 200:
            print("ERROR: NOMAD API returned", resp.status_code)
            return results
        entries = resp.json().get("data", [])
    except Exception as e:
        print("ERROR: Could not query NOMAD API:", e)
        return results

    elab_entries = [e for e in entries if e.get("external_id")]
    print("Found " + str(len(elab_entries)) + " entries with elabFTW external IDs")

    for entry in elab_entries:
        elab_id = entry["external_id"]
        try:
            url = api_url + "/experiments/" + str(elab_id) + "?format=json&json=true"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", data.get("name", "untitled"))
                print("  [" + str(elab_id) + "] " + title)
                results["synced"] += 1
            else:
                print("  [" + str(elab_id) + "] HTTP " + str(resp.status_code))
                results["errors"] += 1
        except Exception as e:
            print("  [" + str(elab_id) + "] ERROR: " + str(e))
            results["errors"] += 1
    return results


def main():
    parser = argparse.ArgumentParser(description="elabFTW-NOMAD Batch Sync")
    parser.add_argument("--api-url", required=True, help="elabFTW API base URL")
    parser.add_argument("--api-key", required=True, help="elabFTW API key")
    args = parser.parse_args()
    print("=== elabFTW-NOMAD Batch Sync ===")
    print("API: " + args.api_url)
    results = sync_experiments(args.api_url, args.api_key)
    print("")
    print("Synced: " + str(results["synced"]) + ", Errors: " + str(results["errors"]))
    return 0 if results["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
