"""Fix xlsx parser to extract metadata from procedure row and filename."""
import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    c = f.read()

# Find _parse_xlsx function and add metadata extraction
old = '''    # Parse header (everything before [step])
    metadata = {}
    raw_lines = []
    for i in range(step_idx):
        row = all_rows[i]
        line = "\\t".join(str(v) for v in row if v)
        if not line.strip():
            continue
        raw_lines.append(line)
        if "\\t" in line:
            key, _, val = line.partition("\\t")
            key_stripped = key.strip().lower().replace(" ", "_")
            metadata[key_stripped] = val.strip()
        elif "=" in line:
            key, _, val = line.partition("=")
            metadata[key.strip().lower().replace(" ", "_")] = val.strip()'''

new = '''    # Parse header (everything before [step])
    metadata = {}
    raw_lines = []
    for i in range(step_idx):
        row = all_rows[i]
        line = "\\t".join(str(v) for v in row if v)
        if not line.strip():
            continue
        raw_lines.append(line)
        if "\\t" in line:
            key, _, val = line.partition("\\t")
            key_stripped = key.strip().lower().replace(" ", "_")
            metadata[key_stripped] = val.strip()
        elif "=" in line:
            key, _, val = line.partition("=")
            metadata[key.strip().lower().replace(" ", "_")] = val.strip()

    # Extract metadata from procedure row (row 0 in TRIOS xlsx)
    if not metadata and step_idx > 0:
        proc_row = all_rows[0]
        proc_text = str(proc_row[0]) if proc_row and proc_row[0] else ""
        if proc_text:
            metadata["procedure_name"] = proc_text

    # Extract metadata from filename if available
    if "sample_name" not in metadata:
        basename = os.path.basename(filepath).replace(".xlsx", "").replace(".xls", "")
        metadata["sample_name"] = basename'''

c = c.replace(old, new, 1)

with open(path, "w") as f:
    f.write(c)
print("Fixed _parse_xlsx to extract metadata from procedure row and filename")
