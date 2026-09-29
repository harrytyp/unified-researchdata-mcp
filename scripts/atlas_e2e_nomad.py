#!/usr/bin/env python3
"""End-to-end check in the live Atlas: does NOMAD connect by itself?

Creates a throwaway password account, signs in over HTTP against the public
URL, reads /api/session, and removes the account again. Prints no secrets and
leaves no rows behind.

The users table keys on `id` and carries no username (that lives in
local_credentials), so cleanup resolves the id there first.

Run on the test server:  python3 /tmp/atlas_e2e_nomad.py
"""

import json
import os
import re
import secrets
import subprocess
import sys

BASE = "https://econverse.e-conversion.de"
# "connected": the account is one the deployment holds a NOMAD key for;
# "unconnected": everybody else has to register their own.
EXPECT = os.environ.get("E2E_EXPECT", "connected")
USER = "e2e-nomad-check"
DISPLAY = "E2E NOMAD check"
CONTAINER = "e-converse-cra-1"

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passed if ok else failed).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def cra(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "cra", *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


def http_client():
    """A cookie-keeping opener, no third-party client needed."""
    import urllib.request
    from http.cookiejar import CookieJar

    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(opener, url, data=None):
    import urllib.error
    import urllib.request

    body = json.dumps(data).encode() if data else None
    request = urllib.request.Request(url, data=body)
    if body:
        request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def psql(sql: str) -> str:
    """One statement; a failure is raised, never swallowed."""
    env = open("/home/debian/atlas/.env", encoding="utf-8").read()
    match = re.search(r"^POSTGRES_PASSWORD=(.*)$", env, re.M)
    password = (match.group(1) if match else "").strip()
    result = subprocess.run(
        [
            "docker", "exec", "-e", f"PGPASSWORD={password}", "e-converse-db-1",
            "psql", "-U", "econverse", "-d", "econverse", "-t", "-A", "-v",
            "ON_ERROR_STOP=1", "-c", sql,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


def user_id_of() -> str:
    found = psql(f"select user_id from local_credentials where username = '{USER}'")
    if found:
        return found
    return psql(f"select id from users where display_name = '{DISPLAY}'")


def cleanup() -> int:
    """Remove the throwaway account and everything hanging off it."""
    user_id = user_id_of()
    if user_id:
        for table in ("source_connections", "sessions", "identities", "local_credentials"):
            psql(f"delete from {table} where user_id = '{user_id}'")
        for conversation in filter(
            None, psql(f"select id from conversations where user_id = '{user_id}'").splitlines()
        ):
            psql(f"delete from messages where conversation_id = '{conversation}'")
        psql(f"delete from conversations where user_id = '{user_id}'")
        psql(f"delete from users where id = '{user_id}'")
    return int(psql(f"select count(*) from local_credentials where username = '{USER}'") or 0)


def main() -> int:
    try:
        left = cleanup()
    except RuntimeError as exc:
        check("database reachable", False, str(exc))
        return 1
    check("no leftovers from an earlier run", left == 0, str(left))

    opener = http_client()
    password = secrets.token_urlsafe(18)
    created = cra(
        "users", "create", USER, "--name", DISPLAY, "--password-stdin",
        stdin=password + "\n",
    )
    check("throwaway account created", created.returncode == 0, created.stderr.strip()[:120])

    try:
        status, _ = call(opener, f"{BASE}/auth/password", data={"username": USER, "password": password})
        check("signed in", status == 200, str(status))

        _, body = call(opener, f"{BASE}/api/config")
        config = json.loads(body)
        check(
            "the NOMAD source is offered",
            "nomad" in config.get("sources", {}),
            str(list(config.get("sources", {}))),
        )

        _, body = call(opener, f"{BASE}/api/session")
        session = json.loads(body)
        nomad = (session.get("connected") or {}).get("nomad")
        if EXPECT == "connected":
            check(
                "NOMAD is connected without registering anything",
                bool(nomad) and nomad.get("active") is True,
                json.dumps(nomad),
            )
            check(
                "the connected tools are counted",
                (session.get("tools") or {}).get("nomad", 0) == 16,
                str((session.get("tools") or {}).get("nomad")),
            )
        else:
            check(
                "NOMAD is NOT connected for an account the deployment does not name",
                bool(nomad) and nomad.get("active") is False,
                json.dumps(nomad),
            )
            check(
                "no NOMAD tools are offered",
                (session.get("tools") or {}).get("nomad", 0) == 0,
                str((session.get("tools") or {}).get("nomad")),
            )
            check(
                "the source is still offered, so a key can be registered",
                "nomad" in config.get("sources", {}),
            )
        blob = json.dumps(session)
        check(
            "the shared key is nowhere in the session payload",
            "nomad_pat" not in blob and "shared_token" not in blob,
        )
        check(
            "the other sources are untouched",
            (session.get("connected") or {}).get("elab", {}).get("active") is False,
            json.dumps((session.get("connected") or {}).get("elab")),
        )
    finally:
        left = cleanup()
        check("throwaway account removed", left == 0, f"{left} rows left")

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
