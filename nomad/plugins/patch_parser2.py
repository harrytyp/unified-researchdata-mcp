import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    content = f.read()

old_func = '''def _find_data_section(header_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
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

new_func = '''def _find_data_section(header_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """Fallback: find column headers and data by scanning for numeric rows."""
    columns = []
    units = []
    data_start = None

    # Start by finding where KEY-VALUE header ends (look for blank line)
    # and where TABULAR data begins
    kv_end = 0
    in_kv = True
    for i, line in enumerate(header_lines):
        stripped = line.strip()
        if in_kv:
            if not stripped:
                kv_end = i
                in_kv = False
                continue
            if stripped.startswith("["):
                kv_end = i
                in_kv = False
                continue
            # Check if this is not a key-value line (no tab or =)
            if "\\t" not in stripped and "=" not in stripped and stripped:
                # Might be the data section header
                in_kv = False
                continue
        # Past key-value section - look for column headers
        if not in_kv:
            stripped = line.strip()
            if stripped and "\\t" in stripped and not stripped.startswith("["):
                parts = stripped.split("\\t")
                # Check if this looks like column headers (has text, mixed content)
                # or if next line is units
                if i + 1 < len(header_lines):
                    next_parts = header_lines[i + 1].strip().split("\\t")
                    if len(next_parts) == len(parts) and all(
                        _looks_like_unit(p) for p in next_parts
                    ):
                        columns = parts
                        units = next_parts
                        data_start = i + 2
                        break
                # Also accept if NO units row: column headers with data below
                has_text_col = any(not p.strip().replace(".","").replace("-","").isdigit() for p in parts)
                if has_text_col and i > kv_end:
                    columns = parts
                    data_start = i + 1
                    break

    data_lines = header_lines[data_start:] if data_start else []
    return data_lines, columns, units'''

if old_func in content:
    content = content.replace(old_func, new_func, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched _find_data_section")
else:
    print("ERROR: Could not find old function")
    sys.exit(1)
