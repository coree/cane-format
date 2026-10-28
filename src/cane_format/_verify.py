"""Checking stored surface text against offsets, shared by the readers."""

from __future__ import annotations

import re
from collections.abc import Sequence

from cane_format._offsets import UNITS, OffsetMap, OffsetUnit
from cane_format.model import Span

_WHITESPACE = re.compile(r"\s+")


def covers(text: str, spans: Sequence[Span], stored: str) -> bool:
    """Whether the stored text shows each fragment, in order (any separator between them)."""
    stored = _WHITESPACE.sub(" ", stored)
    frags = [_WHITESPACE.sub(" ", text[s.start : s.end]) for s in spans]
    if len(frags) == 1:
        return stored == frags[0]
    if not (stored.startswith(frags[0]) and stored.endswith(frags[-1])):
        return False
    pos = len(frags[0])
    for frag in frags[1:-1]:
        pos = stored.find(frag, pos)
        if pos < 0:
            return False
        pos += len(frag)
    return pos <= len(stored) - len(frags[-1])


def unit_hint(text: str, raw: Sequence[tuple[int, int]], stored: str, used: OffsetUnit) -> str:
    """A hint naming another offset unit under which ``raw`` offsets match ``stored``."""
    for unit in UNITS:
        if unit == used:
            continue
        other = OffsetMap(text, unit)
        try:
            spans = [Span(other.to_codepoint(s), other.to_codepoint(e)) for s, e in raw]
        except (KeyError, ValueError):
            continue
        if covers(text, spans, stored):
            return f"; the offsets fit offset_unit={unit!r}"
    return ""
