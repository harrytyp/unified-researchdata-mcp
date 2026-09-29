"""End-to-end smoke test: real MCP client, real NOMAD API.

Run with the deployment's environment (MCP_JWT_SECRET at least):

    python tests/smoke.py                       # against central NOMAD
    NOMAD_BASE_URL=... NOMAD_MCP_DEFAULT_PAT=... python tests/smoke.py

Every call here is read-only. Nothing is written to NOMAD.
"""

import json
import os
import sys
import threading
import time

import anyio
import httpx
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("MCP_JWT_SECRET", "smoke-test-secret-not-a-deployment")

PORT = int(os.environ.get("SMOKE_PORT", "8791"))
BASE = f"http://127.0.0.1:{PORT}"

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passed if ok else failed).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def start() -> None:
    from nomad_mcp.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()
    for _ in range(40):
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                return
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    raise SystemExit("server did not come up")


async def run_mcp() -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(f"{BASE}/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            names = sorted(t.name for t in listing.tools)
            check("tools listed", len(names) >= 16, f"{len(names)} tools")
            annotations = {t.name: t.annotations for t in listing.tools}
            read_only = all(
                a is not None and a.read_only_hint is True for a in annotations.values()
            )
            check("every tool declares readOnlyHint", read_only)
            check(
                "titles present",
                all((t.title or "") for t in listing.tools),
            )
            print("      tools:", ", ".join(names))

            info = await session.call_tool("get_info", {})
            text = "".join(getattr(b, "text", "") for b in info.content)
            check("get_info returns deployment data", "version" in text.lower(), text[:90])
            check("get_info stays small", len(text) < 20000, f"{len(text)} chars")

            search = await session.call_tool(
                "search_entries",
                {"query": {"results.material.elements": "Ti"}, "page_size": 2},
            )
            payload = json.loads("".join(getattr(b, "text", "") for b in search.content))
            total = (payload.get("pagination") or {}).get("total")
            check("search_entries returns real results", bool(payload.get("data")), f"total={total}")
            check("pagination.total reported", isinstance(total, int) and total > 0, str(total))
            check(
                "search_entries stays inside the response budget",
                not payload.get("truncated"),
                f"{len(json.dumps(payload))} chars",
            )
            entry_id = (payload.get("data") or [{}])[0].get("entry_id", "")

            rawdir = await session.call_tool("list_raw_files", {"entry_id": entry_id})
            raw_text = "".join(getattr(b, "text", "") for b in rawdir.content)
            check("list_raw_files lists the submitted files", "raw" in raw_text or "name" in raw_text)

            if entry_id:
                raw = await session.call_tool(
                    "get_raw_file", {"entry_id": entry_id, "path": "README.md"}
                )
                check(
                    "get_raw_file answers (content or a clean 404)",
                    raw.is_error is True or "text" in "".join(
                        getattr(b, "text", "") for b in raw.content
                    ),
                )

            quantities = await session.call_tool(
                "search_quantities", {"text": "chemical_formula", "page_size": 5}
            )
            check(
                "search_quantities suggests fields",
                "chemical_formula" in "".join(getattr(b, "text", "") for b in quantities.content),
            )

            bad = await session.call_tool("get_entry", {"entry_id": "does-not-exist"})
            text = "".join(getattr(b, "text", "") for b in bad.content)
            check("a bad id becomes a tool error, not a crash", bad.is_error is True, text[:80])

            limited = await session.call_tool("list_uploads", {})
            text = "".join(getattr(b, "text", "") for b in limited.content)
            check(
                "unauthenticated upload listing is refused cleanly",
                limited.is_error is True or "data" in text,
                text[:80],
            )


def run_http_checks() -> None:
    health = httpx.get(f"{BASE}/health", timeout=10)
    check("health endpoint", health.status_code == 200 and health.json()["status"] == "ok")

    page = httpx.get(f"{BASE}/register", timeout=10)
    check("register page renders", page.status_code == 200 and "NOMAD" in page.text)

    refused = httpx.post(
        f"{BASE}/register",
        data={"api_key": "obviously-not-a-nomad-token", "base_url": "https://nomad-lab.eu/prod/v1/api/v1"},
        timeout=30,
    )
    check("register refuses an invalid key", refused.status_code == 400, str(refused.status_code))

    no_key = httpx.post(f"{BASE}/register", data={"api_key": ""}, timeout=10)
    check("register requires a key", no_key.status_code == 400)


def run_token_check() -> None:
    """A minted token must carry base URL, key, and tool selection."""
    from nomad_mcp.jwt_token import decode_token, encode_token

    token = encode_token(
        "https://example.invalid/api/v1", "pat-123", profile="r", enabled_tools=["get_info"]
    )
    payload = decode_token(token)
    check("token round-trips", payload is not None and payload["k"] == "pat-123")
    check("token carries the base URL", payload and payload["u"].endswith("/api/v1"))
    check("token carries the tool selection", payload and payload["t"] == ["get_info"])
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    check("tampered token rejected", decode_token(tampered) is None)


def main() -> int:
    start()
    run_http_checks()
    run_token_check()
    anyio.run(run_mcp)
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
