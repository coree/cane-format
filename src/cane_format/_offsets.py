"""Conversion between code-point offsets and the offset units formats use on disk."""

from __future__ import annotations

from typing import Literal

OffsetUnit = Literal["codepoint", "utf8", "utf16"]
UNITS: tuple[OffsetUnit, ...] = ("codepoint", "utf8", "utf16")


def _width(ch: str, unit: OffsetUnit) -> int:
    if unit == "utf8":
        return len(ch.encode("utf-8"))
    return 2 if ord(ch) > 0xFFFF else 1  # utf16


class OffsetMap:
    """Maps offsets of one unit to code points and back for one text."""

    def __init__(self, text: str, unit: OffsetUnit) -> None:
        self.unit = unit
        self._to_cp: dict[int, int] = {}
        self._from_cp: list[int] = []
        if unit == "codepoint":
            return
        pos = 0
        for i, ch in enumerate(text):
            self._to_cp[pos] = i
            self._from_cp.append(pos)
            pos += _width(ch, unit)
        self._to_cp[pos] = len(text)
        self._from_cp.append(pos)

    def to_codepoint(self, offset: int) -> int:
        """Raises KeyError if ``offset`` falls inside a character."""
        if self.unit == "codepoint":
            return offset
        return self._to_cp[offset]

    def from_codepoint(self, offset: int) -> int:
        if self.unit == "codepoint":
            return offset
        return self._from_cp[offset]
