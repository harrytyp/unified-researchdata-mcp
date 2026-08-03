"""Header section: the flat, length-prefixed key/value list at the
start of every .tri file (sample name, operator, procedure, etc.).

Reverse-engineered and validated against 9 real sample files (8 TGA +
1 DMA, different sample name lengths and instrument types) -- see
project notes. Empirically confirmed:
  - `instrumenttype` sits at a fixed byte offset (26) only because
    nothing variable-length precedes it. Every field after the first
    variable-length value shifts file-to-file -- offsets are NOT
    reliable, only marker-relative reads are.
"""
from __future__ import annotations

from ..cursor import BinaryCursor
from ..exceptions import TriFormatError, TriMagicMismatchError
from ..models import ParsedTriFile, RawSection, TriHeaderFields
from ..schema import HEADER_ANCHOR_KEY, HEADER_SCHEMA
from .base import SectionParser

_KEY_TO_ATTR = {spec.raw_key: spec.attr for spec in HEADER_SCHEMA}
_REQUIRED_KEYS = [spec.raw_key for spec in HEADER_SCHEMA if spec.required]
_ANCHOR_BYTES = HEADER_ANCHOR_KEY.encode("ascii")

# Real headers put the anchor within the first ~30 bytes. A generous
# but bounded search window keeps this parser from falsely matching
# the SAME key text if it happens to reappear much later in the file
# (confirmed: procedure_name text, and likely other header words,
# repeat near the file's tail inside VERSIONED/SGMT blocks).
_ANCHOR_SEARCH_WINDOW = 64
_MAX_PAIRS = 60  # safety cap so a malformed file can't loop forever


class HeaderSectionParser(SectionParser):
    name = "header"

    def can_parse(self, cursor: BinaryCursor) -> bool:
        return cursor.find(_ANCHOR_BYTES, within=_ANCHOR_SEARCH_WINDOW) != -1

    def parse(self, cursor: BinaryCursor, result: ParsedTriFile) -> None:
        anchor_idx = cursor.find(_ANCHOR_BYTES, within=_ANCHOR_SEARCH_WINDOW)
        if anchor_idx == -1:
            raise TriFormatError(f"header anchor '{HEADER_ANCHOR_KEY}' not found")

        length_byte_pos = anchor_idx - 1

        # Whatever sits between the current position and the header's
        # first length byte (a short binary preamble -- instrument
        # session id / file-format tag, not yet reverse-engineered) is
        # preserved rather than silently skipped.
        if length_byte_pos > cursor.pos:
            preamble = cursor.read_bytes(length_byte_pos - cursor.pos)
            result.sections.append(RawSection(
                name="file_preamble",
                offset=cursor.pos - len(preamble),
                length=len(preamble),
                raw_bytes=preamble,
            ))

        declared_len = cursor.peek(1)[0]
        if declared_len != len(_ANCHOR_BYTES):
            raise TriMagicMismatchError(
                f"length byte before '{HEADER_ANCHOR_KEY}' is {declared_len}, "
                f"expected {len(_ANCHOR_BYTES)} -- this may be a different "
                f"TRIOS format version than the one this parser was built for"
            )

        header_start = cursor.pos
        header = TriHeaderFields()
        for _ in range(_MAX_PAIRS):
            pair_start = cursor.pos
            try:
                key = cursor.read_pstring()
            except TriFormatError:
                cursor.seek(pair_start)
                break
            if not key or not key.isprintable() or len(key) > 64:
                # Doesn't look like a real field name -- we've walked
                # off the end of the flat header into whatever follows
                # (thumbnail / signal data). Rewind past this failed
                # read so the next section parser sees clean bytes.
                cursor.seek(pair_start)
                break
            try:
                value = cursor.read_pstring()
            except TriFormatError:
                cursor.seek(pair_start)
                break

            attr = _KEY_TO_ATTR.get(key)
            if attr is not None:
                setattr(header, attr, value or None)
            else:
                # Forward-compat: unrecognized key -> parked, not lost.
                header.extra_fields[key] = value

        for required_key in _REQUIRED_KEYS:
            if getattr(header, _KEY_TO_ATTR[required_key]) is None:
                result.warnings.append(
                    f"required header field '{required_key}' was not found"
                )

        result.header = header
        result.header_byte_range = (header_start, cursor.pos)
