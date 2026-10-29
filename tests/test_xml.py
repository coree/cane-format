from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings

import cane_format as cane
from cane_format import Entity
from tests.conftest import at, doc
from tests.test_extremes import EXTREMES, documents
from tests.test_formatter import AMOX, COMPLEX_DOC


def back(d: cane.Document, **options: Any) -> cane.Document:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", cane.LossyConversionWarning)
        (result,) = cane.parse_xml(cane.format_xml(d, **options), **options)
    return result


def test_label_as_element_name() -> None:
    assert cane.format_xml(AMOX) == (
        "After starting <DRUG>amoxicillin</DRUG>, the patient developed a <ADR>rash</ADR>."
    )
    assert back(AMOX) == AMOX


def test_crossing_and_discontinuous_share_refs() -> None:
    assert cane.format_xml(COMPLEX_DOC) == (
        '<DISEASE>metastatic <CELL ref="T2">breast cancer</CELL></DISEASE>'
        '<CELL ref="T2"> cells</CELL> caused <ADR ref="T3">headache</ADR> and '
        '<ADR ref="T3">nausea</ADR>'
    )
    result = back(COMPLEX_DOC)
    assert set(result.entities) == set(COMPLEX_DOC.entities)
    assert result.entity("T3").spans == COMPLEX_DOC.entity("T3").spans


def test_nesting_and_same_span_labels() -> None:
    text = "p53 binds"
    d = doc(text, ("GENE", [(0, 3)]), ("PROTEIN", [(0, 3)]), ("EVENT", [(0, 9)]))
    assert cane.format_xml(d) == "<EVENT><GENE><PROTEIN>p53</PROTEIN></GENE> binds</EVENT>"
    assert set(back(d).entities) == set(d.entities)


def test_escaping_keeps_offsets() -> None:
    d = doc("a < b & c > d", ("X", [(0, 5)]), ("Y", [(8, 13)]))
    assert cane.format_xml(d) == "<X>a &lt; b</X> &amp; <Y>c &gt; d</Y>"
    assert back(d) == d


def test_labels_that_are_not_element_names() -> None:
    d = doc("IL-2 binds", ("protein_N/A", [(0, 4)]), (None, [(5, 10)]))
    with pytest.raises(cane.UnrepresentableError, match="tag="):
        cane.format_xml(d)
    generic = cane.format_xml(d, tag="entity")
    assert generic == '<entity type="protein_N/A">IL-2</entity> <entity>binds</entity>'
    assert back(d, tag="entity") == d


def test_paper_style_combined_refs() -> None:
    (d,) = cane.parse_xml(
        'The <D ref="e1">heart</D> and <D ref="e2">chest</D> <D ref="e1 e2">pain</D>'
    )
    assert sorted(e.parts(d.text) for e in d.entities) == [("chest", "pain"), ("heart", "pain")]
    assert sorted(str(e.id) for e in d.entities) == ["e1", "e2"]


def test_elements_without_ref_never_merge() -> None:
    (d,) = cane.parse_xml("<D>heart</D> and <D>chest</D>")
    assert [e.spans for e in d.entities] == [((0, 5),), ((10, 15),)]


def test_structure_segments_and_excluded_text() -> None:
    content = (
        "<set><article><info>PMID:1</info><title><s>A <cons sem='G#x'>title</cons>.</s></title>"
        "<abstract><s>Body <cons sem='G#y'><cons>nested</cons> term</cons>.</s></abstract>"
        "</article><article><title><s>Second.</s></title></article></set>"
    )
    first, second = cane.parse_xml(
        content,
        tag="cons",
        type_attr="sem",
        document_tag="article",
        segment_tags=("title", "abstract", "s"),
        exclude_tags=("info",),
    )
    assert first.text == "A title.Body nested term." and first.metadata["info"] == "PMID:1"
    assert [(e.label, e.parts(first.text)) for e in first.entities] == [
        ("G#x", ("title",)),
        ("G#y", ("nested term",)),
        (None, ("nested",)),
    ]
    assert [s.kind for s in first.segments] == ["s", "title", "s", "abstract"]
    assert second.text == "Second." and second.id == "2"


def test_collection_files(tmp_path: Path) -> None:
    docs = [
        cane.Document(text=AMOX.text, entities=AMOX.entities, id="a"),
        cane.Document(text="nothing here", id="b"),
    ]
    cane.write_xml(docs, tmp_path / "docs.xml")
    assert cane.read_xml(tmp_path / "docs.xml") == docs


def test_invalid_xml() -> None:
    for bad in ("<A>open", "a <A></A> empty", "x & y"):
        with pytest.raises(cane.CaneFormatError):
            cane.parse_xml(bad)


def test_lossy_warning() -> None:
    d = cane.Document(
        text="ab", entities=(Entity(spans=[(0, 1)], label="X", attributes={"Negation": True}),)
    )
    with pytest.warns(cane.LossyConversionWarning, match="attributes"):
        cane.format_xml(d)


@pytest.mark.parametrize("name", EXTREMES)
def test_extremes_round_trip(name: str) -> None:
    assert set(back(EXTREMES[name]).entities) == set(EXTREMES[name].entities)
    assert back(EXTREMES[name]).text == EXTREMES[name].text


@settings(max_examples=200, deadline=None)
@given(documents())
def test_generated_round_trip(d: cane.Document) -> None:
    result = back(d, tag="e")
    assert result.text == d.text and set(result.entities) == set(d.entities)


def test_entity_at_text_boundaries() -> None:
    text = "aspirin"
    d = doc(text, ("DRUG", [at(text, "aspirin")]))
    assert cane.format_xml(d) == "<DRUG>aspirin</DRUG>" and back(d) == d
