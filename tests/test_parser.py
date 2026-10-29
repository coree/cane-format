from __future__ import annotations

import pytest

import cane_format as cane
from cane_format import IssueKind, Span
from tests.conftest import at, same_entities

TEXT = "After starting amoxicillin, the patient developed a rash."


def kinds(result: cane.ParseResult) -> list[IssueKind]:
    return [i.kind for i in result.issues]


def spans(result: cane.ParseResult) -> list[tuple[Span, ...]]:
    return [e.spans for e in result.entities]


def test_header_optional_and_empty_markers() -> None:
    with_header = cane.loads("Entities:\n`rash` is a ADR", text=TEXT, variant="base")
    without = cane.loads("`rash` is a ADR", text=TEXT, variant="base")
    assert with_header.ok and without.ok and with_header.entities == without.entities
    for empty in (
        "NONE",
        "none",
        "Entities:\nNONE",
        "Entities:\n\nnone\n",
        "Entities:",
        "Entities:\n",
    ):
        result = cane.loads(empty, text=TEXT, variant="base")
        assert result.ok and result.entities == ()
    # On one line, NONE is not the empty marker.
    one_line = cane.loads("Entities: NONE", text=TEXT, variant="base")
    assert kinds(one_line) == [IssueKind.MALFORMED_LINE]
    # NONE among records is a bad line, not an empty output.
    mixed = cane.loads("Entities:\nNONE\n`rash` is a ADR", text=TEXT, variant="base")
    assert kinds(mixed) == [IssueKind.MALFORMED_LINE] and len(mixed.entities) == 1


def test_empty_output_is_reported() -> None:
    """An empty output usually means the generation failed, so it is not a clean result."""
    for empty in ("", "  \n ", "\n\n"):
        result = cane.loads(empty, text=TEXT, variant="base")
        assert result.entities == () and kinds(result) == [IssueKind.EMPTY_OUTPUT]
        assert result.issues[0].line_no is None


def test_articles_accepted() -> None:
    for line in ("`rash` is a ADR", "`rash` is an ADR", "`rash` is ADR"):
        result = cane.loads(line, text=TEXT, variant="base")
        assert result.ok and result.entities[0].label == "ADR"
    assert kinds(cane.loads("`rash` is a", text=TEXT, variant="base")) == [IssueKind.MALFORMED_LINE]


def test_strict_lines_are_per_line_issues() -> None:
    output = "Entities:\nSure, here you go:\n`rash` is a ADR\n- `amoxicillin` is a DRUG"
    result = cane.loads(output, text=TEXT, variant="base")
    assert kinds(result) == [IssueKind.MALFORMED_LINE] * 2
    assert [i.line_no for i in result.issues] == [2, 4]
    assert [e.label for e in result.entities] == ["ADR"]
    lenient = cane.loads(output, text=TEXT, variant="base", strip_list_markers=True)
    assert [e.label for e in lenient.entities] == ["ADR", "DRUG"]


def test_literal_backslash_n_is_not_converted() -> None:
    result = cane.loads("`rash` is a ADR\\n`amoxicillin` is a DRUG", text=TEXT, variant="base")
    assert not result.ok


@pytest.mark.parametrize(
    ("variant", "line", "kind"),
    [
        ("base", "`a` and `b` is a X", IssueKind.MALFORMED_LINE),
        ("base", "`rash` is a ADR found in `a rash.`", IssueKind.MALFORMED_LINE),
        ("context", "`rash` is a ADR", IssueKind.MALFORMED_LINE),
        ("full", "`a` and `rash` are a X found in `a rash.`", IssueKind.PART_COUNT_MISMATCH),
    ],
)
def test_variant_is_enforced(variant: str, line: str, kind: IssueKind) -> None:
    assert kinds(cane.loads(line, text=TEXT, variant=variant)) == [kind]


def test_variant_is_required() -> None:
    with pytest.raises(TypeError):
        cane.loads("NONE", text=TEXT)


def test_options_object_is_recorded_and_exclusive() -> None:
    options = cane.ParseOptions(variant=cane.Variant.BASE, match="casefold")
    result = cane.loads("`RASH` is a ADR", text=TEXT, options=options)
    assert result.settings is options and result.ok
    assert result.entities[0].metadata["match"] == "casefold"
    with pytest.raises(TypeError):
        cane.loads("NONE", text=TEXT, options=options, handles=True)


def test_not_found_and_raise_for_errors() -> None:
    result = cane.loads("`fever` is a ADR\n`rash` is a ADR", text=TEXT, variant="base")
    assert kinds(result) == [IssueKind.NOT_FOUND] and len(result.entities) == 1
    with pytest.raises(cane.ParseError, match="not_found"):
        result.raise_for_errors()


