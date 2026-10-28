from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings

import cane_format as cane
from cane_format import Concept, Entity, Member, Relation, Span
from cane_format._offsets import OffsetUnit
from tests.test_extremes import EXTREMES, documents
from tests.test_json import same


def collection(*docs: dict[str, Any]) -> str:
    return json.dumps({"source": "s", "date": "d", "key": "k", "infons": {}, "documents": docs})


TITLE = "Naïve T cells"
ABSTRACT = "IL-2 binds naïve cells."
# UTF-8 byte offsets: the title is 14 bytes (ï is 2), the abstract starts at byte 15.
DOC = {
    "id": "1",
    "infons": {"journal": "J"},
    "passages": [
        {
            "infons": {"type": "title"},
            "offset": 0,
            "text": TITLE,
            "annotations": [
                {
                    "id": "a1",
                    "infons": {"type": "Cell", "identifier": "CL:1"},
                    "text": "Naïve T cells",
                    "locations": [{"offset": 0, "length": 14}],
                }
            ],
            "relations": [],
        },
        {
            "infons": {"type": "abstract"},
            "offset": 15,
            "text": ABSTRACT,
            "annotations": [
                {
                    "id": "a2",
                    "infons": {"type": "Protein"},
                    "text": "IL-2",
                    "locations": [{"offset": 15, "length": 4}],
                },
                {
                    "id": "a3",
                    "infons": {"type": "Binding"},
                    "text": "binds",
                    "locations": [{"offset": 20, "length": 5}],
                },
                {
                    "id": "a4",
                    "infons": {"type": "Cell"},
                    "text": "naïve cells",
                    "locations": [{"offset": 26, "length": 12}],
                },
            ],
            "relations": [
                {
                    "id": "r1",
                    "infons": {"type": "Bind"},
                    "nodes": [
                        {"refid": "a3", "role": "trigger"},
                        {"refid": "a2", "role": "Theme"},
                        {"refid": "a4", "role": "Theme2"},
                    ],
                }
            ],
        },
    ],
    "annotations": [],
    "relations": [
        {
            "id": "r2",
            "infons": {"type": "Equiv"},
            "nodes": [{"refid": "a1", "role": ""}, {"refid": "a4", "role": ""}],
        }
    ],
}


def test_reads_byte_offsets_passages_and_relations() -> None:
    (d,) = cane.parse_bioc_json(collection(DOC))
    assert d.text == TITLE + " " + ABSTRACT
    assert [(e.label, d.text[e.start : e.end]) for e in d.entities] == [
        ("Cell", "Naïve T cells"),
        ("Protein", "IL-2"),
        ("Binding", "binds"),
        ("Cell", "naïve cells"),
    ]
    assert d.entity("a1").concepts == (Concept(id="CL:1"),)
    assert [s.span for s in d.segments] == [Span(0, 13), Span(14, 37)]
    bind, equiv = d.relations
    assert bind == Relation(
        type="Bind", trigger="a3", members=[Member("a2", "Theme"), Member("a4", "Theme2")]
    )
    assert equiv == Relation(type="Equiv", members=[Member("a1"), Member("a4")])
    assert equiv.metadata["bioc_level"] == "document"
    assert d.metadata["bioc_collection"]["source"] == "s"


def test_round_trip_is_identical() -> None:
    content = collection(DOC)
    assert json.loads(cane.format_bioc_json(cane.parse_bioc_json(content))) == json.loads(content)


def test_wrong_unit_is_caught_with_a_hint() -> None:
    with pytest.raises(cane.IntegrityError, match="offset_unit='utf8'"):
        cane.parse_bioc_json(collection(DOC), offset_unit="codepoint")
    cp = json.loads(json.dumps(DOC))
    cp["passages"][0]["annotations"][0]["locations"][0]["length"] = 13
    cp["passages"][1]["offset"] = 14
    for ann, start in zip(cp["passages"][1]["annotations"], (14, 19, 25), strict=True):
        ann["locations"][0]["offset"] = start
    cp["passages"][1]["annotations"][2]["locations"][0]["length"] = 11
    assert cane.parse_bioc_json(collection(cp), offset_unit="codepoint")[0].text == DOC_TEXT
    with pytest.raises(cane.IntegrityError, match="offset_unit='codepoint'"):
        cane.parse_bioc_json(collection(cp))


DOC_TEXT = TITLE + " " + ABSTRACT


