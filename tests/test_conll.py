from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import cane_format as cane
from cane_format import Entity
from tests.conftest import at, doc
from tests.test_extremes import EXTREMES

CONLL = """\
-DOCSTART- -X- -X- O

EU NNP B-NP B-ORG
rejects VBZ B-VP O
German JJ B-NP B-MISC
call NN I-NP O
. . O O

Peter NNP B-NP B-PER
Blackburn NNP I-NP I-PER

-DOCSTART- -X- -X- O

BRUSSELS NNP B-NP B-LOC
"""


def labelled(d: cane.Document) -> list[tuple[str | None, str]]:
    return [(e.label, d.text[e.start : e.end]) for e in d.entities]


def test_reads_documents_sentences_and_columns() -> None:
    first, second = cane.parse_conll(CONLL)
    assert first.text == "EU rejects German call .\nPeter Blackburn"
    assert labelled(first) == [("ORG", "EU"), ("MISC", "German"), ("PER", "Peter Blackburn")]
    assert first.metadata["text_reconstructed"] is True
    tokens = [s for s in first.segments if s.kind == "token"]
    assert tokens[0].metadata["columns"] == ("NNP", "B-NP")
    assert [s.span for s in first.segments if s.kind == "sentence"] == [(0, 24), (25, 40)]
    assert labelled(second) == [("LOC", "BRUSSELS")]


def test_conll_round_trip_reproduces_tokens_and_tags() -> None:
    out = "".join(cane.format_conll(d) for d in cane.parse_conll(CONLL))
    assert out == CONLL + "\n"  # canonical form: every sentence ends with a blank line


def test_without_docstart_every_sentence_is_a_document() -> None:
    docs = cane.parse_conll("A B-X\nb I-X\n\nc O\n")
    assert [d.text for d in docs] == ["A b", "c"]


def test_align_onto_raw_text() -> None:
    raw = "EU rejects German call.\n\nPeter  Blackburn"
    d = cane.parse_conll(CONLL.split("\n-DOCSTART")[0], text=raw)[0]
    assert labelled(d) == [("ORG", "EU"), ("MISC", "German"), ("PER", "Peter  Blackburn")]
    assert "text_reconstructed" not in d.metadata
    with pytest.raises(cane.CaneFormatError):
        cane.parse_conll(CONLL.split("\n-DOCSTART")[0], text="EU rejected German call.")
    with pytest.raises(cane.CaneFormatError):
        cane.parse_conll(CONLL, text=raw)  # two documents


@pytest.mark.parametrize(
    ("scheme", "tags", "expected"),
    [
        ("bio", ["B-X", "I-X", "B-X", "O", "B-Y"], [("X", 0, 1), ("X", 2, 2), ("Y", 4, 4)]),
        ("iob1", ["I-X", "I-X", "B-X", "O", "I-Y"], [("X", 0, 1), ("X", 2, 2), ("Y", 4, 4)]),
        ("bioes", ["B-X", "E-X", "S-X", "O", "S-Y"], [("X", 0, 1), ("X", 2, 2), ("Y", 4, 4)]),
        ("bilou", ["B-X", "L-X", "U-X", "O", "U-Y"], [("X", 0, 1), ("X", 2, 2), ("Y", 4, 4)]),
        ("bio", ["B-protein_N/A", "I-protein_N/A"], [("protein_N/A", 0, 1)]),
    ],
)
def test_schemes_decode_and_encode(
    scheme: cane.conll.Scheme, tags: list[str], expected: list[tuple[str, int, int]]
) -> None:
    assert list(cane.conll.decode(list(enumerate(tags, 1)), scheme)) == expected
    tokens = [f"t{i}" for i in range(len(tags))]
    d = cane.from_tokens(tokens, tags, scheme=scheme)
    written = [
        line.split()[-1] for line in cane.format_conll(d, scheme=scheme).splitlines() if line
    ]
    assert written == tags


@pytest.mark.parametrize(
    ("scheme", "tags"),
    [
        ("bio", ["O", "I-X"]),
        ("bio", ["B-X", "I-Y"]),
        ("iob1", ["O", "B-X"]),
        ("bioes", ["B-X", "O"]),
        ("bioes", ["I-X"]),
        ("bioes", ["B-X"]),
        ("bio", ["E-X"]),
        ("bio", ["BX"]),
    ],
)
def test_invalid_sequences_raise_unless_repaired(
    scheme: cane.conll.Scheme, tags: list[str]
) -> None:
    with pytest.raises(cane.CaneFormatError):
        list(cane.conll.decode(list(enumerate(tags, 1)), scheme))
    if "BX" not in tags and "E-X" not in tags:
        assert list(cane.conll.decode(list(enumerate(tags, 1)), scheme, repair=True))


