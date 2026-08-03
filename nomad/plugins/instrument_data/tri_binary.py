"""Parser for raw TA Instruments TRIOS `.tri` measurement files.

`.tri` files are NOT the TRIOS-exported CSV/TXT format that `parser.py`
handles -- they are TRIOS' own binary format. Reverse-engineered from
real sample files (see Desktop/e_conversion/FIND.md and hex_compare.py):

- The file opens with a flat sequence of (key, value) string pairs.
- Each string (key or value) is prefixed by its length, encoded as a
  .NET-style "7-bit encoded int" (BinaryWriter.Write(string) format):
  each byte contributes 7 bits, low-to-high; if the high bit (0x80) is
  set, another byte follows. This is why fixed byte offsets do NOT work
  across files -- a single 13-char sample name vs. a 20-char one shifts
  every field after it. Confirmed empirically: `instrumenttype` sits at
  a constant offset (26) across files because nothing variable precedes
  it, but `samplename` and everything after it shifts file to file.
- After the flat header, the file continues into `VERSIONED`/`SGMT`
  binary blocks (segment/calibration records) and eventually the raw
  signal data -- not handled here.

Only the ~10 header fields below were confirmed present as plain text.
`sample_mass` and `gas_atmosphere` were searched for and NOT found in
this header on real TGA samples -- do not assume they're parseable
this way without further reverse-engineering. Flag to the team rather
than guessing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

# Keys we know appear in the flat header, in the order TRIOS writes them.
KNOWN_HEADER_KEYS = (
    "instrumenttype",
    "instrumentserialnumber",
    "instrumentname",
    "companyname",
    "rundate",
    "culture",
    "ticks",
    "operator",
    "project",
    "samplename",
    "comments",
    "instrumentmode",
    "testtype",
    "pantype",
    "samplepannumber",
    "samplepannumberb",
    "samplepannumberc",
    "procedurename",
    "proceduresegments",
    "proceduresignals",
    "procedureGUID",
)


def read_7bit_length(data: bytes, offset: int) -> Tuple[int, int]:
    """Decode a .NET 7-bit-encoded length prefix starting at offset.

    Returns (length, offset_after_length_bytes).
    """
    result = 0
    shift = 0
    pos = offset
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
        if shift > 35:
            raise ValueError(f"7-bit length prefix too long at offset {offset}")
    return result, pos


def read_length_prefixed_string(data: bytes, offset: int) -> Tuple[str, int]:
    """Read one (length-prefixed) string starting at offset.

    Returns (decoded_string, offset_after_string). Uses cp1252 since
    TRIOS embeds Windows-native characters like '°' as single bytes
    (0xB0), which is not valid UTF-8.
    """
    length, pos = read_7bit_length(data, offset)
    raw = data[pos:pos + length]
    return raw.decode("cp1252", errors="replace"), pos + length


def parse_tri_header(filepath: str, max_pairs: int = 40) -> Dict[str, str]:
    """Parse the flat key/value header at the start of a .tri file.

    Walks the file as alternating (key, value) length-prefixed string
    pairs starting right before the first known key ('instrumenttype').
    Stops after `max_pairs` pairs or as soon as a decoded key doesn't
    look like a plausible field name (signals we've walked into the
    binary VERSIONED/SGMT section that follows the header).
    """
    data = Path(filepath).read_bytes()

    start_key = b"instrumenttype"
    key_idx = data.find(start_key)
    if key_idx < 0:
        raise ValueError(f"Could not find header start marker in {filepath}")

    # Back up to the length byte that precedes the first key.
    offset = key_idx - 1
    if data[offset] != len(start_key):
        raise ValueError(
            f"Unexpected length byte before '{start_key.decode()}' in {filepath}: "
            f"got {data[offset]}, expected {len(start_key)}"
        )

    result: Dict[str, str] = {}
    pos = offset
    for _ in range(max_pairs):
        try:
            key, pos = read_length_prefixed_string(data, pos)
        except (IndexError, ValueError):
            break
        if not key or not key.isprintable() or len(key) > 64:
            break
        try:
            value, pos = read_length_prefixed_string(data, pos)
        except (IndexError, ValueError):
            break
        result[key] = value

    return result


def extract_key_fields(filepath: str) -> Dict[str, Optional[str]]:
    """Extract the fields we actually need for the NOMAD schema.

    NOTE: sample_mass and gas_atmosphere are intentionally NOT included
    here -- they were not found as plain text in the header on real
    samples. procedure_name often carries the gas as a free-text
    convention (e.g. "...400 C N2") but that is not a reliable
    structured source; flag with Kolja before relying on it.
    """
    header = parse_tri_header(filepath)
    return {
        "sample_name": header.get("samplename"),
        "operator": header.get("operator"),
        "instrument_name": header.get("instrumentname"),
        "instrument_type": header.get("instrumenttype"),
        "run_date": header.get("rundate"),
        "procedure_name": header.get("procedurename"),
        "procedure_segments": header.get("proceduresegments"),
        "crucible_type": header.get("pantype"),
        "pan_number": header.get("samplepannumber"),
    }


if __name__ == "__main__":
    import json
    import sys

    for f in sys.argv[1:]:
        print(f"\n=== {f} ===")
        print(json.dumps(extract_key_fields(f), indent=2, ensure_ascii=False))
