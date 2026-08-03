"""Strategy interface for one recognized region of a .tri file.

To add support for a new region (once it's reverse-engineered -- e.g.
the signal-data block or the VERSIONED/SGMT trailer), write a class
implementing this interface and register it in registry.py. Nothing
in parser.py, cursor.py, or the other section parsers needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..cursor import BinaryCursor
from ..models import ParsedTriFile


class SectionParser(ABC):
    name: str

    @abstractmethod
    def can_parse(self, cursor: BinaryCursor) -> bool:
        """Cheap, non-consuming check: does this section start at (or
        near) cursor.pos? Must not mutate the cursor."""

    @abstractmethod
    def parse(self, cursor: BinaryCursor, result: ParsedTriFile) -> None:
        """Consume bytes from cursor (advancing cursor.pos) and record
        findings onto `result`. Must always advance the cursor -- a
        parser that matches but consumes zero bytes would stall the
        registry loop."""
