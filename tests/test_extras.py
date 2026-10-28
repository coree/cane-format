from __future__ import annotations

import json
from pathlib import Path

import pytest

import cane_format as cane
from cane_format.cli import main
from tests.conftest import doc
from tests.test_brat import ANN, TEXT
from tests.test_writer import AMOX, COMPLEX_DOC

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


def test_prompt_layout_and_examples_match_the_writer() -> None:
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
