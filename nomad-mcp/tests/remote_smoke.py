"""Deployed-server smoke test: the register flow plus authenticated tools.

Run inside the nomad-mcp container (it has the SDK, the app, and the
deployment's own PAT in its environment):

    docker cp tests/remote_smoke.py <container>:/tmp/
    docker exec <container> python /tmp/remote_smoke.py

The PAT is read from the environment and never printed.
"""

import json
import os
import sys
import urllib.parse

import anyio
import httpx

LOCAL = os.environ.get("SMOKE_LOCAL", "http://127.0.0.1:8000")
PUBLIC = os.environ.get("SMOKE_PUBLIC", "https://researchmcp.duckdns.org/nm")

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passed if ok else failed).append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


async def tools_over(
    url: str,
    label: str,
    calls: list[tuple[str, dict]],
    scope_limited: set[str] = frozenset(),
    expect_tools: int = 16,
) -> None:
    """Drive the server with a real client; `scope_limited` tools may 403."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            check(
                f"{label}: tools listed",
                len(listing.tools) == expect_tools,
                f"{len(listing.tools)} (expected {expect_tools})",
            )
            for name, arguments in calls:
                result = await session.call_tool(name, arguments)
                text = "".join(getattr(b, "text", "") for b in result.content)
                if name in scope_limited and "Missing scopes" in text:
                    check(f"{label}: {name} (expected: key lacks the scope)", True, text[:90].replace("\n", " "))
                    continue
                check(f"{label}: {name}", not result.is_error and bool(text), text[:110].replace("\n", " "))


def register_flow() -> str:
    """A real NOMAD key through the register page, returning the MCP URL."""
    pat = os.environ.get("NOMAD_MCP_DEFAULT_PAT", "")
    if not pat:
        check("register flow (needs NOMAD_MCP_DEFAULT_PAT)", False, "no key in env")
        return ""
    response = httpx.post(
        f"{LOCAL}/register",
        data={
            "api_key": pat,
            "base_url": os.environ.get("NOMAD_BASE_URL", ""),
            "tools": ["get_info", "get_me", "search_entries"],
        },
        timeout=60,
        follow_redirects=True,
    )
    check("register accepts a real key", response.status_code == 200, str(response.status_code))
    if response.status_code != 200:
        return ""
    marker = "token="
    start = response.text.find(marker)
    if start < 0:
        check("register returns a token URL", False)
        return ""
    token = response.text[start + len(marker) :].split('"')[0].split("<")[0].strip()
    token = urllib.parse.unquote(token)
    check("register returns a token URL", len(token) > 40, f"{len(token)} chars")
    # the page must not leak the key back to the browser
    check("register does not echo the key", pat not in response.text)
    return f"{LOCAL}/mcp?token={token}"


def main() -> int:
    health = httpx.get(f"{LOCAL}/health", timeout=20).json()
    check(
        "deployment default PAT is configured",
        health.get("default_pat") is True,
        str(health.get("base_url")),
    )

    anyio.run(
        tools_over,
        f"{LOCAL}/mcp",
        "default-pat",
        [
            ("get_info", {}),
            ("get_me", {}),
            ("list_uploads", {}),
            ("list_datasets", {}),
            ("search_entries", {"query": {"results.material.elements": "Ti"}, "page_size": 2}),
            ("list_groups", {}),
        ],
        {"get_me", "list_datasets", "list_groups"},
    )

    url = register_flow()
    if url:
        anyio.run(
            tools_over,
            url,
            "registered-token",
            [("get_info", {}), ("get_me", {})],
            {"get_me"},
            expect_tools=3,
        )
        # a token that does not list a tool must not be able to call it
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def denied() -> None:
            async with streamable_http_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    names = {t.name for t in listing.tools}
                    check(
                        "token exposes only the selected tools",
                        names == {"get_info", "get_me", "search_entries"},
                        ", ".join(sorted(names)),
                    )

        anyio.run(denied)

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