def test_sentence_level_text_and_annotations() -> None:
    doc = {
        "id": "s",
        "infons": {},
        "passages": [
            {
                "infons": {},
                "offset": 0,
                "text": "",
                "sentences": [
                    {
                        "infons": {},
                        "offset": 0,
                        "text": "First one.\n",
                        "annotations": [
                            {
                                "id": "1",
                                "infons": {"type": "X"},
                                "text": "First",
                                "locations": [{"offset": 0, "length": 5}],
                            }
                        ],
                        "relations": [],
                    },
                    {
                        "infons": {},
                        "offset": 11,
                        "text": "Second.",
                        "annotations": [],
                        "relations": [],
                    },
                ],
                "annotations": [],
                "relations": [],
            }
        ],
        "annotations": [],
        "relations": [],
    }
    (d,) = cane.parse_bioc_json(collection(doc))
    assert d.text == "First one.\nSecond."
    assert [s.kind for s in d.segments] == ["passage", "sentence", "sentence"]
    assert d.entities[0].metadata["bioc_level"] == "sentence"
    out = json.loads(cane.format_bioc_json([d]))["documents"][0]
    assert out["passages"][0]["text"] == ""
    assert out["passages"][0]["sentences"][0]["annotations"][0]["id"] == "1"


def test_empty_passages_and_nodeless_relations_are_kept() -> None:
    doc = {
        "id": "e",
        "infons": {},
        "passages": [
            {
                "infons": {"type": "title"},
                "offset": 0,
                "text": "Title",
                "annotations": [],
                "relations": [],
            },
            {
                "infons": {"type": "abstract"},
                "offset": 6,
                "text": "",
                "annotations": [],
                "relations": [],
            },
        ],
        "annotations": [],
        "relations": [{"id": "R1", "infons": {"type": "Assoc"}, "nodes": []}],
    }
    content = collection(doc)
    (d,) = cane.parse_bioc_json(content)
    assert d.relations == () and len(d.metadata["bioc_relations"]) == 1
    assert json.loads(cane.format_bioc_json([d])) == json.loads(content)


def test_unresolvable_nodes_warn_and_stay_raw() -> None:
    doc = json.loads(json.dumps(DOC))
    doc["relations"][0]["nodes"][0]["refid"] = "nowhere"
    with pytest.warns(UserWarning, match="1 relation"):
        (d,) = cane.parse_bioc_json(collection(doc))
    assert len(d.relations) == 1 and len(d.metadata["bioc_relations"]) == 1


def test_pubtator3_relations_are_never_mention_relations() -> None:
    content = json.dumps({"PubTator3": [DOC]})
    (d,) = cane.parse_bioc_json(content)
    assert d.relations == () and len(d.metadata["bioc_relations"]) == 2


def test_list_of_collections_and_files(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps([json.loads(collection(DOC))]), encoding="utf-8")
    assert len(cane.read_bioc_json(path)) == 1
    cane.write_bioc_json(cane.read_bioc_json(path), tmp_path / "out.json")
    assert cane.read_bioc_json(tmp_path / "out.json")[0] == cane.read_bioc_json(path)[0]


def test_from_other_formats() -> None:
    d = cane.Document(
        text="IL-2 binds",
        id="x",
        entities=(
            Entity(
                spans=[(0, 4)],
                label="P",
                id="T1",
                attributes={"Negation": True},
                concepts=(Concept(id="A"), Concept(id="B", name="b")),
            ),
        ),
    )
    with pytest.warns(cane.LossyConversionWarning) as record:
        out = json.loads(cane.format_bioc_json([d]))
    message = str(record[0].message)
    assert "joined" in message and "attributes" in message and "names" in message
    ann = out["documents"][0]["passages"][0]["annotations"][0]
    assert ann["infons"] == {"type": "P", "identifier": "A;B", "Negation": "true"}
    assert ann["locations"] == [{"offset": 0, "length": 4}]


@pytest.mark.parametrize("name", EXTREMES)
def test_extremes_round_trip(name: str) -> None:
    d = EXTREMES[name]
    units: tuple[OffsetUnit, ...] = ("utf8", "utf16", "codepoint")
    for unit in units:
        out = cane.format_bioc_json([d], offset_unit=unit)
        (back,) = cane.parse_bioc_json(out, offset_unit=unit)
        assert back.text == d.text and back.entities == d.entities


@settings(max_examples=150, deadline=None)
@given(documents())
def test_generated_round_trip(d: cane.Document) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", cane.LossyConversionWarning)
        (back,) = cane.parse_bioc_json(cane.format_bioc_json([d]))
    assert back.text == d.text and back.entities == d.entities


def test_brat_content_through_bioc() -> None:
    from tests.test_brat import ANN, TEXT

    d = cane.parse_brat(TEXT, ANN, id="doc")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", cane.LossyConversionWarning)
        (back,) = cane.parse_bioc_json(cane.format_bioc_json([d]))
    assert back.entities == d.entities
    assert {r.id: r for r in back.relations} == {r.id: r for r in d.relations}
    assert not same(back, d)  # attributes and notes become string infons: lossy, and warned
