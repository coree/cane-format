from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import cane_format as cane
from cane_format import Entity
from cane_format.cli import main
from tests.conftest import doc
from tests.test_brat import ANN, TEXT
from tests.test_formatter import AMOX, COMPLEX_DOC

# --- nervaluate-disco ---------------------------------------------------------------------


def test_to_nervaluate() -> None:
    assert cane.to_nervaluate([COMPLEX_DOC])[0]["entities"][2] == {
        "spans": [(38, 46), (51, 57)],
        "label": "ADR",
        "text": "headache nausea",
    }
    unlabelled = doc("ab", (None, [(0, 1)]), ("X", [(1, 2)]))
    with pytest.raises(cane.UnrepresentableError):
        cane.to_nervaluate([unlabelled])
    assert len(cane.to_nervaluate([unlabelled], unlabelled="skip")[0]["entities"]) == 1


# --- prompts ------------------------------------------------------------------------------


def test_prompt_layout_and_examples_match_the_formatter() -> None:
    prompt = cane.build_prompt(
        "Aspirin caused nausea.", examples=[AMOX, COMPLEX_DOC], variant="full"
    )
    sections = prompt.split("\n\n")
    assert sections[0] == "Task: Named Entity Recognition"
    assert sections[1] == "Entities: ADR, CELL, DISEASE, DRUG"
    assert sections[2].startswith("Format: CANE-Full\nGuidelines: Start the output with")
    assert cane.dumps(COMPLEX_DOC, variant="full") in prompt
    assert prompt.endswith("---\nInput: Aspirin caused nausea.\nOutput:")


@pytest.mark.parametrize("variant", ["base", "disco", "context", "full"])
def test_guideline_mentions_only_what_the_variant_has(variant: str) -> None:
    text = cane.guideline(variant)
    assert ("found in" in text) == cane.Variant(variant).anchored
    assert ("are a" in text) == cane.Variant(variant).multi_part
    assert "is a" in text and "NONE" in text


def test_guideline_uses_the_dialect() -> None:
    german = cane.Dialect(
        header="Entitäten:",
        copula_singular="ist",
        copula_plural="sind",
        articles=("ein",),
        anchor_intro="gefunden in",
    )
    text = cane.guideline("context", dialect=german, handles=True, context=2)
    assert "'Entitäten:'" in text and "ist ein" in text and "gefunden in" in text
    assert "2 words" in text and "T1" in text


# --- command line -------------------------------------------------------------------------


@pytest.fixture
def brat_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "brat"
    cane.write_brat([cane.parse_brat(TEXT, ANN, id="doc")], directory)
    return directory


def test_convert_brat_to_json_and_back(brat_dir: Path, tmp_path: Path) -> None:
    assert (
        main(
            ["convert", str(brat_dir), str(tmp_path / "d.jsonl"), "--from", "brat", "--to", "json"]
        )
        == 0
    )
    assert (
        main(
            [
                "convert",
                str(tmp_path / "d.jsonl"),
                str(tmp_path / "again"),
                "--from",
                "json",
                "--to",
                "brat",
            ]
        )
        == 0
    )
    assert cane.read_brat(tmp_path / "again") == cane.read_brat(brat_dir)


def test_convert_to_cane_and_conll(brat_dir: Path, tmp_path: Path) -> None:
    assert (
        main(
            [
                "convert",
                str(brat_dir),
                str(tmp_path / "cane"),
                "--from",
                "brat",
                "--to",
                "cane-full",
            ]
        )
        == 0
    )
    assert (tmp_path / "cane" / "doc.cane").read_text().startswith("Entities:\n`IL-2` is a")
    assert (
        main(
            ["convert", str(brat_dir), str(tmp_path / "x.conll"), "--from", "brat", "--to", "conll"]
        )
        == 0
    )
    assert "IL B-Protein\n- I-Protein\n2 I-Protein" in (tmp_path / "x.conll").read_text()
    nested = tmp_path / "nested"
    cane.write_brat(
        [cane.Document(text=COMPLEX_DOC.text, entities=COMPLEX_DOC.entities, id="n")], nested
    )
    args = ["convert", str(nested), str(tmp_path / "n.conll"), "--from", "brat", "--to", "conll"]
    assert main(args) == 2  # overlapping and discontinuous entities are refused by default
    assert main([*args, "--on-conflict", "outermost", "--on-unrepresentable", "split"]) == 0


