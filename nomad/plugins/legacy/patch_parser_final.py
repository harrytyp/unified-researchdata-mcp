import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    c = f.read()

# Patch 1: detect_format - add TGA column header check (before final return None)
old1 = "    return None\n\n\ndef parse_file(filepath: str) -> Dict[str, Any]:"
new1 = """    # Check for TGA column headers in CSV
    head_lower = head.lower()
    lines = head.split("\\n")
    header_line = lines[0] if lines else ""
    tga_indicators = ["value/mg", "temp./c", "delta/c/min", "sample weight", "weight/mg"]
    tga_hits = sum(1 for ind in tga_indicators if ind in header_line.lower())
    if tga_hits >= 2:
        return "tga"
    return None

def parse_file(filepath: str) -> Dict[str, Any]:"""

c = c.replace(old1, new1, 1)
print("P1: detect_format header check")

# Patch 2: _find_data_section - handle data after blank line (no units row)
old2 = '''def _find_data_section(header_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """Fallback: find column headers and data by scanning for numeric rows."""
    columns = []
    units = []
    data_start = None

    for i, line in enumerate(header_lines):
        stripped = line.strip()
        # Look for a row that looks like column headers (alphabetic + special chars)
        if stripped and "\\t" in stripped and not stripped.startswith("["):
            parts = stripped.split("\\t")
            # Check if next line looks like units
            if i + 1 < len(header_lines):
                next_line = header_lines[i + 1].strip()
                next_parts = next_line.split("\\t")
                if len(next_parts) == len(parts) and all(
                    _looks_like_unit(p) for p in next_parts
                ):
                    columns = parts
                    units = next_parts
                    data_start = i + 2
                    break

    data_lines = header_lines[data_start:] if data_start else []
    return data_lines, columns, units'''

new2 = '''def _find_data_section(header_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """Fallback: find column headers and data by scanning for numeric rows."""
    columns = []
    units = []
    data_start = None

    for i, line in enumerate(header_lines):
        stripped = line.strip()
        # Skip key-value header lines and blank lines
        if not stripped:
            continue
        if stripped.startswith("["):
            continue
        if "\\t" not in stripped:
            continue
        # Look for a row that looks like column headers (has text, not purely numeric)
        parts = stripped.split("\\t")
        has_text = any(not p.strip().replace(".","").replace("-","").replace("e","").replace("E","").isdigit() for p in parts)
        if not has_text:
            continue
        # Found potential column header row
        # Check if next line looks like units
        if i + 1 < len(header_lines):
            next_parts = header_lines[i + 1].strip().split("\\t")
            if len(next_parts) == len(parts) and all(
                _looks_like_unit(p) for p in next_parts
            ):
                columns = [c.strip() for c in parts]
                units = [u.strip() for u in next_parts]
                data_start = i + 2
                break
        # No units row - this line IS the column header
        columns = [c.strip() for c in parts]
        data_start = i + 1
        break

    data_lines = header_lines[data_start:] if data_start else []
    return data_lines, columns, units'''

c = c.replace(old2, new2, 1)
print("P2: _find_data_section")

# Patch 3: extract_tga_metadata - add sample_weight, gas_atmosphere, heating_rate, temperature_end
old3 = """    # Mass
    for key in [\"sample_mass\", \"sample mass\"]:"""

new3 = """    # Mass (also check sample_weight)
    for key in [\"sample_mass\", \"sample mass\", \"sample_weight\", \"sample weight\"]:"""

c = c.replace(old3, new3, 1)
print("P3a: sample_weight in mass detection")

# Add gas_atmosphere before return result
old_return = "    # Procedure"
new_return_start = """    # Gas atmosphere
    for key in [\"gas_atmosphere\", \"gas atmosphere\"]:
        if key in metadata:
            result[\"gas_atmosphere\"] = metadata[key]
            break

    # Heating rate
    for key in [\"heating_rate\", \"heating rate\"]:
        if key in metadata:
            result[\"heating_rate\"] = metadata[key]
            break

    # Temperature end
    for key in [\"temperature_end\", \"temperature end\"]:
        if key in metadata:
            result[\"temperature_end\"] = metadata[key]
            break

    # Procedure"""

# The issue: old_return appears ONCE per function. Let me check its context.
# Actually, "    # Procedure" appears only in extract_tga_metadata.
# But let me be more specific to avoid ambiguity.
if old_return in c:
    c = c.replace(old_return, new_return_start, 1)
    print("P3b: added gas_atmosphere, heating_rate, temperature_end")
else:
    print("WARNING: Could not find Procedure comment")

with open(path, "w") as f:
    f.write(c)

# Verify
with open(path) as f:
    content = f.read()
gas_count = content.count("gas_atmosphere")
print(f"gas_atmosphere instances: {gas_count}")
if gas_count != 2:  # one in function body, one in comment could vary
    print("WARNING: gas_atmosphere count unexpected")

print("\nDone!")