def test_repeated_mentions_take_successive_occurrences() -> None:
    text = "Take aspirin with food. If pain persists, take aspirin again."
    result = cane.loads("`aspirin` is a DRUG\n`aspirin` is a DRUG", text=text, variant="base")
    assert result.ok and spans(result) == [
        (Span(*at(text, "aspirin")),),
        (Span(*at(text, "aspirin", 1)),),
    ]
    third = cane.loads("`aspirin` is a DRUG\n" * 3, text=text, variant="base")
    assert kinds(third) == [IssueKind.DUPLICATE]


def test_nested_entities_follow_reading_order() -> None:
    text = "breast cancer cells and breast cancer"
    output = (
        "`breast cancer cells` is a CELL\n`breast cancer` is a DISEASE\n"
        "`breast cancer` is a DISEASE"
    )
    result = cane.loads(output, text=text, variant="base")
    assert result.ok and spans(result)[1] == (Span(0, 13),)
    assert spans(result)[2] == (Span(*at(text, "breast cancer", 1)),)


def test_same_span_other_label_is_kept() -> None:
    result = cane.loads("`p53` is a GENE\n`p53` is a PROTEIN", text="p53 binds", variant="base")
    assert result.ok and spans(result) == [(Span(0, 3),), (Span(0, 3),)]


def test_previous_position_guides_fragments() -> None:
    text = "hereditary breast cancer ... to breast and ovarian cancers"
    # Without anchors, a fragment right after its would-be container reads as nested in it.
    output = "`hereditary breast cancer` is a D\n`breast` and `cancers` are a D"
    nested = cane.loads(output, text=text, variant="disco")
    assert nested.entities[1].spans == (Span(*at(text, "breast")), Span(*at(text, "cancers")))
    # An entity in between moves the reading position past the container.
    between = cane.loads(output.replace("\n", "\n`to` is a P\n"), text=text, variant="disco")
    assert between.entities[2].spans == (Span(*at(text, "breast", 1)), Span(*at(text, "cancers")))
    # Anchors remove the ambiguity.
    anchored = (
        "`hereditary breast cancer` is a D found in `hereditary breast cancer ...`\n"
        "`breast` and `cancers` are a D found in `to breast and` and `ovarian cancers`"
    )
    full = cane.loads(anchored, text=text, variant="full")
    assert full.ok
    assert full.entities[1].spans == (Span(*at(text, "breast", 1)), Span(*at(text, "cancers")))


def test_parts_in_any_order() -> None:
    text = "it caused headache and nausea"
    result = cane.loads("`nausea` and `headache` are a ADR", text=text, variant="disco")
    assert result.ok and result.entities[0].spans == (
        Span(*at(text, "headache")),
        Span(*at(text, "nausea")),
    )


def test_partial_parts_ground_nothing() -> None:
    text = "it caused headache and nausea"
    result = cane.loads(
        "`headache` and `fever` are a ADR\n`headache` is a ADR", text=text, variant="disco"
    )
    assert kinds(result) == [IssueKind.NOT_FOUND]
    assert spans(result) == [(Span(*at(text, "headache")),)]


def test_prefer_whole_words_only_reorders_occurrences() -> None:
    text = "Tate against Northamptonshire at Northampton"
    whole = (Span(*at(text, "Northampton", 1)),)
    record = "`Northampton` is a LOC"
    assert spans(cane.loads(record, text=text, variant="base")) == [
        (Span(*at(text, "Northampton")),)
    ]
    for variant, output in (
        ("base", record),
        ("disco", record),
        ("context", record + " found in `Northampton`"),
        ("full", record + " found in `Northampton`"),
    ):
        result = cane.loads(output, text=text, variant=variant, prefer_whole_words=True)
        assert result.ok and spans(result) == [whole]
    # A second mention still gets the remaining occurrence, inside the longer word.
    twice = cane.loads(record + "\n" + record, text=text, variant="base", prefer_whole_words=True)
    assert twice.ok and spans(twice) == [whole, (Span(*at(text, "Northampton")),)]
    # Nothing is rejected: a part that occurs only inside a word still grounds there.
    inside = cane.loads(
        "`Petra` is a LOC", text="Arabia Petraea", variant="base", prefer_whole_words=True
    )
    assert inside.ok and spans(inside) == [(Span(7, 12),)]


def test_prefer_whole_words_keeps_reading_order_among_whole_words() -> None:
    text = "aspirin, then aspirinate, then aspirin"
    output = "`then` is a X\n`aspirin` is a DRUG"
    # The reading position is at the first "then". Without the flag the next occurrence wins,
    # inside "aspirinate"; with it, the next whole word (the earlier whole word comes last
    # among whole words because it is before the reading position).
    plain_order = cane.loads(output, text=text, variant="base")
    assert spans(plain_order)[1] == (Span(*at(text, "aspirin", 1)),)
    result = cane.loads(output, text=text, variant="base", prefer_whole_words=True)
    assert spans(result)[1] == (Span(*at(text, "aspirin", 2)),)
    # Script without spaces: every occurrence is inside a word, so the order is unchanged.
    cjk = "阿司匹林和阿司匹林"
    plain = cane.loads("`阿司匹林` is a DRUG", text=cjk, variant="base")
    preferred = cane.loads(
        "`阿司匹林` is a DRUG", text=cjk, variant="base", prefer_whole_words=True
    )
    assert spans(plain) == spans(preferred) == [(Span(0, 4),)]


