"""Pure binary-reading primitives for the TRIOS `.tri` format.

STRICT DECOUPLING: this module knows nothing about "sample name",
"header", "TGA" or any domain concept. It only knows how to move a
position through a byte string and decode the two low-level encodings
TRIOS actually uses:

  1. A .NET-style "7-bit encoded int" length prefix (the same scheme
     .NET's BinaryWriter.Write(string) / BinaryReader.ReadString() use):
     each byte contributes 7 bits, low-to-high; the top bit (0x80)
     means "another byte follows". Verified empirically: a 298-char
     value decoded correctly as bytes [0xAA, 0x02] -> 42 + (2 << 7).
  2. A "Pascal string" = one such length prefix followed by that many
     raw bytes, decoded as cp1252 (TRIOS embeds Windows-native
     characters like '°' as single bytes -- not valid UTF-8).

Every section parser (header, thumbnail, future signal/trailer
parsers) is built ONLY on top of this class. If TRIOS changes its
string encoding in a future version, this is the one place to change.
"""
from __future__ import annotations

from dataclasses import dataclass

from .exceptions import TriFormatError, TriTruncatedError


@dataclass
class BinaryCursor:
    data: bytes
    pos: int = 0

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def peek(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise TriTruncatedError(
                f"peek({n}) at offset {self.pos} exceeds file length {len(self.data)}"
            )
        return self.data[self.pos:self.pos + n]

    def read_bytes(self, n: int) -> bytes:
        chunk = self.peek(n)
        self.pos += n
        return chunk

    def find(self, marker: bytes, within: int | None = None) -> int:
        """Search for `marker` starting at the current position.
        `within` caps how far ahead to look (search window), so a
        section parser doesn't accidentally match a marker that
        legitimately repeats much later in the file (this happens --
        e.g. the procedure name text repeats near the file's tail
        inside VERSIONED/SGMT blocks)."""
        end = len(self.data) if within is None else min(len(self.data), self.pos + within)
        return self.data.find(marker, self.pos, end)

    def seek(self, pos: int) -> None:
        if pos < 0 or pos > len(self.data):
            raise TriTruncatedError(f"seek to {pos} out of bounds (len={len(self.data)})")
        self.pos = pos

    def read_7bit_length(self) -> int:
        """Decode a .NET-style 7-bit-encoded length prefix."""
        result = 0
        shift = 0
        while True:
            if self.eof():
                raise TriTruncatedError(f"7-bit length prefix truncated at offset {self.pos}")
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
            if shift > 35:
                raise TriFormatError(f"7-bit length prefix implausibly long near offset {self.pos}")
        return result

    def read_pstring(self, encoding: str = "cp1252") -> str:
        """Read one length-prefixed ('Pascal') string at the current position."""
        length = self.read_7bit_length()
        raw = self.read_bytes(length)
        return raw.decode(encoding, errors="replace")
