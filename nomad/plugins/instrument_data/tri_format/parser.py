"""Entry point: parse_tri_file(). Orchestrates the registry of
SectionParser strategies over a BinaryCursor. This is the only module
that should be imported from outside this package.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from .cursor import BinaryCursor
from .exceptions import TriFormatError
from .models import ParsedTriFile, TriHeaderFields
from .registry import DEFAULT_REGISTRY
from .sections.base import SectionParser


def parse_tri_file(
    filepath: str,
    registry: Optional[List[SectionParser]] = None,
) -> ParsedTriFile:
    """Parse a .tri file section by section.

    Raises TriFormatError only for genuinely fatal problems: file
    unreadable, or the header anchor isn't found at all (i.e. this
    doesn't look like a TRIOS .tri file). Never raises for
    unrecognized-but-present content -- that lands in
    ParsedTriFile.sections as RawSection("unknown_payload", ...) plus
    a note in ParsedTriFile.warnings.
    """
    registry = registry if registry is not None else DEFAULT_REGISTRY

    try:
        data = Path(filepath).read_bytes()
    except OSError as exc:
        raise TriFormatError(f"could not read {filepath}: {exc}") from exc

    if not data:
        raise TriFormatError(f"{filepath} is empty")

    cursor = BinaryCursor(data)
    result = ParsedTriFile(source_path=str(filepath), header=TriHeaderFields())

    header_parser = next((p for p in registry if p.name == "header"), None)
    if header_parser is None or not header_parser.can_parse(cursor):
        raise TriFormatError(
            f"{filepath}: does not look like a TRIOS .tri file "
            f"(header anchor not found near the start of the file)"
        )

    while not cursor.eof():
        before = cursor.pos
        for section_parser in registry:
            if section_parser.can_parse(cursor):
                section_parser.parse(cursor, result)
                break
        if cursor.pos == before:
            # Unreachable in practice -- UnknownSectionParser always
            # matches and always drains to EOF -- but guards against
            # a future misbehaving SectionParser causing an infinite loop.
            raise TriFormatError(
                f"no registered SectionParser advanced the cursor at "
                f"offset {cursor.pos} -- a SectionParser implementation has a bug"
            )

    return result


def verify_full_coverage(result: ParsedTriFile, total_size: int) -> None:
    """Sanity check: every byte of the file must be accounted for
    exactly once -- by the header's byte span, or by exactly one
    RawSection -- with no gaps and no overlaps. Raises AssertionError
    if not. Intended for tests and for validating any new
    SectionParser during development: a boundary bug (off-by-one,
    wrong search window) shows up here immediately instead of silently
    corrupting whatever section reads next.
    """
    spans: List[Tuple[int, int]] = []
    if result.header_byte_range is not None:
        spans.append(result.header_byte_range)
    for s in result.sections:
        spans.append((s.offset, s.offset + s.length))

    spans.sort()
    cursor_end = 0
    for start, end in spans:
        assert start == cursor_end, (
            f"gap or overlap in byte coverage: expected next span to start "
            f"at {cursor_end}, got {start} (span {start}:{end})"
        )
        cursor_end = end

    assert cursor_end == total_size, (
        f"byte coverage ends at {cursor_end}, but file is {total_size} bytes -- "
        f"{total_size - cursor_end} trailing bytes unaccounted for"
    )
