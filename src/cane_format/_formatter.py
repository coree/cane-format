"""Writing documents as CANE (``cane.dumps``)."""

from __future__ import annotations

import re
import warnings
from typing import Literal

from cane_format._output import check, document_name
from cane_format._parser import Echo, ParseOptions
from cane_format.dialect import ENGLISH, Dialect, Variant
from cane_format.errors import IssueKind, LossyConversionWarning, UnrepresentableError
from cane_format.model import Document, Entity, Span

_WHITESPACE = re.compile(r"\s+")

OnUnrepresentable = Literal["raise", "skip", "first", "hull"]
OnMismatch = Literal["warn", "raise", "ignore"]


def dumps(
    doc: Document,
    *,
    variant: Variant | str,
    context: int = 1,
    handles: bool = False,
    on_unrepresentable: OnUnrepresentable = "raise",
    on_mismatch: OnMismatch = "warn",
    parse_options: ParseOptions | None = None,
    lossy: Literal["warn", "ignore"] = "warn",
    dialect: Dialect = ENGLISH,
) -> str:
    """Write a document's entities as CANE text, e.g. for a few-shot example.

    Entities are written in reading order: by start, outer before nested, then by label and ID.
    Every record is parsed back as ``loads`` with ``parse_options`` would parse it. A record
    that would not ground on its own spans (a repeated string without an anchor, an anchor of
    ``context`` units that occurs more than once, a part that reads as two) is still written
    as is and handled by ``on_mismatch``. Two entities that would give the same record are
    written once, with the lossy warning.

    Args:
        doc: The document to write.
        variant: ``"base"``, ``"disco"``, ``"context"`` or ``"full"``.
        context: Anchor size in whitespace-separated units on each side (anchored variants).
        handles: Prefix each record with a handle ``T1``, ``T2``, … in output order.
        on_unrepresentable: What to do with an entity the variant cannot express (no label, a
            label that is not one token, or discontinuous in Base/Context): ``"raise"``, or
            ``"skip"``, ``"first"`` (first span only) or ``"hull"`` (one span covering the
            gaps), which warn. Entities with label problems are skipped by any of these.
        on_mismatch: A record that does not parse back on its own spans: ``"warn"`` (one
            ``LossyConversionWarning`` naming each), ``"raise"`` (``UnrepresentableError``),
            or ``"ignore"`` (the check is not run).
        parse_options: How the output will be parsed (``match``, ``prefer_whole_words``,
            ``anchor_fallback``, …); by default ``loads``' defaults. Variant and dialect must
            be the ones given here.
        lossy: ``"warn"`` once about information CANE cannot carry, or ``"ignore"``.
        dialect: The surface vocabulary.

    Raises:
        UnrepresentableError: An entity cannot be written and no strategy allows dropping it,
            or a record does not parse back and ``on_mismatch="raise"``.
    """
    variant = Variant(variant)
    check("on_unrepresentable", on_unrepresentable, ("raise", "skip", "first", "hull"))
    check("on_mismatch", on_mismatch, ("warn", "raise", "ignore"))
    check("lossy", lossy, ("warn", "ignore"))
    if context < 1:
        raise ValueError("context must be at least 1")
    if parse_options is None:
        parse_options = ParseOptions(variant=variant, dialect=dialect)
    elif (parse_options.variant, parse_options.dialect) != (variant, dialect):
        raise ValueError("parse_options must have the variant and dialect given to dumps")
    echo = None if on_mismatch == "ignore" else Echo(doc.text, parse_options)
    dropped: list[str] = []
    mismatched: list[str] = []
    records: list[str] = []
    written: dict[tuple[str, tuple[Span, ...]], str | None] = {}
    ordered = sorted(doc.entities, key=lambda e: (e.start, -e.end, e.label or "", e.id or ""))
    for entity in ordered:
        spans = _writable_spans(doc.text, entity, variant, on_unrepresentable, dropped)
        if spans is None:
            continue
        label = entity.label or ""  # _writable_spans has refused entities without a label
        if (label, spans) in written:
            twin = written[label, spans]
            dropped.append(f"entity {entity.id} (written once: same record as entity {twin})")
            continue
        written[label, spans] = entity.id
        record = _record(doc.text, label, spans, variant, context, dialect)
        problem = None if echo is None else _mismatch(echo, record, label, spans)
        if problem is not None:
            if on_mismatch == "raise":
                raise UnrepresentableError(f"entity {entity.id} {problem}")
            mismatched.append(f"entity {entity.id} ({problem})")
        if handles:
            record = f"{dialect.handle_prefix}{len(records) + 1} {record}"
        records.append(record)
    if mismatched:
        warnings.warn(
            f"{document_name(doc)}: records that do not parse back on their own spans: "
            + "; ".join(mismatched),
            LossyConversionWarning,
            stacklevel=2,
        )
    if lossy == "warn":
        _warn_lossy(doc, dropped)
    if not records:
        return dialect.empty
    return dialect.record_separator.join([dialect.header, *records])


