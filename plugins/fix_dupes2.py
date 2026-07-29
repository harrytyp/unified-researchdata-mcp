#!/usr/bin/env python3
"""Fix duplicate entry_id=entry_id in processor.py"""
import sys

path = "/app/plugins/instrument_data/processor.py"
with open(path) as f:
    lines = f.readlines()

# Find the section with duplicate entry_id entries (around line 320, in push_tga_to_elabftw)
entry_found = False
for i in range(300, 400):
    if i >= len(lines):
        break
    if "entry_id=entry_id," in lines[i]:
        if not entry_found:
            entry_found = True  # First one is fine
        else:
            lines[i] = ""  # Remove subsequent duplicates
            print(f"Removed duplicate entry_id at line {i+1}")

with open(path, "w") as f:
    f.writelines(lines)

# Verify
import subprocess
result = subprocess.run(
    ["sudo", "docker", "exec", "nomad_oasis_app", "python3", "-c",
     "import sys; sys.path.insert(0,\"/app/plugins\"); from instrument_data.processor import process_tga_file; from instrument_data.elabftw_client import ElabftwClient; print(\"OK\")"],
    capture_output=True, text=True, timeout=15
)
print(result.stdout.strip())
if result.stderr:
    print("ERROR:", result.stderr[:200])
