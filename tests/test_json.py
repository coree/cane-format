from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given, settings

import cane_format as cane
from cane_format import Concept, Entity, Member, Relation, Segment, Span
from tests.test_brat import ANN, TEXT
from tests.test_extremes import EXTREMES, documents


def same(a: cane.Document, b: cane.Document) -> bool:
    def content(d: cane.Document) -> list[object]:
        return [
            (e.id, e.label, e.spans, e.concepts, dict(e.attributes), dict(e.metadata))
            for e in d.entities
        ] + [
            (r.id, r.type, r.trigger, r.members, dict(r.attributes), dict(r.metadata))
            for r in d.relations
        ]

    return (
        a == b
        and a.id == b.id
        and dict(a.metadata) == dict(b.metadata)
        and content(a) == content(b)
    )


def test_schema_example() -> None:
    d = cane.Document(
        text="IL-2 binds p53",
        id="doc1",
        entities=(
            Entity(
                spans=[(0, 4)],
                label="Protein",
                id="T1",
                concepts=(Concept(id="UniProt:P60568", name="Interleukin-2"),),
            ),
            Entity(spans=[(5, 10)], label="Binding", id="T2", attributes={"Negation": True}),
            Entity(spans=[(11, 14)], id="T3"),
        ),
        relations=(
            Relation(
                type="Binding",
                trigger="T2",
                id="E1",
                members=[Member("T1", "Theme"), Member("T3", "Theme2")],
            ),
            Relation(type="Equiv", members=[Member("T1"), Member("T3")], id="R1"),
        ),
        segments=(Segment(kind="sentence", span=Span(0, 14)),),
        metadata={"source": "test"},
    )
    assert json.loads(cane.format_json(d)) == {
        "format_version": 1,
        "id": "doc1",
        "text": "IL-2 binds p53",
        "entities": [
            {
                "id": "T1",
                "label": "Protein",
                "spans": [[0, 4]],
                "concepts": [{"id": "UniProt:P60568", "name": "Interleukin-2"}],
            },
            {"id": "T2", "label": "Binding", "spans": [[5, 10]], "attributes": {"Negation": True}},
            {"id": "T3", "spans": [[11, 14]]},
        ],
        "relations": [
            {
                "id": "E1",
                "type": "Binding",
                "trigger": "T2",
                "members": [{"refid": "T1", "role": "Theme"}, {"refid": "T3", "role": "Theme2"}],
            },
            {"id": "R1", "type": "Equiv", "members": [{"refid": "T1"}, {"refid": "T3"}]},
        ],
        "segments": [{"kind": "sentence", "span": [0, 14]}],
        "metadata": {"source": "test"},
    }
    assert same(cane.parse_json(cane.format_json(d)), d)


def test_brat_content_survives_json() -> None:
    d = cane.parse_brat(TEXT, ANN, id="doc")
    back = cane.parse_json(cane.format_json(d, indent=2))
    assert same(back, d)
    assert cane.format_brat(back) == cane.format_brat(d)


@pytest.mark.parametrize("name", EXTREMES)
def test_extremes_round_trip(name: str) -> None:
    assert same(cane.parse_json(cane.format_json(EXTREMES[name])), EXTREMES[name])


@settings(max_examples=200, deadline=None)
@given(documents())
def test_generated_round_trip(d: cane.Document) -> None:
    assert same(cane.parse_json(cane.format_json(d)), d)


def test_file_layouts(tmp_path: Path) -> None:
    docs = [cane.parse_brat(TEXT, ANN, id="a"), cane.Document(text="", id="empty")]
    cane.write_json(docs, tmp_path / "docs.jsonl")
    assert len((tmp_path / "docs.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert all(
        same(x, y) for x, y in zip(cane.read_json(tmp_path / "docs.jsonl"), docs, strict=True)
    )
    (tmp_path / "one.json").write_text(cane.format_json(docs[0], indent=2), encoding="utf-8")
    assert same(cane.read_json(tmp_path / "one.json")[0], docs[0])
    array = "[" + ",".join(cane.format_json(d) for d in docs) + "]"
    (tmp_path / "array.json").write_text(array, encoding="utf-8")
    assert Counter(d.id for d in cane.iter_json(tmp_path / "array.json")) == {"a": 1, "empty": 1}


@pytest.mark.parametrize(
    "content",
    [
        '{"text": "ab"}',
        '{"format_version": 2, "text": "ab"}',
        '{"format_version": 1}',
        '{"format_version": 1, "text": "ab", "entities": [{"spans": [[0, 9]]}]}',
        '{"format_version": 1, "text": "ab", "entities": [{"spans": [[1, 1]]}]}',
        "[1, 2]",
        "{not json",
    ],
)
def test_invalid_input(content: str) -> None:
    with pytest.raises(cane.CaneFormatError):
        cane.parse_json(content)


def test_metadata_must_be_json() -> None:
    d = cane.Document(text="ab", metadata={"x": object()})
    with pytest.raises(cane.UnrepresentableError):
        cane.format_json(d)
