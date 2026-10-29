"""Parsing model output written in CANE back into a document (``cane.loads``).

Stages: output text -> records (no source text needed) -> candidate spans per part -> reading-
order grounding -> entities and issues.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal

from cane_format.dialect import ENGLISH, Dialect, Variant
from cane_format.errors import IssueKind, ParseError, ParseIssue
from cane_format.model import Document, Entity, Span

Match = Literal["exact", "normalized", "casefold"]

_SEARCH_LIMIT = 10_000


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseOptions:
    """How model output is parsed. Every default is strict. Recorded on each ``ParseResult``."""

    variant: Variant
    labels: frozenset[str] | None = None
    match: Match = "exact"
    anchor_fallback: bool = False
    strip_list_markers: bool = False
    handles: bool = False
    prefer_whole_words: bool = False
    dialect: Dialect = ENGLISH


@dataclass(frozen=True, slots=True)
class ParseResult:
    """The grounded document, everything that could not be grounded, and the settings used."""

    document: Document
    issues: tuple[ParseIssue, ...]
    settings: ParseOptions

    @property
    def entities(self) -> tuple[Entity, ...]:
        return self.document.entities

    @property
    def text(self) -> str:
        return self.document.text

    @property
    def ok(self) -> bool:
        """True if the output parsed without any issue."""
        return not self.issues

    def raise_for_errors(self) -> None:
        """Raise ``ParseError`` listing every issue, if there are any."""
        if self.issues:
            raise ParseError(self.issues)


def loads(
    output: str,
    *,
    text: str,
    variant: Variant | str | None = None,
    labels: Iterable[str] | None = None,
    match: Match = "exact",
    anchor_fallback: bool = False,
    strip_list_markers: bool = False,
    handles: bool = False,
    prefer_whole_words: bool = False,
    dialect: Dialect = ENGLISH,
    options: ParseOptions | None = None,
    id: str | None = None,
) -> ParseResult:
    """Parse CANE model output and ground every record in ``text``.

    Problems in the model output never raise: they are returned as ``result.issues``. ``NONE``
    (optionally after the header) means no entities; an empty output also gives no entities but
    is reported as ``empty_output``, because it usually means the generation failed.

    Args:
        output: The model's CANE output, exactly as received.
        text: The source text the model annotated.
        variant: The CANE variant the model was asked for; lines that break it are issues.
        labels: The allowed labels; an unknown label keeps the entity and adds an issue.
        match: ``"exact"``, ``"normalized"`` (Unicode NFC) or ``"casefold"``. Only this level is
            used. Whitespace runs always match any whitespace run.
        anchor_fallback: Ground the bare part when its anchor is not found.
        strip_list_markers: Remove leading list markers (``- ``, ``1. ``) from lines.
        handles: Records carry handles (``T1 `x` is a L``), which become entity IDs.
        prefer_whole_words: When a part could be placed at several occurrences, try those that
            neither start nor end inside a word (between two letters or digits) first, then
            the rest, each in reading order. Nothing is ever rejected. Matters mainly for
            Base and Disco, where no anchor picks the occurrence: in "against Northamptonshire
            at Northampton", `` `Northampton` `` then lands on the whole word.
        dialect: The surface vocabulary.
        options: All of the above as one ``ParseOptions``; excludes the other keywords.
        id: The ID of the resulting document (e.g. needed to write it as brat).
    """
    if options is None:
        if variant is None:
            raise TypeError("loads() needs variant= (or options=)")
        if match not in ("exact", "normalized", "casefold"):
            raise ValueError(f"unknown match level {match!r}")
        options = ParseOptions(
            variant=Variant(variant),
            labels=None if labels is None else frozenset(labels),
            match=match,
            anchor_fallback=anchor_fallback,
            strip_list_markers=strip_list_markers,
            handles=handles,
            prefer_whole_words=prefer_whole_words,
            dialect=dialect,
        )
    elif (
        variant,
        labels,
        match,
        anchor_fallback,
        strip_list_markers,
        handles,
        prefer_whole_words,
        dialect,
    ) != (None, None, "exact", False, False, False, False, ENGLISH):
        raise TypeError("pass either options= or individual keywords, not both")
    records, issues = _read_records(output, options)
    entities, grounding_issues = _Grounder(text, options).ground(records)
    issues.extend(grounding_issues)
    issues.sort(key=lambda i: i.line_no or 0)
    document = Document(text=text, entities=tuple(entities), id=id)
    return ParseResult(document, tuple(issues), options)


# --- stage 1: records ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Record:
    line: str
    line_no: int
    parts: tuple[str, ...]
    anchors: tuple[str, ...] | None
    label: str
    handle: str | None


def _read_records(output: str, options: ParseOptions) -> tuple[list[_Record], list[ParseIssue]]:
    d = options.dialect
    p = d._patterns
    lines = [(n, raw.strip()) for n, raw in enumerate(output.split(d.record_separator), 1)]
    lines = [(n, line) for n, line in lines if line]
    if not lines:
        return [], [ParseIssue(kind=IssueKind.EMPTY_OUTPUT, message="the output is empty")]
    if lines[0][1] == d.header:
        lines = lines[1:]
    if len(lines) == 1 and lines[0][1].upper() == d.empty.upper():
        return [], []
    records: list[_Record] = []
    issues: list[ParseIssue] = []

    def bad(kind: IssueKind, message: str, line: str, n: int) -> None:
        issues.append(ParseIssue(kind=kind, message=message, line=line, line_no=n))

    for n, line in lines:
        body = line
        if options.strip_list_markers:
            marker = p.list_marker.match(body)
            if marker:
                body = body[marker.end() :]
        m = p.record.fullmatch(body)
        if m is None:
            bad(IssueKind.MALFORMED_LINE, "not a CANE record", line, n)
            continue
        handle, label = m["handle"], m["label"]
        if handle is not None and not options.handles:
            bad(IssueKind.MALFORMED_LINE, f"unexpected handle {handle!r}", line, n)
            continue
        if handle is None and options.handles:
            bad(IssueKind.MALFORMED_LINE, "record has no handle", line, n)
            continue
        if m["article"] is None and label in p.articles:
            bad(IssueKind.MALFORMED_LINE, "record has no label", line, n)
            continue
        parts = _split(m["parts"], p.part_split, d)
        anchors = None if m["anchors"] is None else _split(m["anchors"], p.anchor_split, d)
        variant = options.variant
        if not all(parts) or (anchors is not None and not all(anchors)):
            bad(IssueKind.MALFORMED_LINE, "empty part or anchor", line, n)
        elif len(parts) > 1 and not variant.multi_part:
            bad(IssueKind.MALFORMED_LINE, f"several parts in CANE-{variant.value}", line, n)
        elif variant.anchored and anchors is None:
            bad(IssueKind.MALFORMED_LINE, f"missing anchor in CANE-{variant.value}", line, n)
        elif not variant.anchored and anchors is not None:
            bad(IssueKind.MALFORMED_LINE, f"unexpected anchor in CANE-{variant.value}", line, n)
        elif anchors is not None and len(anchors) != len(parts):
            bad(
                IssueKind.PART_COUNT_MISMATCH,
                f"{len(parts)} part(s) but {len(anchors)} anchor(s)",
                line,
                n,
            )
        else:
            records.append(_Record(line, n, parts, anchors, label, handle))
    return records, issues


def _split(region: str, separator: re.Pattern[str], d: Dialect) -> tuple[str, ...]:
    inner = region[len(d.quote_open) : len(region) - len(d.quote_close)]
    return tuple(piece.strip() for piece in separator.split(inner))


# --- stage 2: candidates ------------------------------------------------------------------


class _Searcher:
    """Finds whitespace-flexible occurrences of strings, at one matching level.

    For ``normalized`` and ``casefold`` the text is normalised chunk by chunk (a chunk is a
    starter plus its combining marks), and matches are mapped back to original offsets; a match
    that starts or ends inside a chunk is discarded.
    """

    def __init__(self, text: str, level: Match) -> None:
        self.level = level
        if level == "exact":
            self.text = text
            self.to_orig: dict[int, int] | None = None
            return
        out: list[str] = []
        to_orig = {0: 0}
        size = 0
        for start, chunk in _chunks(text):
            to_orig[size] = start
            piece = self.norm(chunk)
            out.append(piece)
            size += len(piece)
        to_orig[size] = len(text)
        self.text = "".join(out)
        self.to_orig = to_orig

    def norm(self, s: str) -> str:
        if self.level == "exact":
            return s
        s = unicodedata.normalize("NFC", s)
        if self.level == "casefold":
            s = unicodedata.normalize("NFC", s.casefold())
        return s

    def pattern(self, s: str) -> str:
        return r"\s+".join(re.escape(self.norm(token)) for token in s.split())

    def find(self, pattern: str, group: str = "x") -> list[Span]:
        """Every occurrence of ``pattern`` (overlapping), as spans of its group ``group``."""
        found: list[Span] = []
        regex = re.compile(pattern)
        # One search per match start (overlapping matches); a lookahead around the pattern
        # would find the same matches but defeat the engine's literal-prefix scan.
        m = regex.search(self.text)
        while m is not None:
            start, end = m.start(group), m.end(group)
            m = regex.search(self.text, m.start() + 1)
            if self.to_orig is not None:
                if start not in self.to_orig or end not in self.to_orig:
                    continue
                start, end = self.to_orig[start], self.to_orig[end]
            if start < end and (not found or found[-1] != (start, end)):
                found.append(Span(start, end))
        return found


def _chunks(text: str) -> Iterable[tuple[int, str]]:
    start = 0
    for i in range(1, len(text) + 1):
        if i == len(text) or _starts_chunk(text[i]):
            yield start, text[start:i]
            start = i


def _starts_chunk(ch: str) -> bool:
    # Hangul medial vowels and final consonants compose with the preceding jamo.
    return unicodedata.combining(ch) == 0 and not 0x1160 <= ord(ch) <= 0x11FF


def _anchored(searcher: _Searcher, part: str, anchor: str) -> list[Span] | None:
    """Candidates for ``part`` located through ``anchor``; None if the anchor has no part."""
    part_pattern = searcher.pattern(part)
    in_anchor = [
        (m.start("x"), m.end("x"))
        for m in re.finditer(f"(?=(?P<x>{part_pattern}))", searcher.norm(anchor))
    ]
    if not in_anchor:
        return None
    norm_anchor = searcher.norm(anchor)
    candidates: dict[Span, None] = {}
    for s, e in in_anchor:
        left, right = norm_anchor[:s], norm_anchor[e:]
        pattern = (
            _side(searcher, left, before=True)
            + f"(?P<x>{part_pattern})"
            + _side(searcher, right, before=False)
        )
        candidates.update(dict.fromkeys(searcher.find(pattern)))
    return list(candidates)


def _side(searcher: _Searcher, side: str, *, before: bool) -> str:
    if not side.strip():
        return ""
    words = r"\s+".join(re.escape(token) for token in side.split())
    if before:
        return words + (r"\s+" if side[-1].isspace() else "")
    return (r"\s+" if side[0].isspace() else "") + words


def _inside_word(text: str, span: Span) -> bool:
    """Whether ``span`` starts or ends between two letters or digits of ``text``."""
    start, end = span
    return (start > 0 and text[start - 1].isalnum() and text[start].isalnum()) or (
        end < len(text) and text[end].isalnum() and text[end - 1].isalnum()
    )


# --- stage 3: grounding -------------------------------------------------------------------


class Echo:
    """Grounds records one at a time exactly as ``loads`` with ``options`` would, keeping its
    state between records, so that ``dumps`` can check that what it writes parses back."""

    def __init__(self, text: str, options: ParseOptions) -> None:
        self._options = replace(options, handles=False)  # records are checked without handles
        self._grounder = _Grounder(text, self._options)

    def place(self, line: str) -> tuple[Entity | None, list[ParseIssue]]:
        """The entity ``line`` grounds as (None if it does not), and the issues it raises."""
        records, issues = _read_records(line, self._options)
        entities, grounding_issues = self._grounder.ground(records)
        return (entities[0] if entities else None), issues + grounding_issues


class _Grounder:
    def __init__(self, text: str, options: ParseOptions) -> None:
        self.options = options
        self.text = text
        self.searcher = _Searcher(text, options.match)
        self.produced: set[tuple[str, tuple[Span, ...]]] = set()
        self.handles: set[str] = set()
        self.cursor = 0
        self._bare: dict[str, list[Span]] = {}
        self._anchored: dict[tuple[str, str], list[Span] | None] = {}

    def bare(self, part: str) -> list[Span]:
        if part not in self._bare:
            self._bare[part] = self.searcher.find(f"(?P<x>{self.searcher.pattern(part)})")
        return self._bare[part]

    def anchored(self, part: str, anchor: str) -> list[Span] | None:
        if (part, anchor) not in self._anchored:
            self._anchored[part, anchor] = _anchored(self.searcher, part, anchor)
        return self._anchored[part, anchor]

    def ground(self, records: list[_Record]) -> tuple[list[Entity], list[ParseIssue]]:
        entities: list[Entity] = []
        issues: list[ParseIssue] = []
        for record in records:
            entity, record_issues = self._ground_record(record)
            issues.extend(record_issues)
            if entity is not None:
                entities.append(entity)
                self.produced.add((record.label, entity.spans))
                self.cursor = entity.start
        return entities, issues

    def _ground_record(self, r: _Record) -> tuple[Entity | None, list[ParseIssue]]:
        def issue(kind: IssueKind, message: str, cands: Iterable[Span] = ()) -> ParseIssue:
            return ParseIssue(
                kind=kind,
                message=message,
                line=r.line,
                line_no=r.line_no,
                candidates=tuple(cands),
            )

        per_part: list[list[Span]] = []
        unanchored = False
        for i, part in enumerate(r.parts):
            bare = self.bare(part)
            if r.anchors is None:
                cands = bare
            else:
                anchored = self.anchored(part, r.anchors[i])
                cands = anchored or []
                if not cands:
                    if not (self.options.anchor_fallback and bare):
                        where = "does not contain" if anchored is None else "was not found for"
                        return None, [
                            issue(
                                IssueKind.ANCHOR_NOT_FOUND,
                                f"anchor {r.anchors[i]!r} {where} part {part!r}",
                                bare,
                            )
                        ]
                    cands, unanchored = bare, True
            if not cands:
                return None, [issue(IssueKind.NOT_FOUND, f"part {part!r} not found in the text")]
            per_part.append(cands)

        spans, outcome = self._choose(r.label, per_part)
        flat = [s for cands in per_part for s in cands]
        if spans is None:
            if outcome == "duplicate":
                return None, [
                    issue(
                        IssueKind.DUPLICATE,
                        "every placement repeats an earlier entity with the same label",
                        flat,
                    )
                ]
            return None, [issue(IssueKind.NOT_FOUND, outcome, flat)]

        metadata: dict[str, Any] = {}
        if self.options.match != "exact":
            metadata["match"] = self.options.match
        if unanchored:
            metadata["unanchored"] = True
        issues: list[ParseIssue] = []
        entity_id = r.handle
        if entity_id is not None and entity_id in self.handles:
            issues.append(issue(IssueKind.MALFORMED_LINE, f"handle {entity_id} used twice"))
            entity_id = None
        if entity_id is not None:
            self.handles.add(entity_id)
        try:
            entity = Entity(spans=spans, label=r.label, id=entity_id, metadata=metadata)
        except ValueError as err:
            return None, [issue(IssueKind.INVALID_SPAN, str(err), spans)]
        labels = self.options.labels
        if labels is not None and r.label not in labels:
            issues.append(issue(IssueKind.INVALID_LABEL, f"label {r.label!r} is not allowed"))
        return entity, issues

    def _choose(
        self, label: str, per_part: list[list[Span]]
    ) -> tuple[tuple[Span, ...] | None, str]:
        """Reading order: per part, the earliest occurrence at or after the cursor first.

        Placements that keep the parts in their written order are tried first; only if there
        is none may the parts land in any order. With ``prefer_whole_words``, occurrences inside
        a word go after all others.
        """

        def key(s: Span) -> tuple[bool, bool, int, int]:
            inside = self.options.prefer_whole_words and _inside_word(self.text, s)
            return (inside, s.start < self.cursor, s.start, s.end)

        ordered = [sorted(c, key=key) for c in per_part]
        budget = _SEARCH_LIMIT
        saw_complete = False

        def search(i: int, chosen: list[Span], in_order: bool) -> tuple[Span, ...] | None:
            nonlocal budget, saw_complete
            if i == len(ordered):
                saw_complete = True
                spans = tuple(sorted(chosen))
                return None if (label, spans) in self.produced else spans
            for cand in ordered[i]:
                budget -= 1
                if budget < 0:
                    return None
                if in_order and chosen and cand.start < chosen[-1].end:
                    continue
                if any(cand.start < c.end and c.start < cand.end for c in chosen):
                    continue
                found = search(i + 1, [*chosen, cand], in_order)
                if found is not None:
                    return found
            return None

        spans = search(0, [], in_order=True)
        if spans is None and len(ordered) > 1 and budget >= 0:
            spans = search(0, [], in_order=False)
        if spans is not None:
            return spans, ""
        if budget < 0:
            return None, "search limit reached before a placement was found"
        if saw_complete:
            return None, "duplicate"
        return None, "the parts cannot be placed without overlapping each other"
