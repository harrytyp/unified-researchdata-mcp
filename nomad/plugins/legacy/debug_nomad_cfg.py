#!/usr/bin/env python3
"""Debug nomad plugin registration issue."""
import sys, importlib

sys.path.insert(0, "/app/plugins")
import nomad.config
import inspect

src = inspect.getsource(nomad.config)

# Check if _plugins is initialized at module level
print("Module-level code (first 30 lines):")
for line in src.split("\n")[:30]:
    print(line)

# Check load_plugins calls
print("\nload_plugins references:")
for line in src.split("\n"):
    if "load_plugins" in line:
        print(f"  {line.strip()}")
