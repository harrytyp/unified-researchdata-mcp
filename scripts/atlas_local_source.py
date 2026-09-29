#!/usr/bin/env python3
"""Let the served image be built from a local checkout instead of a git ref.

compose.yaml gains ATLAS_CRA_SOURCE/ATLAS_CRA_SRC (default: the published
package, as before); .env switches this deployment to the checkout at
~/cluster-research-assist, which is where a change lives before it is on
GitHub. Idempotent.
"""
import io
import re
import sys

ATLAS = "/home/debian/atlas"
CHECKOUT = "/home/debian/cluster-research-assist"

BUILD_BLOCK = """    build:
      context: docker
      # ATLAS_CRA_SOURCE=local installs the checkout at ATLAS_CRA_SRC instead of
      # a git ref -- how a change runs before it is on GitHub. The default is
      # the published package, as before.
      additional_contexts:
        cra: ${ATLAS_CRA_SRC:-../cluster-research-assist}
      args:
        CRA_SOURCE: ${ATLAS_CRA_SOURCE:-git}
        VERSION: "0.0.0.dev"
        CRA_REF: ${ATLAS_CRA_REF:-main}
        # the upstream repository unless a fork is pinned while a pull
        # request against it is still open
        CRA_REPO: ${ATLAS_CRA_REPO:-https://github.com/e-conversion/cluster-research-assist}
"""

OLD_BLOCK = """    build:
      context: docker
      args:
        CRA_REF: ${ATLAS_CRA_REF:-main}
        # the upstream repository unless a fork is pinned while a pull
        # request against it is still open
        CRA_REPO: ${ATLAS_CRA_REPO:-https://github.com/e-conversion/cluster-research-assist}
"""


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
    path = f"{ATLAS}/compose.yaml"
    text = read(path)
    if "ATLAS_CRA_SOURCE" in text:
        print("compose.yaml: already patched")
    elif OLD_BLOCK in text:
        write(path, text.replace(OLD_BLOCK, BUILD_BLOCK, 1))
        print("compose.yaml: local-source build added")
    else:
        print("compose.yaml: ANCHOR NOT FOUND")
        return 1

    env_path = f"{ATLAS}/.env"
    env = read(env_path)
    env = set_key(env, "ATLAS_CRA_SOURCE", "local")
    env = set_key(env, "ATLAS_CRA_SRC", CHECKOUT)
    write(env_path, env)
    print(".env: ATLAS_CRA_SOURCE=local, ATLAS_CRA_SRC=" + CHECKOUT)

    example_path = f"{ATLAS}/.env.example"
    example = read(example_path)
    if "ATLAS_CRA_SOURCE" not in example:
        if not example.endswith("\n"):
            example += "\n"
        example += (
            "# build the image from a checkout instead of a git ref; how a change\n"
            "# runs before it is on GitHub. Empty ATLAS_CRA_SOURCE = published package\n"
            "ATLAS_CRA_SOURCE=\n"
            "ATLAS_CRA_SRC=../cluster-research-assist\n"
        )
        write(example_path, example)
        print(".env.example: documented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
