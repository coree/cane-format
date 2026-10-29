"""Hand-crafted extremes and generated documents: cases that rarely occur but must work."""

from __future__ import annotations

import re
import warnings
from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import cane_format as cane
from cane_format import Entity, Member, Relation, Span
from tests.conftest import VARIANTS, same_entities


def round_trip(d: cane.Document, variant: str, **kwargs: object) -> cane.ParseResult:
    out = cane.dumps(d, variant=variant, **kwargs)  # type: ignore[arg-type]
    return cane.loads(out, text=d.text, variant=variant)


def _variants_for(d: cane.Document) -> tuple[str, ...]:
    if any(len(e.spans) > 1 for e in d.entities):
        return ("disco", "full")
    return VARIANTS


EXTREMES: dict[str, cane.Document] = {}


def extreme(name: str, text: str, *entities: Entity) -> None:
    EXTREMES[name] = cane.Document(text=text, entities=entities)


words = [f"w{i}" for i in range(20)]
nest_text = " ".join(words)
starts = [nest_text.index(w) for w in words]
extreme(
    "10-level nesting",
    nest_text,
    *(
        Entity(spans=[(starts[i], starts[19 - i] + len(words[19 - i]))], label=f"L{i}")
        for i in range(10)
    ),
)
extreme(
    "5 labels on one span",
    "p53 binds DNA",
    *(Entity(spans=[(0, 3)], label=f"L{i}") for i in range(5)),
)
extreme("entity is the whole document", "aspirin", Entity(spans=[(0, 7)], label="DRUG"))
extreme(
    "adjacent entities, no gap",
    "IL2R alpha",
    Entity(spans=[(0, 2)], label="A"),
    Entity(spans=[(2, 4)], label="B"),
)
extreme(
    "offsets 0 and end",
    "x middle y",
    Entity(spans=[(0, 1)], label="A"),
    Entity(spans=[(9, 10)], label="B"),
)
ten = " and ".join(f"p{i}" for i in range(10)) + " kinases"
extreme(
    "10-part discontinuous",
    ten,
    Entity(spans=[(ten.index(f"p{i}"), ten.index(f"p{i}") + 2) for i in range(10)], label="K"),
)
extreme(
    "1000 repeated mentions",
    "x " * 1000,
    *(Entity(spans=[(2 * i, 2 * i + 1)], label="X") for i in range(1000)),
)


def spans_of(text: str, *needles: str, label: str) -> list[Entity]:
    """One entity per needle, at successive occurrences."""
    found, pos = [], 0
    for needle in needles:
        pos = text.index(needle, pos)
        found.append(Entity(spans=[(pos, pos + len(needle))], label=label))
        pos += 1
    return found


crlf = "pain in\r\n\tthe chest."
extreme(
    "CRLF and tabs inside an entity",
    crlf,
    *spans_of(crlf, "pain in\r\n\tthe chest", label="SYMPTOM"),
)
emoji = "🔥 fever 𝔸 and 🔥 fever"  # noqa: RUF001
extreme("emoji and astral characters", emoji, *spans_of(emoji, "🔥 fever", "🔥 fever", label="S"))
combining = "café or café au lait"
extreme(
    "combining characters",
    combining,
    Entity(spans=[(combining.index("café", 1), combining.index(" au"))], label="DRINK"),
)
rtl = "המטופל קיבל אספירין היום"
extreme("right-to-left text", rtl, *spans_of(rtl, "אספירין", label="DRUG"))
grammar = "is a and found in NONE Entities: are an"
extreme(
    "grammar words as entities",
    grammar,
    *spans_of(grammar, "is a", "and", "found in", "NONE", "Entities:", "are an", label="W"),
)


@pytest.mark.parametrize("name", EXTREMES)
def test_extreme_round_trips(name: str) -> None:
    d = EXTREMES[name]
    for variant in _variants_for(d):
        if variant in ("base", "disco") and name == "combining characters":
            # Without an anchor the second "café" cannot be told from the first: written, and
            # reported.
            with pytest.warns(cane.LossyConversionWarning, match="parses back elsewhere"):
                result = round_trip(d, variant)
            assert result.ok
            continue
        result = round_trip(d, variant)
        assert result.ok, (variant, result.issues)
        assert same_entities(result.entities, d.entities), variant


def test_empty_and_whitespace_only_texts() -> None:
    for text in ("", "   \n\t "):
        d = cane.Document(text=text)
        for variant in VARIANTS:
            assert cane.dumps(d, variant=variant) == "NONE"
            assert cane.loads("NONE", text=text, variant=variant).ok


