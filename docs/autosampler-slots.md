# Auto-Sampler Slot Assignment — Concept & Status

How the TGA operator app (`tga/src/tga_nomad_app.pyw`) assigns auto-sampler
positions to `.tprc` methods before a measurement run.

## Workflow

1. Operator selects multiple uploads in the app (checkboxes or shift+click).
2. Click **"◫ Assign Slots…"** → a modal dialog shows one row per upload
   (Upload, Sample, TPRC status) with a free-form slot-label input
   (`A1`, `03`, `P1S03` — the pan architecture is device-specific).
3. **Auto-Fill** assigns sequential numbers (`01`, `02`, …); fields stay
   manually editable. Duplicate slots are rejected.
4. OK → the app downloads each `.tprc` from NOMAD and stores it in the
   TRIOS import folder as **`{Sample}_{Slot}.tprc`** (e.g. `10K_min_03.tprc`).
5. The watcher maps later `.tri` result files back to the correct upload
   via the filename stem (`10K_min_03.tri` ↔ `10K_min_03.tprc`).

## Current stage: filename-only (implemented)

The slot is encoded **in the filename only**. The in-file auto-sampler GUID
is intentionally left untouched. This is a safe intermediate stage:

- No risk of corrupting the binary `.tprc` format.
- The operator still enters the actual slot in the TRIOS auto-sampler UI;
  the filename keeps the mapping explicit and unambiguous.
- `.tri` results keep unique names (they are named after the sample name),
  which is required for the watcher's stem-based upload mapping.

## Next stage (documented, NOT implemented): in-file slot GUID

Analysis of a TRIOS-exported `.tprc` (`10K_min (2).tprc`, 2511 bytes):

```
offset ~416:  0x24 (length prefix = 36) + "00000000-0000-0000-0000-000000000000"
              ^^^ the auto-sampler pan/slot reference — NULL when unassigned
context:      01 01 19 00 00 00 28 + "C:\ProgramData\TA Instruments\TRIOS\Data\..."
```

Key facts (verified by hexdump analysis):

- The GUID is a **TLV string**: `0x24` + exactly 36 ASCII chars. It can be
  replaced **in place** (length constant) without shifting the file.
- There are **three** GUID-like strings in the file: offset 416 is the
  NULL slot placeholder (patch target), offsets 966 and 2038 are real
  object/procedure GUIDs — **never touch those**.
- `<SAMPLENAME>` appears three times; only the first occurrence (offset 360)
  is the sample-name field. Changing the sample name changes the file length,
  so patch order matters: **sample name first, then slot GUID** (search-based,
  never fixed offsets).

Proposed patch helper (for the future in-file stage):

```python
import uuid

NULL_SLOT_GUID = '00000000-0000-0000-0000-000000000000'

def slot_guid_for(label: str) -> str:
    """Stable GUID from a slot label — same label => same GUID (uuid5)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f'tga-slot:{label.strip()}'))

def patch_tprc_slot_guid(data: bytes, slot_label: str) -> bytes:
    """Replace the NULL slot GUID in place (search-based, 36 chars)."""
    raw = bytearray(data)
    idx = raw.find(NULL_SLOT_GUID.encode('ascii'))
    if idx < 0:
        raise ValueError('No NULL slot GUID found (slot already assigned?)')
    if idx == 0 or raw[idx - 1] != 0x24:
        raise ValueError(f'Unexpected length prefix {raw[idx - 1]:#04x} before slot GUID')
    guid = slot_guid_for(slot_label).upper()   # TRIOS GUIDs are uppercase
    raw[idx:idx + 36] = guid.encode('ascii')
    return bytes(raw)
```

## ⚠️ Open verification needed before enabling the GUID stage

The `uuid5` convention is a **documented placeholder** — it is NOT verified
to be what TRIOS actually writes for a real pan slot. Before production use:

1. Export a `.tprc` from TRIOS **with a real, assigned auto-sampler slot**
   (create the method, place the sample in the pan, save/export).
2. Diff it against the same method **without** a slot assignment
   ("two files, one variable changed").
3. If the real GUID at the slot position matches the `uuid5` scheme — enable
   the in-file patch. If not, map slot labels to the real pan GUIDs from the
   TRIOS device configuration instead.

Until then: **filename-only is the safe mode and the default.**
