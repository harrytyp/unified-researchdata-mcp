#!/usr/bin/env python3
"""Fix duplicate column names in _parse_xlsx."""
import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    c = f.read()

old_code = '''    if columns:
        for col in columns:
            col_lower = col.lower().replace(" ", "_")
            signals[col_lower] = []

        for row in data_rows:
            for j, col in enumerate(columns):
                if j < len(row):
                    col_lower = col.lower().replace(" ", "_")
                    try:
                        val = float(str(row[j]).strip())
                        signals[col_lower].append(val)
                    except (ValueError, IndexError):
                        signals[col_lower].append(float("nan"))'''

new_code = '''    if columns:
        # Create unique column names
        col_names = []
        seen = {}
        for i, col in enumerate(columns):
            col_lower = col.lower().replace(" ", "_")
            if col_lower in seen:
                seen[col_lower] += 1
                col_lower = f"{col_lower}_{seen[col_lower]}"
            else:
                seen[col_lower] = 1
            col_names.append(col_lower)
            signals[col_lower] = []

        for row in data_rows:
            for j, col_name in enumerate(col_names):
                if j < len(row):
                    try:
                        val = float(str(row[j]).strip())
                        signals[col_name].append(val)
                    except (ValueError, IndexError):
                        signals[col_name].append(float("nan"))'''

if old_code in c:
    c = c.replace(old_code, new_code)
    with open(path, "w") as f:
        f.write(c)
    print("Fixed duplicate column names in _parse_xlsx")
else:
    print("Old code not found, checking current state...")
    # Find the signals initialization code
    if "col_lower = col.lower()" in c:
        print("Found col_lower pattern, but exact match failed")
    else:
        print("Pattern not found")
