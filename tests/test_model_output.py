"""Real model output from the CANE paper's runs (tests/data/model-output, local only).

Skipped when absent. Each document carries its text, gold entities and the raw outputs of a
small and a large model in every CANE variant. The parse results are frozen in
``expected/``; after an intended behaviour change, regenerate them with
``CANE_UPDATE_SNAPSHOTS=1``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

import cane_format as cane
from tests.conftest import DATA

OUTPUTS = DATA / "model-output"
EXPECTED = OUTPUTS / "expected"
DIALECT = cane.ENGLISH  # the paper's prompts use the default literals

pytestmark = pytest.mark.skipif(
    not OUTPUTS.is_dir(), reason="real model output (tests/data/model-output) is not present"
)


def datasets() -> list[Path]:
    return sorted(OUTPUTS.glob("*.jsonl")) if OUTPUTS.is_dir() else []


def load(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def squash(s: str) -> str:
    return " ".join(s.split())


def parse(doc: dict[str, Any], variant: str, output: str) -> cane.ParseResult:
    return cane.loads(output, text=doc["text"], variant=variant, labels=doc["labels"])


def snapshot(result: cane.ParseResult) -> dict[str, Any]:
    return {
        "entities": [[e.label, [list(s) for s in e.spans]] for e in result.entities],
        "issues": [[i.line_no, i.kind.value] for i in result.issues],
    }


@pytest.mark.parametrize("path", datasets(), ids=lambda p: p.stem)
def test_gold_slices_back_to_its_text(path: Path) -> None:
    """Integrity gate: gold spans match their recorded text (up to whitespace runs)."""
    for doc in load(path):
        for g in doc["gold"]:
            sliced = " ".join(doc["text"][s:e] for s, e in g["spans"])
            assert squash(sliced) == squash(g["text"]), (doc["id"], g)


@pytest.mark.parametrize("path", datasets(), ids=lambda p: p.stem)
def test_grounded_entities_are_copied_from_the_output(path: Path) -> None:
    """Exact matching never produces a span whose text the model did not quote."""
    for doc in load(path):
        for model, runs in doc["outputs"].items():
            for variant, output in runs.items():
                result = parse(doc, variant, output)
                for e in result.entities:
                    for s in e.spans:
                        part = doc["text"][s.start : s.end]
                        words = r"\s+".join(re.escape(w) for w in part.split())
                        qo, qc = re.escape(DIALECT.quote_open), re.escape(DIALECT.quote_close)
                        quoted = re.compile(rf"{qo}\s*{words}\s*{qc}")
                        assert any(quoted.search(line) for line in output.splitlines()), (
                            doc["id"],
                            model,
                            variant,
                            part,
                        )


@pytest.mark.parametrize("path", datasets(), ids=lambda p: p.stem)
def test_parse_results_are_unchanged(path: Path) -> None:
    """Regression: the parse of every output matches the frozen result."""
    actual = {
        doc["id"]: {
            model: {variant: snapshot(parse(doc, variant, out)) for variant, out in runs.items()}
            for model, runs in doc["outputs"].items()
        }
        for doc in load(path)
    }
    expected_file = EXPECTED / f"{path.stem}.json"
    if os.environ.get("CANE_UPDATE_SNAPSHOTS"):
        EXPECTED.mkdir(exist_ok=True)
        expected_file.write_text(json.dumps(actual, indent=1, ensure_ascii=False) + "\n")
    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    for doc_id, runs in expected.items():
        for model, variants in runs.items():
            for variant, snap in variants.items():
                assert actual[doc_id][model][variant] == snap, (doc_id, model, variant)