def test_failed_conversion_writes_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    cane.write_brat(
        [cane.Document(text=COMPLEX_DOC.text, entities=COMPLEX_DOC.entities, id="n")], bad
    )
    out = tmp_path / "out"
    assert main(["convert", str(bad), str(out), "--from", "brat", "--to", "cane-base"]) == 2
    assert not out.exists()


def test_parse_model_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "text.txt").write_text(AMOX.text, encoding="utf-8")
    (tmp_path / "out.cane").write_text(cane.dumps(AMOX, variant="base") + "\n`fever` is a ADR")
    args = [
        "parse",
        str(tmp_path / "out.cane"),
        "--text",
        str(tmp_path / "text.txt"),
        "--variant",
        "base",
    ]
    assert main(args) == 1
    captured = capsys.readouterr()
    assert "not_found" in captured.err
    parsed = cane.parse_json(captured.out.strip())
    assert [e.label for e in parsed.entities] == ["DRUG", "ADR"]
    assert main([*args, "--allow-issues", "--to", "brat", "-o", str(tmp_path / "b")]) == 0
    assert (tmp_path / "b" / "text.ann").exists()


def test_cli_errors_are_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert main(["convert", str(tmp_path / "bad.json"), "-", "--from", "json", "--to", "xml"]) == 2
    assert "error" in capsys.readouterr().err
    assert json.loads(json.dumps({"ok": True}))  # keeps json import used


# --- review fixes ---------------------------------------------------------------------------


def test_guideline_with_brace_delimiters() -> None:
    text = cane.guideline("disco", dialect=cane.Dialect(quote_open="{", quote_close="}"))
    assert "{entity} is a TYPE" in text and "{part1} and {part2} are a TYPE" in text
    mixed = cane.guideline("base", dialect=cane.Dialect(quote_open="{", quote_close="»"))
    assert "{entity» is a TYPE" in mixed


def test_prompt_labels_are_reproducible_and_required() -> None:
    a = cane.build_prompt("x", examples=[AMOX], variant="base", labels={"DRUG", "ADR"})
    assert "Entities: ADR, DRUG\n" in a
    assert "Entities: DRUG, ADR\n" in cane.build_prompt(
        "x", examples=[AMOX], variant="base", labels=["DRUG", "ADR"]
    )
    zero_shot = cane.build_prompt("x", examples=[], variant="base", labels=["DRUG"])
    assert "Examples:" not in zero_shot and zero_shot.endswith("---\nInput: x\nOutput:")
    with pytest.raises(ValueError):
        cane.build_prompt("x", examples=[], variant="base")


def test_loads_sets_the_document_id(tmp_path: Path) -> None:
    result = cane.loads(
        cane.dumps(AMOX, variant="base"), text=AMOX.text, variant="base", id="doc-17"
    )
    assert result.document.id == "doc-17"
    cane.write_brat([result.document], tmp_path)  # the README walkthrough's last step
    assert (tmp_path / "doc-17.ann").exists()


@pytest.mark.parametrize("strategy", ["skip", "first", "hull"])
def test_strategies_skip_label_problems(strategy: str) -> None:
    d = doc("a b c", (None, [(0, 1)]), ("TWO WORDS", [(2, 3)]), ("OK", [(4, 5)]))
    with pytest.warns(cane.LossyConversionWarning, match="skipped") as record:
        out = cane.dumps(d, variant="base", on_unrepresentable=strategy)  # type: ignore[arg-type]
    assert out.splitlines()[1:] == ["`c` is a OK"]
    assert "None" not in out and str(record[0].message).startswith("document")


