#!/usr/bin/env python3
"""Point the Atlas deployment at the NOMAD MCP.

Three edits, all idempotent, all in ~/atlas:

1. compose.yaml gains a CRA_REPO build argument (default: the upstream repo),
   so the image can be built from a fork while a pull request is open.
2. .env gets the NOMAD source, the deployment's read-only key for it, and the
   temporary CRA_REPO/CRA_REF pin.
3. .env.example documents the new keys.

The key is copied from the monorepo's nomad/.env and never printed.
"""
import io
import re
import sys

ATLAS = "/home/debian/atlas"
MONOREPO = "/home/debian/unified-researchdata-mcp"
FORK = "https://github.com/harrytyp/cluster-research-assist"
COMMIT = "66b49c3f1352e8238cfba3356df62ded4f66ae6c"
PUBLIC = "https://researchmcp.duckdns.org"


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


def patch_compose():
    path = f"{ATLAS}/compose.yaml"
    text = read(path)
    if "CRA_REPO:" in text:
        return "compose.yaml: already patched"
    anchor = "        CRA_REF: ${ATLAS_CRA_REF:-main}\n"
    if anchor not in text:
        return "compose.yaml: ANCHOR NOT FOUND"
    text = text.replace(
        anchor,
        anchor
        + "        # the upstream repository unless a fork is pinned while a pull\n"
        + "        # request against it is still open\n"
        + "        CRA_REPO: ${ATLAS_CRA_REPO:-https://github.com/e-conversion/cluster-research-assist}\n",
        1,
    )
    write(path, text)
    return "compose.yaml: CRA_REPO build arg added"


def main() -> int:
    print(patch_compose())

    nomad_env = read(f"{MONOREPO}/nomad/.env")
    match = re.search(r"^NOMAD_PAT=(.*)$", nomad_env, re.M)
    pat = (match.group(1) if match else "").strip().strip('"').strip("'")
    print("token length:", len(pat), "| contains $:", "$" in pat)
    if not pat:
        return 1

    path = f"{ATLAS}/.env"
    text = read(path)
    if "CRA_MCP_NOMAD_URL" not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += (
            "\n# ---- NOMAD MCP (the read-only server in the researchdata stack) ----\n"
            f"CRA_MCP_NOMAD_URL={PUBLIC}/nm/mcp\n"
            f"CRA_MCP_NOMAD_REGISTER_URL={PUBLIC}/nm/register\n"
            f"CRA_MCP_NOMAD_BASE_URL={PUBLIC}/nomad-oasis/api/v1\n"
            "# read-only access for everybody who has not registered their own\n"
            "# NOMAD key; never leaves the server\n"
            "CRA_MCP_NOMAD_TOKEN=" + pat.replace("$", "$$") + "\n"
        )
        print(".env: NOMAD source added")
    else:
        text = set_key(text, "CRA_MCP_NOMAD_TOKEN", pat.replace("$", "$$"))
        print(".env: NOMAD token refreshed")

    # temporary: the image is built from the fork until the pull request lands
    text = set_key(
        text,
        "ATLAS_CRA_REPO",
        FORK,
    )
    text = set_key(text, "ATLAS_CRA_REF", COMMIT)
    write(path, text)
    print(".env: ATLAS_CRA_REPO/ATLAS_CRA_REF pinned to the fork")

    example = f"{ATLAS}/.env.example"
    text = read(example)
    if "CRA_MCP_NOMAD_URL" not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += (
            "\n# ---- NOMAD MCP ----------------------------------------------------\n"
            f"CRA_MCP_NOMAD_URL={PUBLIC}/nm/mcp\n"
            f"CRA_MCP_NOMAD_REGISTER_URL={PUBLIC}/nm/register\n"
            f"CRA_MCP_NOMAD_BASE_URL={PUBLIC}/nomad-oasis/api/v1\n"
            "# secret: a key this deployment holds for the source above; an account\n"
            "# without a token of its own is connected with it, read-only\n"
            "CRA_MCP_NOMAD_TOKEN=\n"
            "# build the image from another repository (a fork, while a pull\n"
            "# request is open); empty uses the upstream one\n"
            "ATLAS_CRA_REPO=\n"
        )
        write(example, text)
        print(".env.example: documented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