def test_from_tokens_with_hugging_face_ids() -> None:
    d = cane.from_tokens(["EU", "rejects"], [1, 0], label_names=["O", "B-ORG"], id="hf-0")
    assert labelled(d) == [("ORG", "EU")] and d.id == "hf-0"
    with pytest.raises(cane.CaneFormatError):
        cane.from_tokens(["EU"], [1])


TEXT = "After starting amoxicillin, the patient developed a rash."


def test_writes_documents_without_tokens() -> None:
    d = doc(TEXT, ("DRUG", [at(TEXT, "amoxicillin")]), ("ADR", [at(TEXT, "rash")]))
    with pytest.warns(cane.LossyConversionWarning, match="whitespace"):
        out = cane.format_conll(d)
    assert "amoxicillin B-DRUG\n, O\n" in out and "rash B-ADR\n. O\n" in out


def test_alignment_policies() -> None:
    d = doc("hereinafter clause", ("X", [(4, 11)]))
    with pytest.raises(cane.UnrepresentableError):
        cane.format_conll(d, lossy="ignore")
    expanded = cane.format_conll(d, alignment="expand", lossy="ignore")
    assert expanded.startswith("hereinafter B-X")
    contracted = cane.format_conll(d, alignment="contract", lossy="ignore")
    assert "B-X" not in contracted


def test_conflicts_and_unrepresentable() -> None:
    text = "breast cancer cells caused headache and nausea"
    d = doc(
        text,
        ("CELL", [at(text, "breast cancer cells")]),
        ("D", [at(text, "breast cancer")]),
        ("ADR", [at(text, "headache"), at(text, "nausea")]),
    )
    with pytest.raises(cane.UnrepresentableError):
        cane.format_conll(d, on_unrepresentable="split", lossy="ignore")  # nested conflict
    with pytest.raises(cane.UnrepresentableError):
        cane.format_conll(d, on_conflict="outermost", lossy="ignore")  # discontinuous
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        outer = cane.format_conll(d, on_conflict="outermost", on_unrepresentable="split")
        inner = cane.format_conll(d, on_conflict="innermost", on_unrepresentable="hull")
        skip = cane.format_conll(d, on_conflict="skip", on_unrepresentable="skip")
    assert "breast B-CELL\ncancer I-CELL\ncells I-CELL" in outer
    assert "headache B-ADR\nand O\nnausea B-ADR" in outer
    assert "breast B-D\ncancer I-D\ncells O" in inner and "and I-ADR" in inner
    assert "B-" not in skip


def test_entity_crossing_sentences() -> None:
    text = "a b\nc d"
    two = cane.Document(
        text=text,
        entities=[Entity(spans=[(2, 5)], label="X")],
        segments=[
            cane.Segment(kind="sentence", span=(0, 3)),
            cane.Segment(kind="sentence", span=(4, 7)),
        ],
    )
    with pytest.raises(cane.UnrepresentableError):
        cane.format_conll(two, lossy="ignore")
    assert "B-X" not in cane.format_conll(two, on_unrepresentable="skip", lossy="ignore")


def test_files(tmp_path: Path) -> None:
    path = tmp_path / "train.conll"
    path.write_text(CONLL, encoding="utf-8")
    docs = cane.read_conll(path)
    assert [d.id for d in docs] == ["train-1", "train-2"]
    cane.write_conll(docs, tmp_path / "out.conll")
    again = cane.read_conll(tmp_path / "out.conll")
    assert [labelled(d) for d in again] == [labelled(d) for d in docs]


def test_sub_token_entities_are_refused() -> None:
    with pytest.raises(cane.UnrepresentableError, match="token boundaries"):
        cane.format_conll(EXTREMES["adjacent entities, no gap"], lossy="ignore")


@pytest.mark.parametrize(
    "name",
    [
        "offsets 0 and end",
        "emoji and astral characters",
        "right-to-left text",
    ],
)
def test_extremes_through_conll(name: str) -> None:
    d = EXTREMES[name]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", cane.LossyConversionWarning)
        out = cane.format_conll(d, alignment="strict")
    back = cane.parse_conll(out)[0]
    assert sorted(t for _, t in labelled(back)) == sorted(
        " ".join(d.text[e.start : e.end].split()) for e in d.entities
    )


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["EU", "p53", "naïve", "🔥", ",", "x"]),
            st.sampled_from(["O", "B-A", "I-A", "B-B", "I-B"]),
        ),
        min_size=1,
        max_size=30,
    ),
    st.sampled_from(["bio", "iob1", "bioes", "bilou"]),
)
def test_generated_tag_sequences_round_trip(pairs: list[tuple[str, str]], scheme: str) -> None:
    tokens = [t for t, _ in pairs]
    d = cane.from_tokens(tokens, [g for _, g in pairs], scheme="bio", repair=True)
    out = cane.format_conll(d, scheme=scheme)  # type: ignore[arg-type]
    back = cane.parse_conll(out, scheme=scheme)[0]  # type: ignore[arg-type]
    assert back.entities == d.entities and back.text == d.text
