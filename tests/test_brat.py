from __future__ import annotations

import warnings
from pathlib import Path

import pytest

import cane_format as cane
from cane_format import Concept, Member, Relation, Span

TEXT = "IL-2 binding stimulates TNF expression.\r\nNo effect on p53."
ANN = """\
T1\tProtein 0 4\tIL-2
T2\tProtein 24 27\tTNF
T3\tPositive_regulation 13 23\tstimulates
T4\tGene_expression 28 38\texpression
T5\tProtein 54 57\tp53
E1\tGene_expression:T4 Theme:T2
E2\tPositive_regulation:T3 Theme:E1 Cause:T1
R1\tCoref Arg1:T2 Arg2:T5
*\tEquiv T1 T5
A1\tNegation E2
A2\tConfidence T5 High
M3\tSpeculation E1
N1\tReference T1 UniProt:P60568\tInterleukin-2
N2\tReference T1 HGNC:6001
#1\tAnnotatorNotes T5\tcheck this
"""


def test_reads_every_line_kind() -> None:
    d = cane.parse_brat(TEXT, ANN, id="doc")
    assert d.text == TEXT and len(d.entities) == 5
    il2 = d.entity("T1")
    assert il2.concepts == (
        Concept(id="UniProt:P60568", name="Interleukin-2"),
        Concept(id="HGNC:6001"),
    )
    assert dict(d.entity("T5").attributes) == {"Confidence": "High"}
    assert d.entity("T5").metadata["brat_notes"] == (("AnnotatorNotes", "check this"),)
    e2 = next(r for r in d.relations if r.id == "E2")
    assert e2 == Relation(
        type="Positive_regulation",
        trigger="T3",
        members=[Member("E1", "Theme"), Member("T1", "Cause")],
    )
    assert dict(e2.attributes) == {"Negation": True}
    equiv = next(r for r in d.relations if r.type == "Equiv")
    assert equiv.members == (Member("T1"), Member("T5")) and equiv.trigger is None


def test_round_trip_keeps_all_content() -> None:
    d = cane.parse_brat(TEXT, ANN, id="doc")
    out = cane.format_brat(d)
    back = cane.parse_brat(TEXT, out, id="doc")
    assert back == d
    assert {e.id: (e.concepts, dict(e.attributes), dict(e.metadata)) for e in back.entities} == {
        e.id: (e.concepts, dict(e.attributes), dict(e.metadata)) for e in d.entities
    }
    assert {r.id: dict(r.attributes) for r in back.relations if (r.id or "").startswith("E")} == {
        "E1": {"Speculation": True},
        "E2": {"Negation": True},
    }
    assert cane.format_brat(back) == out  # canonical form is stable


def test_files_keep_text_exact(tmp_path: Path) -> None:
    d = cane.parse_brat(TEXT, ANN, id="doc")
    cane.write_brat([d], tmp_path)
    assert (tmp_path / "doc.txt").read_bytes() == TEXT.encode("utf-8")
    assert cane.read_brat(tmp_path) == [d]
    assert cane.read_brat(tmp_path / "doc.ann") == [d]


def test_integrity_check() -> None:
    skewed = "T1\tProtein 1 5\tIL-2\n"
    with pytest.raises(cane.IntegrityError, match="stores 'IL-2'"):
        cane.parse_brat(TEXT, skewed)
    with pytest.warns(UserWarning):
        cane.parse_brat(TEXT, skewed, verify="warn")
    cane.parse_brat(TEXT, skewed, verify="off")


def test_discontinuous_text_column_any_separator() -> None:
    text = "Breast and Ovarian Cancers"
    for column in ("Breast Cancers", "Breast [...] Cancers", "Breast ... Cancers"):
        d = cane.parse_brat(text, f"T1\tDisease 0 6;19 26\t{column}\n")
        assert d.entities[0].spans == (Span(0, 6), Span(19, 26))
    with pytest.raises(cane.IntegrityError):
        cane.parse_brat(text, "T1\tDisease 0 6;19 26\tBreast Ovarian\n")


def test_offset_units_and_hint() -> None:
    text = "Fever 🔥 and naïve T cells"
    span = Span(text.index("naïve"), text.index("naïve") + 5)
    d = cane.Document(text=text, entities=(cane.Entity(spans=[span], label="X", id="T1"),))
    for unit in ("utf8", "utf16"):
        ann = cane.format_brat(d, offset_unit=unit)
        assert ann != cane.format_brat(d)
        assert cane.parse_brat(text, ann, offset_unit=unit) == d
        with pytest.raises(cane.IntegrityError, match=f"offset_unit='{unit}'"):
            cane.parse_brat(text, ann)


def test_writer_maps_structure_to_line_kinds_and_renumbers() -> None:
    d = cane.Document(
        text="a b c",
        entities=(
            cane.Entity(spans=[(0, 1)], label="X", id="ent-a"),
            cane.Entity(spans=[(2, 3)], label="X", id="T1"),
            cane.Entity(spans=[(4, 5)], label="Trig", id="T7"),
        ),
        relations=(
            Relation(type="Same", members=[("ent-a",), ("T1",)]),
            Relation(type="Rel", members=[("ent-a", "A"), ("T1", "B")], id="x"),
            Relation(type="Ev", trigger="T7", members=[("T1", "Theme")], id="R5"),
        ),
    )
    lines = cane.format_brat(d).splitlines()
    assert lines == [
        "T1\tX 2 3\tb",
        "T2\tX 0 1\ta",
        "T7\tTrig 4 5\tc",
        "E1\tEv:T7 Theme:T1",
        "R1\tRel A:T2 B:T1",
        "*\tSame T2 T1",
    ]


def test_unrepresentable() -> None:
    bad = [
        cane.Document(text="ab", entities=(cane.Entity(spans=[(0, 1)]),)),
        cane.Document(
            text="ab",
            entities=(
                cane.Entity(spans=[(0, 1)], label="X", id="T1"),
                cane.Entity(spans=[(1, 2)], label="X", id="T2"),
                cane.Entity(spans=[(0, 2)], label="X", id="T3"),
            ),
            relations=(Relation(type="Tri", members=[("T1", "A"), ("T2", "B"), ("T3", "C")]),),
        ),
    ]
    for d in bad:
        with pytest.raises(cane.UnrepresentableError):
            cane.format_brat(d)


def test_lossy_warning() -> None:
    d = cane.Document(
        text="ab",
        entities=(cane.Entity(spans=[(0, 1)], label="X"),),
        segments=(cane.Segment(kind="sentence", span=Span(0, 2)),),
    )
    with pytest.warns(cane.LossyConversionWarning, match="1 segments"):
        cane.format_brat(d)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        cane.format_brat(d, lossy="ignore")


@pytest.mark.parametrize(
    "ann",
    ["X1\tFoo 0 1\n", "T1\tProtein 0\n", "A1\tNeg T9\n", "N1\tAlias T1 X:1\n", "T1 Protein 0 4\n"],
)
def test_bad_ann_lines(ann: str) -> None:
    text_bound = "T1\tProtein 0 4\tIL-2\n"
    with pytest.raises(cane.CaneFormatError):
        cane.parse_brat(TEXT, (text_bound if not ann.startswith("T1") else "") + ann)
