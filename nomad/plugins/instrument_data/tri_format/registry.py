"""Ordered list of SectionParser strategies.

Tried top-to-bottom at the current cursor position by parser.py's
main loop. To support a new section type: write a SectionParser
subclass in sections/ and add an instance here -- insert it BEFORE
UnknownSectionParser, which must always stay last (it's the
always-matches catch-all; anything registered after it is dead code).
"""
from __future__ import annotations

from typing import List

from .sections.base import SectionParser
from .sections.header import HeaderSectionParser
from .sections.thumbnail import PngThumbnailSectionParser
from .sections.unknown import UnknownSectionParser

DEFAULT_REGISTRY: List[SectionParser] = [
    HeaderSectionParser(),
    PngThumbnailSectionParser(),
    UnknownSectionParser(),   # must stay last
]
