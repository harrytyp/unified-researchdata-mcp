"""
tprc_builder.py v2 — Build .tprc by modifying a real template file.
"""
import logging
import struct, os, json, shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Template path (use a real .tprc as base)
import platform
if platform.system() == 'Windows':
    TEMPLATE_PATH = Path(r"C:\Users\go75bel\Downloads\tgafiles_new\Matching data 1_PROCEDURE TGA_LBAM Hofmann 10K min 400 C N2.tprc")
    FALLBACK_TEMPLATE = Path(r"C:\Users\go75bel\Downloads\tgaautomation\sample files\TGA_Char yield 1Cmin 1000C.tprc")
else:
    TEMPLATE_PATH = Path("/app/plugins/sample_files/TGA_Char yield 1Cmin 1000C.tprc")
    FALLBACK_TEMPLATE = Path("/home/debian/tga_service/Matching_data_1_PROCEDURE_TGA_LBAM_Hofmann_10K_min_400_C_N2.tprc")


def _patch_be_f32(data: bytearray, offset: int, value: float):
    packed = struct.pack('>f', float(value))
    for i in range(4):
        if offset + i < len(data):
            data[offset + i] = packed[i]


def _patch_le_f32(data: bytearray, offset: int, value: float):
    """Same as _patch_be_f32 but little-endian — the isothermal duration
    field uses the opposite byte order from every other field we've found
    in this format, confirmed by comparing real TRIOS-exported files."""
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
    only None is rejected).
    """
    problems = []
    for i, seg in enumerate(segments):
        seg_type = (seg.get('type') or 'Ramp').lower()
        label = f"Segment {i + 1} ({seg.get('type') or 'Ramp'})"
        if seg_type == 'ramp':
            if seg.get('end_temp') is None:
                problems.append(f"{label} is missing end_temp")
            if seg.get('rate') is None:
                problems.append(f"{label} is missing rate")
        elif seg_type == 'isothermal':
            if seg.get('duration_min') is None:
                problems.append(f"{label} is missing duration_min")
        elif seg_type in ('mass_flow', 'balance_flow'):
            if seg.get('flow_rate') is None:
                problems.append(f"{label} is missing flow_rate")
        else:
            problems.append(f"{label} has unknown type {seg.get('type')!r}")
    return problems


def build_tprc(params: Dict, segments: List[Dict], template_path: Optional[Path] = None,
               logger: Optional[logging.Logger] = None) -> bytes:
    """
    Build a .tprc by patching a template.

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
    raises ValueError instead of silently patching a default of 0 — a
    half-filled segment must not produce a "successful" but physically
    meaningless procedure file.

    Each valid segment is then patched into the nth SGMT block of its
    matching type in the template (Ramp -> 0x06, Isothermal -> 0x04,
    Mass Flow -> 0x0E, Balance Flow -> 0x13), in the order the segments
    were entered. The template only has a fixed number of SGMT blocks of
    each type, so segments beyond that count cannot be written and are
    skipped with a logged warning.

    Encoding (all confirmed by comparing real TRIOS-exported .tprc files
    that differed only in one changed value, isolating each field):
      - Isothermal segment type byte is 0x04, not 0x05 as earlier code
        assumed; duration_min lives at +12 from the block's "SGMT" marker,
        little-endian. There is no target-temperature field in this block
        type — an isothermal segment holds at whatever temperature the
        preceding segment ended at, so end_temp is not written for it.
      - Ramp: end_temp lives at +12 and rate at +16, both little-endian —
        not +8/+12 big-endian as earlier code assumed. Confirmed both with
        isolated single-Ramp test files (only temp changed, only rate
        changed) and by re-reading a real multi-segment template file,
        where the corrected offsets produced sensible values matching the
        file's own name (e.g. "1Cmin 1000C" -> rate=1.0, end_temp=1000.0)
        while the old offsets produced garbage.
      - Mass Flow (0x0E) and Balance Flow (0x13): flow_rate lives at +12,
        little-endian — same "+12, little-endian" pattern as the other
        segment types' primary value. Confirmed against a real multi-segment
        operator file (matched TRIOS's displayed "200.00 mL/min" exactly).
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

    # ── 3. Patch each segment into its matching SGMT block, in order ──
    max_ramp = _count_sgmt_blocks(data, 0x06)
    max_iso = _count_sgmt_blocks(data, 0x04)
    max_mass_flow = _count_sgmt_blocks(data, 0x0E)
    max_balance_flow = _count_sgmt_blocks(data, 0x13)
    ramp_count = 0
    iso_count = 0
    mass_flow_count = 0
    balance_flow_count = 0
    for i, seg in enumerate(segments):
        seg_type = (seg.get('type') or 'Ramp').lower()
        if seg_type == 'ramp':
            idx = _find_sgmt_block(data, 0x06, ramp_count)
            if idx >= 0:
                # Confirmed against real TRIOS-exported files (isolated
                # single-Ramp segments, only one variable changed at a time):
                # target temperature lives at +12 and rate at +16, both
                # little-endian - not +8/+12 big-endian as previously assumed.
                _patch_le_f32(data, idx + 12, float(seg['end_temp']))  # Target temperature
                _patch_le_f32(data, idx + 16, float(seg['rate']))      # Heating rate
            else:
                log.warning(
                    "Template only has %d Ramp slot(s); segment %d (Ramp to %s) not written",
                    max_ramp, i + 1, seg.get('end_temp'))
            ramp_count += 1
        elif seg_type == 'isothermal':
            idx = _find_sgmt_block(data, 0x04, iso_count)
            if idx >= 0:
                _patch_le_f32(data, idx + 12, float(seg['duration_min']))  # Hold duration (minutes)
            else:
                log.warning(
                    "Template only has %d Isothermal slot(s); segment %d (Isothermal, %s min) not written",
                    max_iso, i + 1, seg.get('duration_min'))
            iso_count += 1
        elif seg_type == 'mass_flow':
            idx = _find_sgmt_block(data, 0x0E, mass_flow_count)
            if idx >= 0:
                _patch_le_f32(data, idx + 12, float(seg['flow_rate']))  # Sample purge flow (mL/min)
            else:
                log.warning(
                    "Template only has %d Mass Flow slot(s); segment %d (Mass Flow, %s mL/min) not written",
                    max_mass_flow, i + 1, seg.get('flow_rate'))
            mass_flow_count += 1
        elif seg_type == 'balance_flow':
            idx = _find_sgmt_block(data, 0x13, balance_flow_count)
            if idx >= 0:
                _patch_le_f32(data, idx + 12, float(seg['flow_rate']))  # Balance purge flow (mL/min)
            else:
                log.warning(
                    "Template only has %d Balance Flow slot(s); segment %d (Balance Flow, %s mL/min) not written",
                    max_balance_flow, i + 1, seg.get('flow_rate'))
            balance_flow_count += 1

    # ── 4. Patch gas atmosphere in TLV strings ──
    gas = params.get('gas_atmosphere', 'Nitrogen')
    if gas:
        for marker in [b'Nitrogen', b'Air', b'Argon', b'Helium']:
            if _patch_tlv_string(data, marker, gas):
                break

    return bytes(data)


def parse_tprc(path: str) -> Dict:
    """Parse .tprc and return readable info."""
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
    
    # Find SGMT blocks  
    pos = 0
    while True:
        pos = data.find(b'SGMT', pos)
        if pos < 0: break
        if pos + 24 <= len(data):
            block = data[pos:pos+24]
            params = []
            for off in [8, 12, 16]:
                try:
                    v = struct.unpack('>f', block[off:off+4])[0]
                    params.append(round(v, 1))
                except: params.append(0)
            result['segments'].append({
                'offset': pos,
                'type': block[4] if len(block) > 4 else 0,
                'params': params,
            })
        pos += 4
    
    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        r = parse_tprc(sys.argv[1])
        print(json.dumps(r, indent=2, default=str))
        sys.exit(0)
    
    # Build and compare
    params = {
        'sample_name': 'Test Kollidon',
        'procedure_name': 'Ramp 10Kmin 400C N2',
        'gas_atmosphere': 'Nitrogen',
    }
    segments = [{'type': 'Ramp', 'end_temp': 400, 'rate': 10}]
    tprc = build_tprc(params, segments)
    out = Path(__file__).parent / 'test_output.tprc'
    out.write_bytes(tprc)
    print(f"Built: {out} ({len(tprc)} bytes)")
    
    # Compare with real
    real = TEMPLATE_PATH
    if real.exists():
        rd = real.read_bytes()
        same = sum(1 for i in range(min(len(tprc), len(rd))) if tprc[i] == rd[i])
        print(f"Real: {len(rd)} bytes, same: {same}/{len(rd)} ({same/len(rd)*100:.1f}%)")
        
        # Parse back
        r = parse_tprc(str(out))
        print(f"Parsed: proc={r['procedure_name']}, sample={r['sample_name']}")
        for s in r['segments'][:5]:
            type_names = {0x0E: 'MassFlow', 0x06: 'Ramp', 0x05: 'Iso/End', 0x13: 'Gas'}
            tn = type_names.get(s['type'], f'0x{s["type"]:02X}')
            print(f"  [{tn}] params={s['params']}")
