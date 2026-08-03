"""Catch-all fallback: everything not claimed by a more specific
SectionParser is consumed to end-of-file and stored as one opaque
RawSection. This is the graceful-degradation guarantee -- it's what
lets the parser run cleanly TODAY, before the signal-data block
(~99% of every file) or the VERSIONED/SGMT trailer are decoded.

MUST be registered last in registry.DEFAULT_REGISTRY. can_parse()
always returns True, so anything registered after it would never run.

When the signal block's structure is reverse-engineered, add a
dedicated `SignalBlockSectionParser` (mirroring header.py/thumbnail.py)
and register it BEFORE this one -- it will then carve its bytes out of
what currently falls in here, and this parser will keep catching
whatever's left (e.g. the still-undecoded VERSIONED/SGMT trailer).
Nothing else in the architecture changes.
"""
from __future__ import annotations

from ..cursor import BinaryCursor
from ..models import ParsedTriFile, RawSection
from .base import SectionParser


class UnknownSectionParser(SectionParser):
    name = "unknown_payload"

    def can_parse(self, cursor: BinaryCursor) -> bool:
        return True

    def parse(self, cursor: BinaryCursor, result: ParsedTriFile) -> None:
        start = cursor.pos
        raw = cursor.read_bytes(cursor.remaining())
        result.sections.append(RawSection(
            name=self.name, offset=start, length=len(raw), raw_bytes=raw,
        ))
        result.warnings.append(
            f"unrecognized region [{start}:{start + len(raw)}] "
            f"({len(raw):,} bytes) stored as raw payload -- not yet decoded"
        )
