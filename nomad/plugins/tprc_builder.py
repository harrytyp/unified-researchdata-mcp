"""
tprc_builder.py v3 — Build .tprc from an empty TRIOS base + inserted SGMT blocks.

v3 change: instead of patching values into a foreign multi-segment template
(which left the template's own procedure steps in the file), the procedure
is now *built*: an empty .tprc (TRIOS-exported, no SGMT blocks) is used as
the base and exactly one SGMT block is inserted per entered segment, before
the LengthTagged section. Verified byte-identical against real
TRIOS-exported reference files (empty.tprc + 1 Ramp == Procedure.tprc,
and 12-segment output matches the real LBAM file block-for-block).
"""
import logging
import struct, os, json, shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Base template: a real TRIOS .tprc with *no* procedure segments (434 B,
# exported from TRIOS 6.1). Segment SGMT blocks are inserted into it.
import platform
if platform.system() == 'Windows':
    TEMPLATE_PATH = Path(r"C:\Users\go75bel\Downloads\empty.tprc")
    FALLBACK_TEMPLATE = Path(r"C:\Users\go75bel\Downloads\empty.tprc")
else:
    TEMPLATE_PATH = Path("/app/plugins/sample_files/empty.tprc")
    FALLBACK_TEMPLATE = Path("/app/plugins/sample_files/empty.tprc")

# SGMT block type bytes (verified against real TRIOS-exported files)
T_RAMP = 0x06       # 20 B: SGMT + type + flags + id + end_temp(LE@+12) + rate(LE@+16)
T_ISO = 0x04        # 16 B: duration_min at +12 (LE)
T_MASSFLOW = 0x0E   # 16 B: flow_rate at +12 (LE)
T_BALFLOW = 0x13    # 16 B: flow_rate at +12 (LE)
BLOCK_FLAGS = {
    T_RAMP: b'\x00\x03\x00',
    T_ISO: b'\x00\x03\x00',
    T_MASSFLOW: b'\x00\x03\x00',
    T_BALFLOW: b'\x00\x03\x03',
}


def _patch_be_f32(data: bytearray, offset: int, value: float):
    packed = struct.pack('>f', float(value))
    for i in range(4):
        if offset + i < len(data):
            data[offset + i] = packed[i]


def _patch_le_f32(data: bytearray, offset: int, value: float):
    """Little-endian float write (the format's value encoding)."""
    packed = struct.pack('<f', float(value))
    for i in range(4):
        if offset + i < len(data):
            data[offset + i] = packed[i]


def _patch_tlv_string(data: bytearray, marker: bytes, new_value: str):
    """Find a TLV string starting with marker and replace it."""
    idx = data.find(marker)
    if idx < 0:
        return False
    # Length byte precedes the marker
    len_pos = idx - 1
    if len_pos < 0 or data[len_pos] == 0 or data[len_pos] > 127:
        return False
    old_len = data[len_pos]
    new_bytes = new_value.encode('ascii', errors='replace')[:old_len]
    padded = new_bytes.ljust(old_len, b' ')
    data[idx:idx + old_len] = padded
    return True


def _patch_after_marker(data: bytearray, marker: bytes, new_value: str):
    """Replace TLV string that follows immediately after a marker tag."""
    idx = data.find(marker)
    if idx < 0:
        return False
    name_start = idx + len(marker)
    if name_start >= len(data) or data[name_start] == 0 or data[name_start] > 127:
        return False
    old_len = data[name_start]
    new_bytes = new_value.encode('ascii', errors='replace')[:old_len]
    padded = new_bytes.ljust(old_len, b' ')
    data[name_start + 1:name_start + 1 + old_len] = padded
    return True


def _find_sgmt_block(data: bytearray, type_byte: int, nth: int = 0):
    """Find the nth SGMT block with given type byte."""
    pos = 0
    count = 0
    while True:
        pos = data.find(b'SGMT', pos)
        if pos < 0:
            return -1
        if pos + 5 < len(data) and data[pos + 4] == type_byte:
            if count == nth:
                return pos
            count += 1
        pos += 4


def _count_sgmt_blocks(data: bytearray, type_byte: int) -> int:
    """Count how many SGMT blocks of a given type byte exist in the template."""
    count = 0
    pos = 0
    while True:
        pos = data.find(b'SGMT', pos)
        if pos < 0:
            return count
        if pos + 5 < len(data) and data[pos + 4] == type_byte:
            count += 1
        pos += 4


def _validate_segments(segments: List[Dict]) -> List[str]:
    """Check each segment has the fields it needs. Returns a list of
    human-readable problem descriptions (empty list = all valid).

    A Ramp needs both end_temp and rate. An Isothermal needs duration_min —
    it does NOT need end_temp, since an isothermal segment holds at
    whatever temperature the previous segment ended at; the .tprc format
    has no target-temperature field for this segment type (confirmed by
    inspecting real TRIOS-exported files, see build_tprc's docstring). A
    Mass Flow or Balance Flow segment needs flow_rate.
    A value of 0 is accepted (a user may genuinely want a 0 rate isn't
    physical, but a *missing* field is not the same as an intentional 0 —
    only None is rejected). A *negative* rate/flow_rate/duration is always
    rejected, regardless of segment type - this format always records these
    as positive magnitudes (direction/effect is implied by the segment type
    and its target, not by the sign of the number), so a negative value can
    only be a data-entry mistake, never an intentional value.
    """
    def _negative(seg, field):
        value = seg.get(field)
        return value is not None and value < 0

    problems = []
    for i, seg in enumerate(segments):
        seg_type = (seg.get('type') or 'Ramp').lower()
        label = f"Segment {i + 1} ({seg.get('type') or 'Ramp'})"
        if seg_type == 'ramp':
            if seg.get('end_temp') is None:
                problems.append(f"{label} is missing end_temp")
            if seg.get('rate') is None:
                problems.append(f"{label} is missing rate")
            elif _negative(seg, 'rate'):
                problems.append(f"{label} has a negative rate ({seg['rate']}) - enter it as a positive magnitude")
        elif seg_type == 'isothermal':
            if seg.get('duration_min') is None:
                problems.append(f"{label} is missing duration_min")
            elif _negative(seg, 'duration_min'):
                problems.append(f"{label} has a negative duration_min ({seg['duration_min']})")
        elif seg_type in ('mass_flow', 'balance_flow'):
            if seg.get('flow_rate') is None:
                problems.append(f"{label} is missing flow_rate")
            elif _negative(seg, 'flow_rate'):
                problems.append(f"{label} has a negative flow_rate ({seg['flow_rate']})")
        else:
            problems.append(f"{label} has unknown type {seg.get('type')!r}")
    return problems


def _make_sgmt_block(seg_type: int, block_id: int, value1: float,
                     value2: Optional[float] = None) -> bytes:
    """Build one SGMT block in the verified TRIOS layout (LE floats).

    Ramp is 20 bytes (end_temp at +12, rate at +16); all other types are
    16 bytes (single value at +12). The id field is a free-running counter
    that is never referenced elsewhere in the file (verified).
    """
    flags = BLOCK_FLAGS.get(seg_type, b'\x00\x03\x00')
    blk = bytearray(b'SGMT') + bytes([seg_type]) + flags + struct.pack('<I', block_id)
    blk += struct.pack('<f', value1)
    if value2 is not None:
        blk += struct.pack('<f', value2)
    return bytes(blk)


def build_tprc(params: Dict, segments: List[Dict], template_path: Optional[Path] = None,
               logger: Optional[logging.Logger] = None) -> bytes:
    """
    Build a .tprc by inserting one SGMT block per segment into an empty base.

    params keys:
      sample_name, procedure_name (strings)
      gas_atmosphere: 'Nitrogen' | 'Air' | etc.
    segments: ordered list of dicts, one per procedure step:
      {'type': 'Ramp', 'end_temp': <float>, 'rate': <float>}
      {'type': 'Isothermal', 'duration_min': <float>}
      {'type': 'Mass Flow', 'flow_rate': <float>}
      {'type': 'Balance Flow', 'flow_rate': <float>}
    logger: optional logger to report warnings through (e.g. NOMAD's entry
      logger, so warnings show up in the entry's processing log in the GUI
      instead of only the server's own log file).

    Every segment is validated before anything is written: a Ramp needs
    both end_temp and rate, an Isothermal needs duration_min, a Mass Flow
    or Balance Flow needs flow_rate. If any segment is incomplete, this
    raises ValueError instead of silently writing a default of 0.

    Layout (reverse-engineered from real TRIOS-exported files, confirmed by
    byte-comparing empty.tprc against a single-Ramp export of the same
    procedure): the file is a container whose procedure segments live as
    SGMT blocks directly in front of the LengthTagged section. A 4-byte
    length field at lt-4 holds the total byte size of the SGMT region, and
    the container length at offset 36 grows by the same amount. The base
    template (empty.tprc, exported from TRIOS with no segments) therefore
    yields exactly the entered segments and nothing else — no foreign
    template steps remain.

    Encoding (confirmed by comparing real TRIOS-exported .tprc files that
    differed only in one changed value, isolating each field):
      - Ramp: type byte 0x06; end_temp at +12 and rate at +16 from the
        block start, little-endian. Block size 20.
      - Isothermal: type byte 0x04; duration_min at +12, little-endian.
        No target-temperature field — holds at the previous segment's end
        temperature. Block size 16.
      - Mass Flow: type byte 0x0E; flow_rate at +12, little-endian.
        Block size 16, flags 00 03 00.
      - Balance Flow: type byte 0x13; flow_rate at +12, little-endian.
        Block size 16, flags 00 03 03.
    """
    log = logger or globals()['logger']

    problems = _validate_segments(segments)
    if problems:
        raise ValueError("Invalid temperature segments: " + "; ".join(problems))

    tmpl = template_path or TEMPLATE_PATH
    if not tmpl.exists():
        tmpl = FALLBACK_TEMPLATE

    data = bytearray(tmpl.read_bytes())

    # ── 1. Patch procedure name ──
    proc_name = params.get('procedure_name', '')
    if proc_name:
        # Try common markers in order
        for marker in [b'LBAM', b'Ramp', b'Char', b'Mass', b'Isothermal']:
            if _patch_tlv_string(data, marker, proc_name):
                break

    # ── 2. Patch sample name (after <SAMPLENAME>) ──
    sample_name = params.get('sample_name', 'Sample')
    _patch_after_marker(data, b'<SAMPLENAME>', sample_name)

    # ── 3. Build one SGMT block per entered segment, in order ──
    lt = data.find(b'\x0cLengthTagged')
    if lt < 0:
        raise ValueError("Template has no LengthTagged section - not a .tprc?")
    # 4-byte length field right before LengthTagged holds the SGMT region size
    len_field_pos = lt - 4

    blocks = bytearray()
    start_id = 903  # arbitrary free-running id, never referenced (verified)
    for i, seg in enumerate(segments):
        seg_type = (seg.get('type') or 'Ramp').lower()
        bid = start_id + i
        if seg_type == 'ramp':
            blocks += _make_sgmt_block(T_RAMP, bid, float(seg['end_temp']), float(seg['rate']))
        elif seg_type == 'isothermal':
            blocks += _make_sgmt_block(T_ISO, bid, float(seg['duration_min']))
        elif seg_type == 'mass_flow':
            blocks += _make_sgmt_block(T_MASSFLOW, bid, float(seg['flow_rate']))
        elif seg_type == 'balance_flow':
            blocks += _make_sgmt_block(T_BALFLOW, bid, float(seg['flow_rate']))

    # ── 4. Insert blocks before LengthTagged, fix the two length fields ──
    block_len = len(blocks)
    if block_len:
        data[lt:lt] = blocks
        struct.pack_into('<I', data, len_field_pos, block_len)
        c_len = struct.unpack_from('<I', data, 36)[0]
        struct.pack_into('<I', data, 36, c_len + block_len)

    # ── 5. Patch gas atmosphere in TLV strings ──
    gas = params.get('gas_atmosphere', 'Nitrogen')
    if gas:
        for marker in [b'Nitrogen', b'Air', b'Argon', b'Helium']:
            if _patch_tlv_string(data, marker, gas):
                break

    return bytes(data)


def parse_tprc(path: str) -> Dict:
    """Parse .tprc and return readable info (values little-endian, matching
    how build_tprc writes them)."""
    with open(path, 'rb') as f:
        data = bytearray(f.read())

    result = {
        'filename': Path(path).name,
        'size': len(data),
        'procedure_name': '',
        'sample_name': '',
        'segments': [],
    }

    # Extract sample name
    for m in [b'<SAMPLENAME>', b'SampleName', b'SAMPLE']:
        pos = data.find(m)
        if pos >= 0:
            ns = pos + len(m)
            if ns < len(data) and 1 <= data[ns] <= 100 and ns + 1 + data[ns] < len(data):
                result['sample_name'] = data[ns+1:ns+1+data[ns]].decode('ascii', errors='replace').strip()
                break

    # Extract procedure name
    for marker in [b'LBAM', b'Procedure']:
        pos = data.find(marker)
        if pos >= 0:
            lp = pos - 1
            if lp > 0 and 1 <= data[lp] <= 100:
                result['procedure_name'] = data[pos:pos+data[lp]].decode('ascii', errors='replace').strip()
                break

    # SGMT blocks: the SGMT region begins right after a 4-byte length field
    # (which holds the region's total byte size) and ends at the
    # LengthTagged marker. Locate the region via the first 'SGMT' after the
    # header area (~offset 88+), read the length field before it, and take
    # every procedure-type SGMT block inside [start, start+region_len).
    lt = data.find(b'\x0cLengthTagged')
    # first standalone SGMT in the block area (after header GUIDs ~off 44-88)
    first = -1
    pos = 88
    while True:
        pos = data.find(b'SGMT', pos)
        if pos < 0 or (lt >= 0 and pos >= lt):
            break
        first = pos
        break
    if first >= 0 and first >= 4:
        region_len = struct.unpack_from('<I', data, first - 4)[0]
        region_start = first
        region_end = min(first + region_len, lt if lt >= 0 else len(data))
        pos = region_start
        while pos + 4 <= region_end:
            if data[pos:pos + 4] != b'SGMT':
                pos += 1
                continue
            typ = data[pos + 4]
            if typ in (T_RAMP, T_ISO, T_MASSFLOW, T_BALFLOW):
                try:
                    v1 = struct.unpack('<f', data[pos+12:pos+16])[0]
                except Exception:
                    v1 = 0.0
                v2 = None
                if typ == T_RAMP and pos + 20 <= len(data):
                    try:
                        v2 = struct.unpack('<f', data[pos+16:pos+20])[0]
                    except Exception:
                        v2 = 0.0
                block_len = 20 if typ == T_RAMP else 16
                result['segments'].append({
                    'offset': pos,
                    'type': typ,
                    'length': block_len,
                    'value1': round(v1, 4),
                    'value2': round(v2, 4) if v2 is not None else None,
                })
                pos += block_len
            else:
                pos += 4

    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        r = parse_tprc(sys.argv[1])
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0)

    # Build and self-check
    params = {
        'sample_name': 'Test Kollidon',
        'procedure_name': 'Ramp 10Kmin 400C N2',
        'gas_atmosphere': 'Nitrogen',
    }
    segments = [
        {'type': 'Ramp', 'end_temp': 400, 'rate': 10},
        {'type': 'Isothermal', 'duration_min': 30},
    ]
    tprc = build_tprc(params, segments)
    out = Path(__file__).parent / 'test_output.tprc'
    out.write_bytes(tprc)
    print(f"Built: {out} ({len(tprc)} bytes)")
    r = parse_tprc(str(out))
    print(f"Parsed: sample={r['sample_name']!r}")
    for s in r['segments']:
        tn = {0x0E: 'MassFlow', 0x06: 'Ramp', 0x04: 'Iso', 0x13: 'BalFlow'}.get(s['type'], hex(s['type']))
        print(f"  [{tn}] v1={s['value1']} v2={s['value2']}")