def test_anchor_selects_occurrence() -> None:
    text = "aspirin twice daily, then aspirin once"
    result = cane.loads(
        "`aspirin` is a DRUG found in `then aspirin once`", text=text, variant="context"
    )
    assert result.ok and spans(result) == [(Span(*at(text, "aspirin", 1)),)]


def test_anchor_whitespace_is_flexible() -> None:
    text = "took\n\naspirin   daily"
    result = cane.loads(
        "`aspirin` is a DRUG found in `took aspirin daily`", text=text, variant="context"
    )
    assert result.ok and spans(result) == [(Span(*at(text, "aspirin")),)]


def test_anchor_not_found_and_fallback() -> None:
    wrong = "`amoxicillin` is a DRUG found in `took ibuprofen daily`"
    missing = "`amoxicillin` is a DRUG found in `stopping amoxicillin,`"
    for line in (wrong, missing):
        assert kinds(cane.loads(line, text=TEXT, variant="context")) == [IssueKind.ANCHOR_NOT_FOUND]
    result = cane.loads(missing, text=TEXT, variant="context", anchor_fallback=True)
    assert result.ok and result.entities[0].metadata["unanchored"] is True
    assert kinds(cane.loads(wrong, text=TEXT, variant="context", anchor_fallback=True)) == []


def test_part_twice_inside_its_anchor() -> None:
    text = "she said the the end of the story"
    result = cane.loads("`the` is a W found in `the the end`", text=text, variant="context")
    assert result.ok and spans(result) == [(Span(*at(text, "the")),)]
    two = cane.loads(
        "`the` is a W found in `the the end`\n`the` is a W found in `the the end`",
        text=text,
        variant="context",
    )
    assert two.ok and spans(two)[1] == (Span(*at(text, "the", 1)),)


def test_labels_unknown_kept_with_issue() -> None:
    result = cane.loads("`rash` is a SYMPTOM", text=TEXT, variant="base", labels={"ADR"})
    assert kinds(result) == [IssueKind.INVALID_LABEL] and result.entities[0].label == "SYMPTOM"


def test_labels_with_slashes() -> None:
    result = cane.loads("`rash` is a protein_N/A", text=TEXT, variant="base")
    assert result.ok and result.entities[0].label == "protein_N/A"


def test_match_levels_are_never_mixed() -> None:
    text = "Café au lait"  # e + combining acute
    line = "`Café` is a DRINK"  # precomposed é
    assert kinds(cane.loads(line, text=text, variant="base")) == [IssueKind.NOT_FOUND]
    result = cane.loads(line, text=text, variant="base", match="normalized")
    assert result.ok and spans(result) == [(Span(0, 5),)]
    assert kinds(
        cane.loads("`CAFÉ` is a DRINK", text=text, variant="base", match="normalized")
    ) == [IssueKind.NOT_FOUND]
    assert cane.loads("`CAFÉ` is a DRINK", text=text, variant="base", match="casefold").ok


def test_handles_become_ids() -> None:
    output = "Entities:\nT1 `amoxicillin` is a DRUG\nT2 `rash` is a ADR"
    result = cane.loads(output, text=TEXT, variant="base", handles=True)
    assert result.ok and [e.id for e in result.entities] == ["T1", "T2"]
    assert kinds(cane.loads(output, text=TEXT, variant="base")) == [IssueKind.MALFORMED_LINE] * 2
    assert kinds(cane.loads("`rash` is a ADR", text=TEXT, variant="base", handles=True)) == [
        IssueKind.MALFORMED_LINE
    ]


def test_grammar_words_inside_content() -> None:
    text = "the drug is a found in thing and Entities: NONE"
    entities = ["is a", "found in", "and", "Entities:", "NONE"]
    output = "Entities:\n" + "\n".join(f"`{e}` is a X found in `{e}`" for e in entities)
    result = cane.loads(output, text=text, variant="context")
    assert result.ok
    assert [result.text[e.start : e.end] for e in result.entities] == entities


def test_round_trip_paper_examples() -> None:
    from tests.test_formatter import AMOX, COMPLEX_DOC

    for d, variants in (
        (AMOX, ("base", "disco", "context", "full")),
        (COMPLEX_DOC, ("disco", "full")),
    ):
        for variant in variants:
            back = cane.loads(cane.dumps(d, variant=variant), text=d.text, variant=variant)
            assert back.ok and same_entities(back.entities, d.entities)