@pytest.mark.parametrize("strategy", ["skip", "first", "hull", "split"])
def test_conll_strategies_skip_label_problems(strategy: str) -> None:
    d = doc("a b c", (None, [(0, 1)]), ("TWO WORDS", [(2, 3)]), ("OK", [(4, 5)]))
    with pytest.warns(cane.LossyConversionWarning, match="skipped"):
        out = cane.format_conll(d, on_unrepresentable=strategy)  # type: ignore[arg-type]
    assert out == "a O\nb O\nc B-OK\n\n"


def test_lossy_warnings_name_the_document() -> None:
    d = cane.Document(
        text="a b",
        id="doc-9",
        metadata={"source": "x"},
        entities=(Entity(spans=[(0, 1)], label="X"),),
    )
    writers: list[Callable[[], object]] = [
        lambda: cane.dumps(d, variant="base"),
        lambda: cane.format_brat(d),
        lambda: cane.format_conll(d),
        lambda: cane.format_xml(d),
    ]
    for write in writers:
        with pytest.warns(cane.LossyConversionWarning, match="document doc-9"):
            write()


# --- CLI review fixes ---------------------------------------------------------------------


def _jsonl(path: Path, *docs: cane.Document) -> Path:
    cane.write_json(docs, path)
    return path


DRUGS = [
    cane.Document(text="Aspirin helps.", id="a", entities=(Entity(spans=[(0, 7)], label="DRUG"),)),
    cane.Document(
        text="Ibuprofen hurts.", id="b", entities=(Entity(spans=[(0, 9)], label="DRUG"),)
    ),
]


def test_cli_xml_keeps_documents_and_ids(tmp_path: Path) -> None:
    src = _jsonl(tmp_path / "d.jsonl", *DRUGS)
    assert (
        main(["convert", str(src), str(tmp_path / "o.xml"), "--from", "json", "--to", "xml"]) == 0
    )
    assert (
        main(
            [
                "convert",
                str(tmp_path / "o.xml"),
                str(tmp_path / "back.jsonl"),
                "--from",
                "xml",
                "--to",
                "json",
            ]
        )
        == 0
    )
    assert cane.read_json(tmp_path / "back.jsonl") == DRUGS


def test_cli_dash_is_stdout_or_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    src = _jsonl(tmp_path / "d.jsonl", *DRUGS)
    for target in ("cane-full", "brat"):
        assert main(["convert", str(src), "-", "--from", "json", "--to", target]) == 2
    assert not (tmp_path / "-").exists()
    assert main(["convert", str(src), "-", "--from", "json", "--to", "conll"]) == 0
    assert "Aspirin B-DRUG" in capsys.readouterr().out
    (tmp_path / "t.txt").write_text("Aspirin helps.", encoding="utf-8")
    (tmp_path / "m.cane").write_text("`Aspirin` is a DRUG", encoding="utf-8")
    assert main(["parse", "m.cane", "--text", "t.txt", "--variant", "base", "--to", "brat"]) == 2
    assert not (tmp_path / "-").exists()


@pytest.mark.parametrize("ids", [("a", "a"), ("a", "A"), ("../escape", "b")])
def test_cli_file_names_are_safe_and_unique(tmp_path: Path, ids: tuple[str | None, str]) -> None:
    docs = [
        cane.Document(text=d.text, entities=d.entities, id=i)
        for d, i in zip(DRUGS, ids, strict=True)
    ]
    src = _jsonl(tmp_path / "d.jsonl", *docs)
    for target in ("cane-base", "brat"):
        out = tmp_path / target
        assert main(["convert", str(src), str(out), "--from", "json", "--to", target]) == 2
        assert not out.exists()
    assert not (tmp_path / "escape.cane").exists()