def test_relation_extremes_round_trip_through_brat() -> None:
    text = " ".join(f"t{i}" for i in range(12))
    entities = tuple(
        Entity(
            spans=[(text.index(f"t{i}"), text.index(f"t{i}") + len(f"t{i}"))],
            label="P",
            id=f"T{i + 1}",
        )
        for i in range(12)
    )
    chain = tuple(
        Relation(
            type="Reg",
            trigger="T12",
            id=f"E{i}",
            members=[Member(f"E{i + 1}" if i < 10 else "T1", "Theme")],
        )
        for i in range(1, 11)
    )
    wide = Relation(
        type="Complex",
        trigger="T11",
        id="E11",
        members=[Member(f"T{i}", "Theme") for i in range(1, 11)],
    )
    self_rel = Relation(type="Same", members=[Member("T1", "Arg1"), Member("T1", "Arg2")], id="R1")
    d = cane.Document(text=text, entities=entities, relations=(*chain, wide, self_rel), id="d")
    back = cane.parse_brat(text, cane.format_brat(d), id="d")
    assert back == d


# --- generated documents ------------------------------------------------------------------

TOKENS = [
    "IL-2",
    "p53",
    "cells",
    "naïve",
    "🔥",
    "café",
    "אספירין",
    "a",
    "and",
    "is",
    "found",
    "in",
    "Entities:",
    "NONE",
    "x",
    "(",
    ")",
    ",",
    ".",
]
SPACES = [" ", " ", " ", "  ", "\n", "\t", "\r\n"]


@st.composite
def documents(draw: st.DrawFn, discontinuous: bool = True) -> cane.Document:
    tokens = draw(st.lists(st.sampled_from(TOKENS), min_size=1, max_size=40))
    text, bounds = "", []
    for i, token in enumerate(tokens):
        if i:
            text += draw(st.sampled_from(SPACES))
        bounds.append((len(text), len(text) + len(token)))
        text += token
    entities: list[Entity] = []
    for _ in range(draw(st.integers(0, 12))):
        i = draw(st.integers(0, len(bounds) - 1))
        j = draw(st.integers(i, min(i + 4, len(bounds) - 1)))
        spans = [(bounds[i][0], bounds[j][1])]
        if discontinuous and draw(st.booleans()) and j + 2 < len(bounds):
            k = draw(st.integers(j + 2, len(bounds) - 1))
            spans.append(bounds[k])
        entity = Entity(spans=spans, label=draw(st.sampled_from(["A", "B", "protein_N/A"])))
        if entity not in entities:
            entities.append(entity)
    return cane.Document(text=text, entities=tuple(entities))


@settings(max_examples=300, deadline=None)
@given(documents())
def test_generated_brat_round_trip(d: cane.Document) -> None:
    for unit in ("codepoint", "utf8", "utf16"):
        assert cane.parse_brat(d.text, cane.format_brat(d, offset_unit=unit), offset_unit=unit) == d


@settings(max_examples=300, deadline=None)
@given(documents(), st.sampled_from(VARIANTS))
def test_generated_cane_keeps_every_mention(d: cane.Document, variant: str) -> None:
    """Every entity comes back with its label and surface text; nothing is silently lost.

    Surface forms always come back; exact offsets wherever the text leaves no ambiguity. Every
    entity that does not come back at its own spans is named in the formatter's warning.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", cane.LossyConversionWarning)
        out = cane.dumps(d, variant=variant, on_unrepresentable="skip")
    reported = {
        m.group(1)
        for w in caught
        for m in re.finditer(
            r"entity (\S+) \((?:parses back elsewhere|does not parse)", str(w.message)
        )
    }
    expected = [e for e in d.entities if len(e.spans) == 1 or cane.Variant(variant).multi_part]
    result = cane.loads(out, text=d.text, variant=variant)
    assert all(i.kind == cane.IssueKind.DUPLICATE for i in result.issues), result.issues

    def surface(e: Entity) -> tuple[str | None, tuple[str, ...]]:
        return (e.label, tuple(" ".join(p.split()) for p in e.parts(d.text)))

    got = Counter(surface(e) for e in result.entities)
    want = Counter(surface(e) for e in expected)
    assert got <= want
    assert sum(want.values()) - sum(got.values()) == len(result.issues)
    unreported = [e for e in expected if e not in result.entities and e.id not in reported]
    assert not unreported, (out, unreported)


def test_span_strategy_is_valid() -> None:
    assert Span(0, 1) < Span(0, 2)
