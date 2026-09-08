"""Patch parser.py to add xlsx support."""
import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    c = f.read()

# Add openpyxl import after other imports
c = c.replace(
    "import os",
    "import os\nimport openpyxl"
)

# Replace detect_format to handle xlsx
old_detect = '''def detect_format(filepath: str) -> Optional[str]:
    """Detect instrument type from file content.

    Returns 'tga', 'dma', 'ftir', 'ms', or None if unknown.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        head = f.read(4096)'''

new_detect = '''def detect_format(filepath: str) -> Optional[str]:
    """Detect instrument type from file content.

    Returns 'tga', 'dma', 'ftir', 'ms', or None if unknown.
    """
    if filepath.lower().endswith(".xlsx"):
        return _detect_xlsx_format(filepath)

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        head = f.read(4096)'''

c = c.replace(old_detect, new_detect, 1)

# Replace parse_file to handle xlsx
old_parse = '''def parse_file(filepath: str) -> Dict[str, Any]:
    """Parse a TRIOS-exported CSV/TXT file.

    Returns dict with:
        format: detected instrument type ('tga', 'dma', etc.)
        metadata: dict of key-value pairs from header
        signals: dict of signal_name -> list[float]
        signal_units: dict of signal_name -> unit string
        columns: list of column header names
        raw_header: full header text before data section
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()'''

new_parse = '''def parse_file(filepath: str) -> Dict[str, Any]:
    """Parse a TRIOS-exported file (CSV/TXT/XLSX).

    Returns dict with:
        format: detected instrument type ('tga', 'dma', etc.)
        metadata: dict of key-value pairs from header
        signals: dict of signal_name -> list[float]
        signal_units: dict of signal_name -> unit string
        columns: list of column header names
        raw_header: full header text before data section
    """
    if filepath.lower().endswith(".xlsx"):
        return _parse_xlsx(filepath)

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()'''

c = c.replace(old_parse, new_parse, 1)

# Add helper functions before _split_sections
xlsx_helpers = '''

# ── XLSX support ─────────────────────────────────────────────────────────────

def _detect_xlsx_format(filepath: str) -> Optional[str]:
    """Detect instrument type from xlsx file."""
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
        ws = wb.active

        # Read first 50 rows looking for indicators
        tga_indicators = ["weight", "mg", "temperature", "thermogravimetric", "tga"]
        dma_indicators = ["modulus", "tan", "strain", "dynamic mechanical", "dma"]
        ftir_indicators = ["wavenumber", "absorbance", "transmittance", "infrared"]
        ms_indicators = ["m/z", "mass", "intensity", "mass spectrom"]

        all_text = []
        for i, row in enumerate(ws.iter_rows(max_row=50, values_only=True)):
            for cell in row:
                if cell:
                    all_text.append(str(cell).lower())

        wb.close()

        text = " ".join(all_text)

        if any(kw in text for kw in tga_indicators):
            return "tga"
        if any(kw in text for kw in dma_indicators):
            return "dma"
        if any(kw in text for kw in ftir_indicators):
            return "ftir"
        if any(kw in text for kw in ms_indicators):
            return "ms"
    except Exception:
        pass

    return None


def _parse_xlsx(filepath: str) -> Dict[str, Any]:
    """Parse a TRIOS xlsx export file."""
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    # Read all rows
    all_rows = []
    for row in ws.iter_rows(values_only=True):
        all_rows.append([str(v) if v is not None else "" for v in row])

    wb.close()

    # Find the [step] header
    step_idx = None
    for i, row in enumerate(all_rows):
        if row and "[step]" in str(row[0]).strip():
            step_idx = i
            break

    if step_idx is None:
        # Try to find header row by looking for column names
        for i, row in enumerate(all_rows):
            row_str = " ".join(str(v).lower() for v in row if v)
            if any(kw in row_str for kw in ["time", "temperature", "weight"]):
                step_idx = i - 1
                break

    if step_idx is None:
        return {"format": None, "metadata": {}, "signals": {}, "signal_units": {}, "columns": [], "raw_header": ""}

    # Parse header (everything before [step])
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

    # Parse step section
    step_rows = all_rows[step_idx + 1:]
    if not step_rows:
        return {"format": "tga", "metadata": metadata, "signals": {}, "signal_units": {}, "columns": [], "raw_header": "\\n".join(raw_lines)}

    # Find column headers and units
    columns = []
    units = []
    data_start = 0

    for i, row in enumerate(step_rows):
        vals = [str(v).strip() for v in row if v]
        # Check if this looks like column headers
        has_text = any(not v.replace(".", "").replace("-", "").replace("e", "").replace("E", "").isdigit() for v in vals)
        if has_text and len(vals) >= 3:
            columns = [v for v in vals]
            # Check next row for units
            if i + 1 < len(step_rows):
                next_vals = [str(v).strip() for v in step_rows[i + 1] if v]
                if len(next_vals) == len(columns) and all(_looks_like_unit(v) for v in next_vals):
                    units = next_vals
                    data_start = i + 2
                else:
                    data_start = i + 1
            break

    # Parse data rows
    data_rows = step_rows[data_start:]
    signals = {}
    signal_units = {}

    if columns:
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
                        signals[col_lower].append(float("nan"))

    return {
        "format": _detect_xlsx_format(filepath),
        "metadata": metadata,
        "signals": signals,
        "signal_units": {k: "" for k in signals},
        "columns": list(signals.keys()),
        "raw_header": "\\n".join(raw_lines)
    }

'''

c = c.replace("\ndef _split_sections(", xlsx_helpers + "\ndef _split_sections(")

with open(path, "w") as f:
    f.write(c)
print("Added xlsx support to parser.py")