def test_cli_rejects_unknown_and_inapplicable_options(tmp_path: Path) -> None:
    src = _jsonl(tmp_path / "d.jsonl", *DRUGS)
    with pytest.raises(SystemExit):
        main(
            [
                "convert",
                str(src),
                "-",
                "--from",
                "json",
                "--to",
                "conll",
                "--on-conflict",
                "outermsot",
            ]
        )
    assert (
        main(
            [
                "convert",
                str(src),
                str(tmp_path / "c"),
                "--from",
                "json",
                "--to",
                "cane-base",
                "--on-unrepresentable",
                "split",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "convert",
                str(src),
                str(tmp_path / "c"),
                "--from",
                "json",
                "--to",
                "cane-full",
                "--context",
                "0",
            ]
        )
        == 2
    )


def test_cli_errors_never_exit_like_issues(tmp_path: Path) -> None:
    (tmp_path / "t.txt").write_bytes(b"caf\xe9")
    (tmp_path / "m.cane").write_text("NONE", encoding="utf-8")
    args = [
        "parse",
        str(tmp_path / "m.cane"),
        "--text",
        str(tmp_path / "t.txt"),
        "--variant",
        "base",
    ]
    assert main(args) == 2
    assert main([*args, "--encoding", "latin-1"]) == 0
    assert main([*args, "--encoding", "no-such-codec"]) == 2


def test_cli_warns_for_every_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    disco = [
        cane.Document(
            text="a b c", id=f"x{n}", entities=(Entity(spans=[(0, 1), (4, 5)], label="X"),)
        )
        for n in range(3)
    ]
    src = _jsonl(tmp_path / "d.jsonl", *disco)
    assert (
        main(
            [
                "convert",
                str(src),
                str(tmp_path / "c"),
                "--from",
                "json",
                "--to",
                "cane-base",
                "--on-unrepresentable",
                "skip",
            ]
        )
        == 0
    )
    err = capsys.readouterr().err
    assert all(f"document x{n}" in err for n in range(3))


def test_cli_brat_writes_nothing_on_error(tmp_path: Path) -> None:
    bad = cane.Document(text="ab", id="c", entities=(Entity(spans=[(0, 1)]),))
    src = _jsonl(tmp_path / "d.jsonl", *DRUGS, bad)
    assert main(["convert", str(src), str(tmp_path / "b"), "--from", "json", "--to", "brat"]) == 2
    assert not (tmp_path / "b").exists()


def test_cli_labels_are_trimmed(tmp_path: Path) -> None:
    (tmp_path / "t.txt").write_text("Aspirin helps.", encoding="utf-8")
    (tmp_path / "m.cane").write_text("`Aspirin` is a DRUG\n`helps` is a ADR", encoding="utf-8")
    assert (
        main(
            [
                "parse",
                str(tmp_path / "m.cane"),
                "--text",
                str(tmp_path / "t.txt"),
                "--variant",
                "base",
                "--labels",
                "DRUG, ADR",
                "-o",
                str(tmp_path / "o.jsonl"),
            ]
        )
        == 0
    )


def test_cli_on_collision(tmp_path: Path) -> None:
    code = cane.Document(
        text="use `x` now", id="c", entities=(Entity(spans=[(4, 7)], label="CODE"),)
    )
    src = _jsonl(tmp_path / "d.jsonl", code)
    args = ["convert", str(src), str(tmp_path / "c"), "--from", "json", "--to", "cane-base"]
    assert main(args) == 2
    assert main([*args, "--on-collision", "ignore"]) == 0


