import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    content = f.read()

old = "    return None"

new = """    # Check for TGA column headers in CSV
    head_lower = head.lower()
    lines = head.split("\\n")
    header_line = lines[0] if lines else ""
    tga_indicators = ["value/mg", "temp./c", "delta/c/min", "sample weight", "weight/mg"]
    tga_hits = sum(1 for ind in tga_indicators if ind in header_line.lower())
    if tga_hits >= 2:
        return "tga"
    return None"""

if old in content:
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched detect_format with header checks")
else:
    print("Could not find 'return None' target")
    sys.exit(1)