def _writable_spans(
    text: str, entity: Entity, variant: Variant, strategy: OnUnrepresentable, dropped: list[str]
) -> tuple[Span, ...] | None:
    problem = None
    repairable = False  # by first/hull; nothing repairs a label or whitespace-edged text
    edged = [p for p in entity.parts(text) if p != p.strip()]
    if entity.label is None:
        problem = "has no label"
    elif not entity.label or _WHITESPACE.search(entity.label):
        problem = f"has the label {entity.label!r}, which is not one token"
    elif edged:
        problem = f"has text {edged[0]!r} starting or ending with whitespace"
    elif len(entity.spans) > 1 and not variant.multi_part:
        problem = f"is discontinuous, which CANE-{variant.value.title()} cannot express"
        repairable = True
    if problem is None:
        return entity.spans
    if strategy == "raise":
        raise UnrepresentableError(f"entity {entity.id} {problem}")
    if strategy == "skip" or not repairable:
        dropped.append(f"entity {entity.id} (skipped: {problem})")
        return None
    dropped.append(f"entity {entity.id} ({strategy}: {problem})")
    return (entity.spans[0],) if strategy == "first" else (entity.hull,)


def _mismatch(echo: Echo, record: str, label: str, spans: tuple[Span, ...]) -> str | None:
    """Why ``record`` would not parse back on ``label`` and ``spans``; None if it would."""
    placed, issues = echo.place(record)
    if placed is not None:
        if placed.spans != spans:
            return f"parses back elsewhere, at offset {placed.start}"
        if placed.label != label:
            return f"parses back with the label {placed.label!r}"
        return None
    problem = next(i for i in issues if i.kind is not IssueKind.INVALID_LABEL)
    return f"does not parse back: {problem.kind.value}: {problem.message}"


def _record(
    text: str, label: str, spans: tuple[Span, ...], variant: Variant, context: int, d: Dialect
) -> str:
    parts = [_content(text[s.start : s.end]) for s in spans]
    copula = d.copula_plural if len(parts) > 1 else d.copula_singular
    record = f" {d.part_connective} ".join(_quote(p, d) for p in parts)
    record += f" {copula} {d.articles[0]} {label}"
    if variant.anchored:
        anchors = [_content(_anchor_text(text, s, context)) for s in spans]
        record += f" {d.anchor_intro} " + f" {d.anchor_connective} ".join(
            _quote(a, d) for a in anchors
        )
    return record


def _content(raw: str) -> str:
    if raw != raw.strip():
        raise UnrepresentableError(
            f"span text {raw!r} starts or ends with whitespace, which CANE cannot carry"
        )
    return _WHITESPACE.sub(" ", raw)


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
        warnings.warn(
            f"{document_name(doc)}: CANE cannot carry: " + "; ".join(lost),
            LossyConversionWarning,
            stacklevel=3,
        )