def test_cli_xml_structure_options(tmp_path: Path) -> None:
    (tmp_path / "g.xml").write_text(
        "<set><article><info>PMID:1</info><s>A <cons sem='X'>term</cons>.</s></article></set>",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "convert",
                str(tmp_path / "g.xml"),
                str(tmp_path / "o.jsonl"),
                "--from",
                "xml",
                "--to",
                "json",
                "--tag",
                "cons",
                "--type-attr",
                "sem",
                "--document-tag",
                "article",
                "--exclude-tags",
                "info",
                "--segment-tags",
                "s",
            ]
        )
        == 0
    )
    (d,) = cane.read_json(tmp_path / "o.jsonl")
    assert d.text == "A term." and d.metadata["info"] == "PMID:1"
    assert [s.kind for s in d.segments] == ["s"]


def test_whitespace_edged_spans_follow_the_strategy() -> None:
    d = doc("a b c", ("X", [(1, 3)]), ("Y", [(4, 5)]))  # " b" starts with a space
    with pytest.raises(cane.UnrepresentableError, match="whitespace"):
        cane.dumps(d, variant="base")
    with pytest.warns(cane.LossyConversionWarning, match="whitespace"):
        assert cane.dumps(d, variant="base", on_unrepresentable="hull").splitlines()[1:] == [
            "`c` is a Y"
        ]


# --- third review -------------------------------------------------------------------------


@pytest.mark.parametrize("doc_id", ["a:b", "with space", " edge "])
def test_brat_writes_back_what_it_can_read(tmp_path: Path, doc_id: str) -> None:
    d = cane.Document(
        text="Aspirin helps.", id=doc_id, entities=(Entity(spans=[(0, 7)], label="DRUG"),)
    )
    cane.write_brat([d], tmp_path)
    assert cane.read_brat(tmp_path) == [d]
    for unsafe in ("a/b", "..", ".", "a\\b"):
        with pytest.raises(cane.UnrepresentableError):
            cane.write_brat([cane.Document(text="x", id=unsafe)], tmp_path / "unsafe")


def test_cli_stdout_is_utf8_whatever_the_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    src = _jsonl(
        tmp_path / "d.jsonl",
        cane.Document(
            text="café au lait", id="c", entities=(Entity(spans=[(0, 4)], label="DRINK"),)
        ),
    )
    console = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr("sys.stdout", console)
    assert main(["convert", str(src), "-", "--from", "json", "--to", "xml"]) == 0
    written = console.buffer.getvalue().decode("utf-8")
    assert '<?xml version="1.0" encoding="UTF-8"?>' in written
    assert "<DRINK>café</DRINK> au lait" in written


def test_warnings_for_documents_without_id() -> None:
    d = cane.Document(text="a b", metadata={"x": 1}, entities=(Entity(spans=[(0, 1)], label="X"),))
    writers: list[Callable[[], object]] = [
        lambda: cane.format_brat(d),
        lambda: cane.format_conll(d),
        lambda: cane.format_xml(d),
        lambda: cane.dumps(d, variant="base"),
    ]
    for write in writers:
        with pytest.warns(cane.LossyConversionWarning) as record:
            write()
        assert str(record[0].message).startswith("document: ")


def test_cli_unknown_encoding_is_a_user_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "x.conll").write_text("a O\n", encoding="utf-8")
    assert (
        main(
            [
                "convert",
                str(tmp_path / "x.conll"),
                "-",
                "--from",
                "conll",
                "--to",
                "json",
                "--encoding",
                "no-such-codec",
            ]
        )
        == 2
    )
    assert "unknown encoding 'no-such-codec'" in capsys.readouterr().err


def test_cli_numbers_unnamed_documents_around_existing_ids(tmp_path: Path) -> None:
    docs = [
        cane.Document(text=d.text, entities=d.entities, id=i)
        for d, i in zip(DRUGS, (None, "1"), strict=True)
    ]
    src = _jsonl(tmp_path / "d.jsonl", *docs)
    assert (
        main(["convert", str(src), str(tmp_path / "c"), "--from", "json", "--to", "cane-base"]) == 0
    )
    assert sorted(p.name for p in (tmp_path / "c").iterdir()) == ["1.cane", "2.cane"]
    assert b"\r" not in (tmp_path / "c" / "2.cane").read_bytes()
