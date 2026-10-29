from __future__ import annotations

import warnings

import pytest

import cane_format as cane
from tests.conftest import at, doc

TEXT = "After starting amoxicillin, the patient developed a rash."
AMOX = doc(TEXT, ("DRUG", [at(TEXT, "amoxicillin")]), ("ADR", [at(TEXT, "rash")]))

COMPLEX = "metastatic breast cancer cells caused headache and nausea"
COMPLEX_DOC = doc(
    COMPLEX,
    ("DISEASE", [at(COMPLEX, "metastatic breast cancer")]),
    ("CELL", [at(COMPLEX, "breast cancer cells")]),
    ("ADR", [at(COMPLEX, "headache"), at(COMPLEX, "nausea")]),
)


def test_paper_examples() -> None:
    assert cane.dumps(AMOX, variant="base") == (
        "Entities:\n`amoxicillin` is a DRUG\n`rash` is a ADR"
    )
    assert cane.dumps(AMOX, variant="context") == (
        "Entities:\n"
        "`amoxicillin` is a DRUG found in `starting amoxicillin,`\n"
        "`rash` is a ADR found in `a rash.`"
    )
    assert cane.dumps(COMPLEX_DOC, variant="full") == (
        "Entities:\n"
        "`metastatic breast cancer` is a DISEASE found in `metastatic breast cancer cells`\n"
        "`breast cancer cells` is a CELL found in `metastatic breast cancer cells caused`\n"
        "`headache` and `nausea` are a ADR found in `caused headache and` and `and nausea`"
    )


def test_empty_document_is_none_marker() -> None:
    assert cane.dumps(doc("text"), variant="base") == "NONE"


def test_reading_order_outer_before_nested() -> None:
    text = "breast cancer cells"
    d = doc(
        text,
        ("B", [at(text, "breast cancer")]),
        ("A", [at(text, text)]),
        ("C", [at(text, "cells")]),
    )
    lines = cane.dumps(d, variant="base").splitlines()[1:]
    assert lines == ["`breast cancer cells` is a A", "`breast cancer` is a B", "`cells` is a C"]


def test_discontinuous_in_base_raises_or_follows_strategy() -> None:
    with pytest.raises(cane.UnrepresentableError):
        cane.dumps(COMPLEX_DOC, variant="base")
    with pytest.warns(cane.LossyConversionWarning):
        skipped = cane.dumps(COMPLEX_DOC, variant="base", on_unrepresentable="skip")
    assert "ADR" not in skipped
    with pytest.warns(cane.LossyConversionWarning):
        first = cane.dumps(COMPLEX_DOC, variant="base", on_unrepresentable="first")
    assert "`headache` is a ADR" in first
    with pytest.warns(cane.LossyConversionWarning):
        hull = cane.dumps(COMPLEX_DOC, variant="base", on_unrepresentable="hull")
    assert "`headache and nausea` is a ADR" in hull


def test_unlabelled_and_bad_labels() -> None:
    with pytest.raises(cane.UnrepresentableError):
        cane.dumps(doc("ab", (None, [(0, 1)])), variant="base")
    with pytest.raises(cane.UnrepresentableError):
        cane.dumps(doc("ab", ("TWO WORDS", [(0, 1)])), variant="base")


def test_whitespace_is_collapsed_and_edges_refused() -> None:
    text = "pain in\r\n\tthe  chest"
    out = cane.dumps(doc(text, ("S", [(0, len(text))])), variant="context")
    assert out.splitlines()[1] == "`pain in the chest` is a S found in `pain in the chest`"
    with pytest.raises(cane.UnrepresentableError):
        cane.dumps(doc("a b", ("S", [(0, 2)])), variant="base")


def test_delimiter_collision() -> None:
    d = doc("use `x` here", ("CODE", [(4, 7)]))
    with pytest.raises(cane.UnrepresentableError):
        cane.dumps(d, variant="base")
    out = cane.dumps(d, variant="base", dialect=cane.Dialect(quote_open="«", quote_close="»"))
    assert out.splitlines()[1] == "«`x`» is a CODE"


def test_handles_renumber_in_output_order() -> None:
    lines = cane.dumps(COMPLEX_DOC, variant="disco", handles=True).splitlines()[1:]
    assert [line.split()[0] for line in lines] == ["T1", "T2", "T3"]


def test_anchor_size_and_mid_word_units() -> None:
    text = "the hereinafter clause, applies"
    d = doc(text, ("X", [at(text, "inafter")]))
    # The rest of a word the span starts inside ("here") counts as one unit.
    assert "found in `hereinafter clause,`" in cane.dumps(d, variant="context")
    assert "found in `the hereinafter clause, applies`" in cane.dumps(
        d, variant="context", context=2
    )


def test_lossy_warning_lists_what_cannot_be_carried() -> None:
    d = cane.Document(
        text="ab",
        entities=(
            cane.Entity(spans=[(0, 1)], label="X", id="T1", concepts=(cane.Concept(id="MESH:1"),)),
        ),
        relations=(cane.Relation(type="R", members=[("T1", "Arg1")]),),
    )
    with pytest.warns(cane.LossyConversionWarning, match="1 relations; 1 concepts"):
        cane.dumps(d, variant="base")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        cane.dumps(d, variant="base", lossy="ignore")


def test_other_dialect() -> None:
    german = cane.Dialect(
        header="Entitäten:",
        copula_singular="ist",
        copula_plural="sind",
        articles=("ein", "eine"),
        anchor_intro="gefunden in",
        part_connective="und",
        anchor_connective="und",
        empty="KEINE",
    )
    out = cane.dumps(AMOX, variant="context", dialect=german)
    assert out.splitlines()[1] == "`amoxicillin` ist ein DRUG gefunden in `starting amoxicillin,`"
    back = cane.loads(out, text=TEXT, variant="context", dialect=german)
    assert back.ok and back.entities == AMOX.entities
