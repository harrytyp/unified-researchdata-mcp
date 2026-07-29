#!/usr/bin/env python3
"""Fix xlsx parser to accept binary files and handle both xlsx and txt formats."""
import sys

# Fix 1: tga_parser.py - accept xlsx files in is_mainfile
path1 = "/home/debian/nomad-distro-template/plugins/instrument_data/tga_parser.py"
with open(path1) as f:
    c1 = f.read()

old = """        if not decoded_buffer:
# Accept xlsx files by extension and MIME type        if filename.lower().endswith((\".xlsx\", \".xls\")):            return True        if \"spreadsheet\" in (mime or \"\"):            return True
            return False"""

new = """        if not decoded_buffer:
            # Accept xlsx files by extension and MIME type
            if filename.lower().endswith((".xlsx", ".xls")):
                return True
            if "spreadsheet" in (mime or ""):
                return True
            return False"""

if old in c1:
    c1 = c1.replace(old, new)
    with open(path1, "w") as f:
        f.write(c1)
    print("1. Fixed is_mainfile for xlsx")
else:
    print("1. Pattern not found in tga_parser.py")

# Fix 2: parser.py - improve xlsx metadata extraction from filename
path2 = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path2) as f:
    c2 = f.read()

old_meta = """    # Extract metadata from procedure row (row 0 in TRIOS xlsx)
    if not metadata and step_idx > 0:
        proc_row = all_rows[0]
        proc_text = str(proc_row[0]) if proc_row and proc_row[0] else ""
        if proc_text:
            metadata["procedure_name"] = proc_text

    # Extract metadata from filename if available
    if "sample_name" not in metadata:
        basename = os.path.basename(filepath).replace(".xlsx", "").replace(".xls", "")
        metadata["sample_name"] = basename"""

new_meta = """    # Extract metadata from procedure row (row 0 in TRIOS xlsx)
    if not metadata and step_idx > 0:
        proc_row = all_rows[0]
        proc_text = str(proc_row[0]) if proc_row and proc_row[0] else ""
        if proc_text:
            metadata["procedure_name"] = proc_text

    # Extract metadata from filename if available
    basename = os.path.basename(filepath).replace(".xlsx", "").replace(".xls", "")
    if "sample_name" not in metadata:
        metadata["sample_name"] = basename

    # Parse heating rate from filename (e.g. "5KMIN")
    import re as _re
    rate_match = _re.search(r'(\d+)KMIN', basename)
    if rate_match and "heating_rate" not in metadata:
        metadata["heating_rate"] = f\"{rate_match.group(1)} K/min\"

    # Parse gas from filename (e.g. "N2")
    gas_match = _re.search(r'\\b(N2|Air|O2|Ar|He)\\b', basename)
    if gas_match and "gas_atmosphere" not in metadata:
        metadata["gas_atmosphere"] = gas_match.group(1)

    # Parse temperature from filename (e.g. "1000C")
    temp_match = _re.search(r'(\\d+)C\\b', basename)
    if temp_match and "temperature_end" not in metadata:
        metadata["temperature_end\"] = f\"{temp_match.group(1)} C\""""

c2 = c2.replace(old_meta, new_meta, 1)
with open(path2, "w") as f:
    f.write(c2)
print("2. Updated xlsx metadata extraction from filename")

# Fix 3: Also improve txt metadata extraction for files like DMA_PTDB...
old_gas = """    # Gas atmosphere
    for key in ["gas_atmosphere", "gas atmosphere", "gas_type", "gas type"]:
        if key in metadata:
            result["gas_atmosphere"] = metadata[key]
            break"""

new_gas = """    # Gas atmosphere
    for key in ["gas_atmosphere", "gas atmosphere", "gas_type", "gas type",
                "purge_gas", "purge gas", "atmosphere"]:
        if key in metadata:
            result["gas_atmosphere"] = metadata[key]
            break

    # Heating rate from procedure segments
    if "heating_rate" not in result:
        proc_segs = metadata.get("proceduresegments", "")
        rate_m = _re.search(r'Ramp\\s+(\\d+\\.?\\d*)\\s*°?C/min', proc_segs, _re.IGNORECASE)
        if rate_m:
            result["heating_rate"] = f\"{rate_m.group(1)} K/min\""""

c2 = c2.replace(old_gas, new_gas, 1)
with open(path2, "w") as f:
    f.write(c2)
print("3. Updated txt metadata extraction for gas and heating rate")
