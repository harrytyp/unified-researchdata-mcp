"""Domain data models for a parsed .tri file.

STRICT DECOUPLING: nothing in this module reads a single byte. These
are plain dataclasses that section parsers (in `sections/`) populate.
Downstream code (NOMAD schema mapping, elabFTW push-back) should only
ever depend on THIS module, never on cursor.py or the section parsers
directly -- that's what keeps the binary-reading internals swappable
without touching the rest of the codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class TriHeaderFields:
    """Schema-mapped header fields. `None` = key not present in this
    particular file (e.g. DMA files have no pan_type/pan_number --
    that's a normal, expected state, not an error).

    Confirmed present as plain text (validated against 9 real sample
    files, 8 TGA + 1 DMA): everything below except `extra_fields`.
    Deliberately NOT present here: sample_mass, gas_atmosphere -- both
    searched for and NOT found as plain text in the header on real
    samples. Do not add them here without new empirical evidence.
    """
    instrument_type: Optional[str] = None
    instrument_serial_number: Optional[str] = None
    instrument_name: Optional[str] = None
    company_name: Optional[str] = None
    run_date: Optional[str] = None
    operator: Optional[str] = None
    project: Optional[str] = None
    sample_name: Optional[str] = None
    comments: Optional[str] = None
    pan_type: Optional[str] = None
    pan_number: Optional[str] = None
    procedure_name: Optional[str] = None
    procedure_segments: Optional[str] = None
    procedure_signals: Optional[str] = None
    procedure_guid: Optional[str] = None

    # Forward-compat safety valve: any header key encountered that is
    # NOT in schema.HEADER_SCHEMA lands here instead of being dropped
    # or crashing the parse. A future TRIOS version adding a new key
    # (e.g. a real "samplemass" field) will show up here automatically
    # even before anyone updates schema.py.
    extra_fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class RawSection:
    """A region of the file that either isn't decoded yet (the ~99%
    signal-data block, the VERSIONED/SGMT trailer) or deliberately
    isn't decoded (the embedded PNG thumbnail -- not needed for data
    extraction). Nothing in the file is ever silently dropped: every
    byte not claimed by a known field ends up in exactly one of these.
    """
    name: str
    offset: int
    length: int
    raw_bytes: bytes


@dataclass
class ParsedTriFile:
    source_path: str
    header: TriHeaderFields
    sections: List[RawSection] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # (start, end) byte range the header field walk actually consumed.
    # Set by HeaderSectionParser. Used by verify_full_coverage() to
    # confirm every byte in the file is accounted for by either the
    # header span or exactly one RawSection -- with no gaps or overlaps.
    header_byte_range: Optional[Tuple[int, int]] = None

    def section(self, name: str) -> Optional[RawSection]:
        return next((s for s in self.sections if s.name == name), None)
