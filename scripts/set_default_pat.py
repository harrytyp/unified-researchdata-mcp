#!/usr/bin/env python3
"""Put the deployment's NOMAD PAT into .env as the NOMAD MCP default credential.

Reads the token from nomad/.env and writes it to .env with Docker Compose `$`
escaping. Never prints the value.
"""
import io
import re
import sys

ROOT = "/home/debian/unified-researchdata-mcp"


def main() -> int:
    env = io.open(f"{ROOT}/.env", encoding="utf-8", newline="").read()
    nomad = io.open(f"{ROOT}/nomad/.env", encoding="utf-8", newline="").read()
    match = re.search(r"^NOMAD_PAT=(.*)$", nomad, re.M)
    pat = (match.group(1) if match else "").strip().strip('"').strip("'")
    print("token length:", len(pat), "| contains $:", "$" in pat)
    if not pat:
        print("no NOMAD_PAT in nomad/.env")
        return 1
    escaped = pat.replace("$", "$$")
    if re.search(r"^NOMAD_MCP_DEFAULT_PAT=", env, re.M):
        env = re.sub(
            r"^NOMAD_MCP_DEFAULT_PAT=.*$",
            "NOMAD_MCP_DEFAULT_PAT=" + escaped,
            env,
            flags=re.M,
        )
        action = "updated"
    else:
        if not env.endswith("\n"):
            env += "\n"
        env += (
            "\n# NOMAD MCP: read-only access for callers that never register "
            "(the Oasis admin PAT)\nNOMAD_MCP_DEFAULT_PAT=" + escaped + "\n"
        )
        action = "added"
    io.open(f"{ROOT}/.env", "w", encoding="utf-8", newline="").write(env)
    print(".env", action)

    example = io.open(f"{ROOT}/.env.example", encoding="utf-8", newline="").read()
    if "NOMAD_MCP_DEFAULT_PAT" not in example:
        if not example.endswith("\n"):
            example += "\n"
        example += (
            "\n# NOMAD MCP (nomad-mcp service)\n"
            "NOMAD_MCP_DEFAULT_PAT=\n"
            "NOMAD_MCP_BASE_URL=http://proxy:80/nomad-oasis/api/v1\n"
            "NOMAD_MCP_ALLOW_ANONYMOUS=true\n"
            "NOMAD_MCP_REQUIRE_TOKEN=false\n"
            "NOMAD_MCP_RATE_LIMIT=120\n"
            "NOMAD_MCP_MAX_RESPONSE_CHARS=60000\n"
            "NOMAD_MCP_TIMEOUT_S=60\n"
        )
        io.open(f"{ROOT}/.env.example", "w", encoding="utf-8", newline="").write(example)
        print(".env.example updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
