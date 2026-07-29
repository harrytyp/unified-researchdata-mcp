#!/usr/bin/env python3
"""Patch nomad-distro-template for elabFTW bridge (no custom image needed)."""

import os, sys, yaml

DISTRO = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NOMAD_DISTRO_DIR", os.path.expanduser("~/nomad-distro-template"))
changes = []

# 1. Patch docker-compose.yaml — use official image + startup command
dc_path = os.path.join(DISTRO, "docker-compose.yaml")
with open(dc_path) as f:
    data = yaml.safe_load(f)

for svc_name in ["app"]:
    s = data["services"].get(svc_name)
    if not s:
        continue

    # Ensure we use the OFFICIAL image (not a custom build)
    official = "ghcr.io/fairmat-nfdi/nomad-distro-template:main"
    if s.get("image") != official:
        s["image"] = official
        changes.append(f"{svc_name}: image -> {official}")

    # Add volume mount for plugins (only if not already present)
    vol_plugins = "./plugins:/app/plugins"
    if vol_plugins not in s.get("volumes", []):
        s.setdefault("volumes", []).append(vol_plugins)
        changes.append(f"{svc_name}: added plugins volume")

    # Override command to run startup.sh first
    s["command"] = "bash /app/plugins/startup.sh"
    changes.append(f"{svc_name}: command -> startup.sh")

    # Add PYTHONPATH
    env = s.setdefault("environment", {})
    if isinstance(env, dict):
        env["PYTHONPATH"] = "/app/plugins"
        changes.append(f"{svc_name}: PYTHONPATH=/app/plugins")

with open(dc_path, "w") as f:
    yaml.dump(data, f, default_flow_style=False, width=200, sort_keys=False)
changes.append("saved docker-compose.yaml")

for c in changes:
    print(f"  {c}")
