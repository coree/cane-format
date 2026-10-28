"""Writing documents as CANE (``cane.dumps``)."""

from __future__ import annotations

import re
import warnings
from typing import Literal

from cane_format.dialect import ENGLISH, Dialect, Variant
from cane_format.errors import LossyConversionWarning, UnrepresentableError
from cane_format.model import Document, Entity, Span

_WHITESPACE = re.compile(r"\s+")

OnUnrepresentable = Literal["raise", "skip", "first", "hull"]


def dumps(
    doc: Document,
    *,
    variant: Variant | str,
    context: int = 1,
    handles: bool = False,
    on_unrepresentable: OnUnrepresentable = "raise",
    on_collision: Literal["raise", "ignore"] = "raise",
    lossy: Literal["warn", "ignore"] = "warn",
    dialect: Dialect = ENGLISH,
) -> str:
    """Write a document's entities as CANE text, e.g. for a few-shot example.

    Entities are written in reading order: by start, outer before nested, then by label and ID.

    Args:
        doc: The document to write.
        variant: ``"base"``, ``"disco"``, ``"context"`` or ``"full"``.
        context: Anchor size in whitespace-separated units on each side (anchored variants).
        handles: Prefix each record with a handle ``T1``, ``T2``, … in output order.
        on_unrepresentable: What to do with an entity the variant cannot express (no label, a
            label that is not one token, or discontinuous in Base/Context): ``"raise"``, or
            ``"skip"``, ``"first"`` (first span only) or ``"hull"`` (one span covering the
            gaps), which warn. Entities with label problems are skipped by any of these.
        on_collision: ``"raise"`` if a part or anchor contains a delimiter, or ``"ignore"``.
        lossy: ``"warn"`` once about information CANE cannot carry, or ``"ignore"``.
        dialect: The surface vocabulary.

    Raises:
        UnrepresentableError: An entity cannot be written and no strategy allows dropping it.
    """
    variant = Variant(variant)
    if context < 1:
        raise ValueError("context must be at least 1")
    dropped: list[str] = []
    records: list[str] = []
    ordered = sorted(doc.entities, key=lambda e: (e.start, -e.end, e.label or "", e.id or ""))
    for entity in ordered:
        spans = _writable_spans(entity, variant, on_unrepresentable, dropped)
        if spans is None:
            continue
        record = _record(doc.text, entity.label, spans, variant, context, dialect, on_collision)
        if handles:
            record = f"{dialect.handle_prefix}{len(records) + 1} {record}"
        records.append(record)
    if lossy == "warn":
        _warn_lossy(doc, dropped)
    if not records:
        return dialect.empty
    return dialect.record_separator.join([dialect.header, *records])


def _writable_spans(
    entity: Entity, variant: Variant, strategy: OnUnrepresentable, dropped: list[str]
) -> tuple[Span, ...] | None:
    problem = None
    if entity.label is None:
        problem = "has no label"
    elif not entity.label or _WHITESPACE.search(entity.label):
        problem = f"has the label {entity.label!r}, which is not one token"
    elif len(entity.spans) > 1 and not variant.multi_part:
        problem = f"is discontinuous, which CANE-{variant.value.title()} cannot express"
    if problem is None:
        return entity.spans
    if strategy == "raise":
        raise UnrepresentableError(f"entity {entity.id} {problem}")
    if strategy == "skip" or problem.startswith("has"):  # no strategy can repair a label
        dropped.append(f"entity {entity.id} (skipped: {problem})")
        return None
    dropped.append(f"entity {entity.id} ({strategy}: {problem})")
    return (entity.spans[0],) if strategy == "first" else (entity.hull,)


def _record(
    text: str,
    label: str | None,
    spans: tuple[Span, ...],
    variant: Variant,
    context: int,
    dialect: Dialect,
    on_collision: str,
) -> str:
    parts = [_content(text[s.start : s.end], text, dialect, on_collision) for s in spans]
    copula = dialect.copula_plural if len(parts) > 1 else dialect.copula_singular
    record = (
        f" {dialect.part_connective} ".join(_quote(p, dialect) for p in parts)
        + f" {copula} {dialect.articles[0]} {label}"
    )
    if variant.anchored:
        anchors = [
            _content(_anchor_text(text, s, context), text, dialect, on_collision) for s in spans
        ]
        record += f" {dialect.anchor_intro} " + f" {dialect.anchor_connective} ".join(
            _quote(a, dialect) for a in anchors
        )
    return record


def _content(raw: str, text: str, dialect: Dialect, on_collision: str) -> str:
    if raw != raw.strip():
        raise UnrepresentableError(
            f"span text {raw!r} starts or ends with whitespace, which CANE cannot carry"
        )
    content = _WHITESPACE.sub(" ", raw)
    if on_collision == "raise" and (
        dialect.quote_open in content or dialect.quote_close in content
    ):
        raise UnrepresentableError(
            f"{content!r} contains a CANE delimiter; choose a dialect with other quotes"
        )
    return content


def _quote(content: str, dialect: Dialect) -> str:
    return f"{dialect.quote_open}{content}{dialect.quote_close}"


def _anchor_text(text: str, span: Span, n: int) -> str:
    """The span plus ``n`` whitespace-separated units on each side.

    The rest of a unit the span starts or ends inside counts as one unit (``here`` for a span
    ``inafter`` in ``hereinafter``; the comma in ``amoxicillin,``).
    """
    left = span.start
    for _ in range(n):
        while left > 0 and text[left - 1].isspace():
            left -= 1
        if left == 0:
            break
        while left > 0 and not text[left - 1].isspace():
            left -= 1
    right = span.end
    for _ in range(n):
        while right < len(text) and text[right].isspace():
            right += 1
        if right == len(text):
            break
        while right < len(text) and not text[right].isspace():
            right += 1
    return text[left:right].strip()


def _warn_lossy(doc: Document, dropped: list[str]) -> None:
    counts = {
        "relations": len(doc.relations),
        "segments": len(doc.segments),
        "concepts": sum(len(e.concepts) for e in doc.entities),
        "attributes": sum(len(e.attributes) for e in doc.entities),
        "entity metadata": sum(1 for e in doc.entities if e.metadata),
        "document metadata": 1 if doc.metadata else 0,
    }
    lost = [f"{n} {what}" for what, n in counts.items() if n] + dropped
    if lost:
        warnings.warn("CANE cannot carry: " + "; ".join(lost), LossyConversionWarning, stacklevel=3)
