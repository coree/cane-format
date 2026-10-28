from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

import cane_format as cane

DATA = Path(__file__).parent / "data"

requires_data = pytest.mark.skipif(
    not (DATA / "brat").is_dir(), reason="real test documents (tests/data) are not present"
)


def doc(text: str, *entities: tuple[str | None, list[tuple[int, int]]]) -> cane.Document:
    """A document with entities given as (label, spans)."""
    return cane.Document(
        text=text, entities=tuple(cane.Entity(spans=s, label=label) for label, s in entities)
    )


def at(text: str, needle: str, nth: int = 0) -> tuple[int, int]:
    """The span of the nth occurrence of needle in text."""
    start = -1
    for _ in range(nth + 1):
        start = text.index(needle, start + 1)
    return (start, start + len(needle))


def same_entities(a: tuple[cane.Entity, ...], b: tuple[cane.Entity, ...]) -> bool:
    return Counter(a) == Counter(b)
