"""Public API for the .tri binary format parser.

Everything else in this package (cursor, sections, registry) is an
implementation detail -- import from here, not from submodules.
"""
from .exceptions import TriFormatError, TriMagicMismatchError, TriTruncatedError
from .models import ParsedTriFile, RawSection, TriHeaderFields
from .parser import parse_tri_file, verify_full_coverage

__all__ = [
    "parse_tri_file",
    "verify_full_coverage",
    "ParsedTriFile",
    "TriHeaderFields",
    "RawSection",
    "TriFormatError",
    "TriMagicMismatchError",
    "TriTruncatedError",
]
