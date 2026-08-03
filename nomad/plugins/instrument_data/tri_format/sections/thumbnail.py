"""PNG thumbnail section: TRIOS embeds an auto-generated preview chart
image right after the header. We don't need the image for data
extraction, so it's isolated as an opaque RawSection rather than
decoded -- but it IS accounted for, so downstream code can tell "this
is a known, deliberately-skipped image" apart from "this is unparsed
territory we haven't reverse-engineered yet".
"""
from __future__ import annotations

from ..cursor import BinaryCursor
from ..exceptions import TriTruncatedError
from ..models import ParsedTriFile, RawSection
from .base import SectionParser

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PNG_IEND = b"IEND"
_SEARCH_WINDOW = 4096  # generous gap allowance between header end and PNG start


class PngThumbnailSectionParser(SectionParser):
    name = "png_thumbnail"

    def can_parse(self, cursor: BinaryCursor) -> bool:
        return cursor.find(_PNG_MAGIC, within=_SEARCH_WINDOW) != -1

    def parse(self, cursor: BinaryCursor, result: ParsedTriFile) -> None:
        png_start = cursor.find(_PNG_MAGIC, within=_SEARCH_WINDOW)

        if png_start > cursor.pos:
            gap = cursor.read_bytes(png_start - cursor.pos)
            result.sections.append(RawSection(
                name="post_header_gap",
                offset=cursor.pos - len(gap),
                length=len(gap),
                raw_bytes=gap,
            ))

        iend_idx = cursor.find(_PNG_IEND)
        if iend_idx == -1:
            raise TriTruncatedError("PNG thumbnail has no IEND chunk -- file truncated")
        end = iend_idx + len(_PNG_IEND) + 4  # + 4-byte CRC32 trailing the IEND tag

        raw = cursor.read_bytes(end - cursor.pos)
        result.sections.append(RawSection(
            name=self.name, offset=png_start, length=len(raw), raw_bytes=raw,
        ))
