#!/usr/bin/env python3
"""Create the full read-only PAT for the NOMAD MCP, from the session bearer.

The session bearer (a Keycloak JWT) is the only credential NOMAD lets create a
PAT: `create_pat` refuses tokens:create/read/delete inside a PAT, so no PAT can
mint another one. A Keycloak session resolves to `*:*`.

The bearer is read from the file named by argv[1] and never printed. The raw
token that comes back goes straight into the two .env files, also unprinted.

Run on the test server: python3 /tmp/make_pat.py /tmp/session.jwt
"""

import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://researchdata.e-conversion.de/nomad-oasis/api/v1"
NAME = "nomad-mcp-admin-read"
DAYS = 365

# every read scope except tokens:read -- a PAT may not operate on PATs, so a
# scope list containing it is rejected outright
READ_SCOPES = [
    "actions:read", "apps:read", "datasets:read", "entries:read", "graph:read",
    "groups:read", "info:read", "materials:read", "metainfo:read", "north:read",
    "schemas:read", "suggestions:read", "systems:read", "uploads:read",
    "uploads_bundle:read", "users:read",
    "external_optimade:read", "external_dcat:read", "external_h5grove:read",
]


def call(method, path, bearer, body=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": "Bearer " + bearer, "Accept": "application/json"},
    )
    if body:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, raw[:300]
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def set_key(text, key, value):
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        return re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
    if not text.endswith("\n"):
        text += "\n"
    return text + f"{key}={value}\n"


def main() -> int:
    bearer = io.open(sys.argv[1], encoding="utf-8").read().strip()
    if not bearer:
        print("no bearer in", sys.argv[1])
        return 1

    status, who = call("GET", "/users/me", bearer)
    print("session accepted:", status)
    if status != 200:
        print("  ->", who)
        return 1
    data = who.get("data", who) if isinstance(who, dict) else who
    print("  account:", data.get("name"), "| user_id:", data.get("user_id"))

    status, existing = call("GET", "/auth/pats", bearer)
    rows = existing.get("data", existing) if isinstance(existing, dict) else existing
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("name") == NAME and not row.get("revoked"):
                code, _ = call("DELETE", f"/auth/pats/{row['id']}", bearer)
                print("revoked an earlier", NAME, "->", code)

    status, answer = call(
        "POST",
        "/auth/pats",
        bearer,
        {
            "metadata": {
                "name": NAME,
                "scopes": READ_SCOPES,
                "description": "full read-only access for the NOMAD MCP server",
            },
            "expires_in_days": DAYS,
        },
    )
    print("pat created:", status)
    if status not in (200, 201):
        print("  ->", answer)
        return 1
    token = answer["raw_token"]
    # the raw token is deliberately never printed: it goes straight to the files
    print("  name:", answer["pat"]["name"], "| scopes:", len(answer["pat"]["scopes"]),
          "| expires:", answer["pat"].get("expired_at"))
    print("  token length:", len(token), "| prefix ok:", token.startswith("nomad_pat_"))

    status, seen = call("GET", "/uploads?page_size=1", token)
    total = (seen.get("pagination", {}) or {}).get("total") if isinstance(seen, dict) else None
    print("new token reads /uploads:", status, "| uploads visible:", total)
    for path in ("/users/me", "/datasets/?page_size=1", "/groups"):
        code, _ = call("GET", path, token)
        print(f"  {path}: {code}")

    escaped = token.replace("$", "$$")
    for path, key in (
        ("/home/debian/unified-researchdata-mcp/.env", "NOMAD_MCP_DEFAULT_PAT"),
        ("/home/debian/atlas/.env", "CRA_MCP_NOMAD_TOKEN"),
    ):
        write(path, set_key(read(path), key, escaped))
        print(f"{path}: {key} updated")

    os.remove(sys.argv[1])
    print("session file removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
