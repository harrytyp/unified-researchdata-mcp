"""Exception hierarchy for .tri binary parsing.

Kept separate from cursor/section logic so callers (entrypoint.py,
instrument_ingest.py) can catch precisely what they care about without
importing parsing internals.
"""


class TriFormatError(Exception):
    """Base class for all .tri parsing errors."""


class TriMagicMismatchError(TriFormatError):
    """An anchor/magic marker was found, but the structure around it
    (e.g. the length byte that should precede it) doesn't match what
    the schema expects. Usually means a different TRIOS format version
    than the one this schema was reverse-engineered from -- NOT
    necessarily a corrupt file."""


class TriTruncatedError(TriFormatError):
    """A read would go past end-of-file, or a variable-length value
    (e.g. a 7-bit length prefix) never terminated. Usually means a
    corrupt or partially-written file."""
