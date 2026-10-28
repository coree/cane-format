"""Real documents from public corpora (tests/data, kept out of git). Skipped when absent."""

from __future__ import annotations

import random
import warnings
from collections import Counter
from pathlib import Path

import pytest

import cane_format as cane
from tests.conftest import DATA, requires_data

pytestmark = requires_data


def corpora() -> list[Path]:
    return sorted((DATA / "brat").iterdir()) if (DATA / "brat").is_dir() else []


def all_docs() -> list[cane.Document]:
    return [d for corpus in corpora() for d in cane.read_brat(corpus)]


@pytest.mark.parametrize("corpus", corpora(), ids=lambda p: p.name)
def test_reads_and_round_trips(corpus: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        docs = cane.read_brat(corpus)
        for d in docs:
            back = cane.parse_brat(d.text, cane.format_brat(d), id=d.id)
            assert back.text == d.text and Counter(back.entities) == Counter(d.entities)
            assert Counter(back.relations) == Counter(d.relations)

            def content(x: cane.Document) -> dict[str | None, object]:
                items: tuple[cane.Entity | cane.Relation, ...] = (*x.entities, *x.relations)
                return {
                    e.id: (getattr(e, "concepts", ()), dict(e.attributes), dict(e.metadata))
                    for e in items
                }

            assert content(back) == content(d)


def test_skewed_files_raise() -> None:
    for txt in sorted((DATA / "invalid" / "bconv-skewed").glob("*.txt")):
        with pytest.raises(cane.IntegrityError):
            cane.read_brat(txt)


def _cane_round_trip(variant: str, order: str) -> tuple[int, int, int]:
    """(gold entities, exactly recovered, issues) over all real documents."""
    gold_n = exact = issues = 0
    for d in all_docs():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", cane.LossyConversionWarning)
            out = cane.dumps(d, variant=variant, on_unrepresentable="skip")
        if out == "NONE":
            continue
        header, *lines = out.split("\n")
        if order == "shuffled":
            random.Random(0).shuffle(lines)
        elif order == "by_label":
            lines.sort(key=lambda line: line.rsplit(" a ", 1)[-1].split()[0])
        gold = Counter(
            e for e in d.entities if len(e.spans) == 1 or cane.Variant(variant).multi_part
        )
        result = cane.loads("\n".join([header, *lines]), text=d.text, variant=variant)
        gold_n += sum(gold.values())
        exact += sum((gold & Counter(result.entities)).values())
        issues += len(result.issues)
    return gold_n, exact, issues


@pytest.mark.parametrize("variant", ["context", "full"])
@pytest.mark.parametrize("order", ["reading", "by_label"])
def test_anchored_variants_recover_everything(variant: str, order: str) -> None:
    gold, exact, issues = _cane_round_trip(variant, order)
    assert exact == gold and issues == 0


@pytest.mark.parametrize("variant", ["base", "disco"])
def test_unanchored_variants_in_reading_order(variant: str) -> None:
    # Misses are genuine ambiguity: unannotated occurrences of the same string (CRAFT).
    gold, exact, issues = _cane_round_trip(variant, "reading")
    assert exact / gold > 0.98 and issues == 0


@pytest.mark.parametrize("corpus", corpora(), ids=lambda p: p.name)
def test_json_round_trip(corpus: Path) -> None:
    from tests.test_json import same

    for d in cane.read_brat(corpus):
        back = cane.parse_json(cane.format_json(d))
        assert same(back, d)
        assert cane.format_brat(back) == cane.format_brat(d)


CONLL_FILES = [
    ("bconv", "bioes", "#"),
    ("conll-2002", "bio", None),
    ("wnut-17", "bio", None),
]


def conll_files() -> list[tuple[Path, str, str | None]]:
    return [
        (f, scheme, comment)
        for folder, scheme, comment in CONLL_FILES
        for f in sorted((DATA / "conll" / folder).glob("*"))
        if (DATA / "conll").is_dir() and f.name not in ("LICENSE", "README")
    ]


@pytest.mark.parametrize(("path", "scheme", "comment"), conll_files(), ids=lambda x: str(x))
def test_conll_files_round_trip(path: Path, scheme: str, comment: str | None) -> None:
    docs = cane.read_conll(path, scheme=scheme, comment_prefix=comment)  # type: ignore[arg-type]
    assert docs and all(d.metadata["text_reconstructed"] for d in docs)
    out = "".join(cane.format_conll(d, scheme=scheme) for d in docs)  # type: ignore[arg-type]
    original = [line.split() for line in path.read_text(encoding="utf-8").splitlines()]
    assert [c for c in original if c] == [line.split() for line in out.splitlines() if line]
    again = cane.parse_conll(out, scheme=scheme, comment_prefix=comment)  # type: ignore[arg-type]
    assert [d.entities for d in again] == [d.entities for d in docs]


def _norm(x: object) -> object:
    if isinstance(x, dict):
        return {
            k: _norm(v)
            for k, v in x.items()
            if v not in ([], {}, "") or k in ("text", "id", "offset")
        }
    if isinstance(x, list):
        return [_norm(v) for v in x]
    return x


def bioc_files() -> list[Path]:
    return sorted((DATA / "bioc").rglob("*.json")) if (DATA / "bioc").is_dir() else []


@pytest.mark.parametrize("path", bioc_files(), ids=lambda p: p.name)
def test_bioc_files_round_trip_identically(path: Path) -> None:
    import json

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        docs = cane.read_bioc_json(path, concept_keys=("identifier", "cui"))
    original = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(original, list):
        original = original[0]
    if "PubTator3" in original:
        original = {"documents": original["PubTator3"]}
    ours = json.loads(cane.format_bioc_json(docs))
    assert _norm(ours["documents"]) == _norm(original["documents"])
