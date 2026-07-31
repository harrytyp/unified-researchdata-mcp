#!/usr/bin/env python3
"""Find elabFTW API key from running processes."""
import os

for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        cmdline = open(f"/proc/{entry}/cmdline").read()
        if "processor" in cmdline:
            env_data = open(f"/proc/{entry}/environ").read()
            for var in env_data.split("\0"):
                if "ELABFTW_API_KEY" in var:
                    key = var.split("=", 1)[1] if "=" in var else var
                    print(f"PID {entry}: KEY={key}")
    except (IOError, OSError):
        pass
