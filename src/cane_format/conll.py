"""CoNLL-style token/tag files (IOB tagging): one token per line, tag in the last column.

Blank lines separate sentences; a ``-DOCSTART-`` line starts a new document (without any, every
sentence is a document). CoNLL stores tokens, not text: the text is rebuilt by joining tokens with
spaces and sentences with newlines, and marked with ``metadata["text_reconstructed"] = True``.
Token and sentence segments keep the tokens, so CoNLL -> CoNLL reproduces the input.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable, Iterable, Iterator, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Literal

from cane_format.errors import CaneFormatError, LossyConversionWarning, UnrepresentableError
from cane_format.model import Document, Entity, Segment, Span

Scheme = Literal["bio", "iob1", "bioes", "bilou"]
Alignment = Literal["strict", "expand", "contract"]
OnConflict = Literal["raise", "outermost", "innermost", "skip"]
OnUnrepresentable = Literal["raise", "first", "hull", "split", "skip"]
Tokenizer = Callable[[str], Iterable[tuple[int, int]]]

RECONSTRUCTED = "text_reconstructed"
DOCSTART_KEY = "conll_docstart"
COMMENTS_KEY = "conll_comments"
COLUMNS_KEY = "columns"
_DOCSTART = "-DOCSTART-"
_TOKEN = re.compile(r"\w+|[^\w\s]")
_WHITESPACE = re.compile(r"\s")


def regex_tokenizer(text: str) -> Iterator[tuple[int, int]]:
    """The default tokeniser: runs of word characters, and single other characters."""
    for m in _TOKEN.finditer(text):
        yield m.start(), m.end()


# --- reading ------------------------------------------------------------------------------


def read_conll(
    path: str | PathLike[str],
    *,
    scheme: Scheme = "bio",
    repair: bool = False,
    text: str | None = None,
    encoding: str = "utf-8",
    comment_prefix: str | None = None,
) -> list[Document]:
    """Read a CoNLL file. See ``parse_conll``; ``encoding`` is the file's text encoding."""
    return list(
        iter_conll(
            path,
            scheme=scheme,
            repair=repair,
            text=text,
            encoding=encoding,
            comment_prefix=comment_prefix,
        )
    )


def iter_conll(
    path: str | PathLike[str],
    *,
    scheme: Scheme = "bio",
    repair: bool = False,
    text: str | None = None,
    encoding: str = "utf-8",
    comment_prefix: str | None = None,
) -> Iterator[Document]:
    """Like ``read_conll``, yielding documents one at a time."""
    path = Path(path)
    content = path.read_text(encoding=encoding)
    yield from _parse(content, scheme, repair, text, comment_prefix, prefix=f"{path.stem}-")


def parse_conll(
    content: str,
    *,
    scheme: Scheme = "bio",
    repair: bool = False,
    text: str | None = None,
    comment_prefix: str | None = None,
) -> list[Document]:
    """Build documents from CoNLL content.

    Args:
        content: The file content.
        scheme: The tag scheme: ``"bio"`` (IOB2), ``"iob1"``, ``"bioes"`` or ``"bilou"``.
        repair: Accept invalid tag sequences (e.g. ``I-X`` after ``O``) by starting a new entity
            there, instead of raising.
        text: The true raw text, if known. Tokens are aligned onto it (only whitespace may lie
            between them) and offsets refer to it. Only for content with exactly one document.
        comment_prefix: Treat lines starting with this prefix (e.g. ``"#"``) as comments. A
            comment ``doc_id = X`` or ``newdoc id = X`` starts a new document with ID ``X``; other
            comments are kept in ``metadata["conll_comments"]``. Off by default, since ``#``
            can also be a token.
    """
    return list(_parse(content, scheme, repair, text, comment_prefix, prefix=""))


def _parse(
    content: str,
    scheme: Scheme,
    repair: bool,
    text: str | None,
    comment_prefix: str | None,
    prefix: str,
) -> Iterator[Document]:
    blocks = list(_documents(content, comment_prefix))
    if text is not None and len(blocks) != 1:
        raise CaneFormatError(f"text= needs exactly one document, found {len(blocks)}")
    for n, block in enumerate(blocks, 1):
        doc = _build(block, scheme, repair, block.doc_id or f"{prefix}{n}")
        yield doc if text is None else align(doc, text)


_Line = tuple[int, list[str]]  # (line number, columns)
_DOC_ID = re.compile(r"(?:doc_id|newdoc id)\s*=\s*(\S.*)")


class _Block:
    def __init__(self, docstart: str | None = None, doc_id: str | None = None) -> None:
        self.docstart, self.doc_id = docstart, doc_id
        self.comments: list[str] = []
        self.sentences: list[list[_Line]] = []


def _documents(content: str, comment_prefix: str | None) -> Iterator[_Block]:
    """Split content into documents of sentences of token lines."""
    lines = content.splitlines()

    def is_comment(line: str) -> bool:
        return comment_prefix is not None and line.startswith(comment_prefix)

    def doc_id(line: str) -> str | None:
        assert comment_prefix is not None
        m = _DOC_ID.fullmatch(line[len(comment_prefix) :].strip())
        return m[1].strip() if m else None

    explicit = any(
        line.split()[:1] == [_DOCSTART] or (is_comment(line) and doc_id(line)) for line in lines
    )
    block: _Block | None = None if explicit else _Block()
    current: list[_Line] = []

    def close_sentence() -> None:
        nonlocal current
        if current:
            if block is None:
                raise CaneFormatError(f"line {current[0][0]}: tokens before the first document")
            block.sentences.append(current)
            current = []

    for n, line in enumerate(lines, 1):
        columns = line.split()
        new_id = doc_id(line) if is_comment(line) else None
        if columns[:1] == [_DOCSTART] or new_id is not None:
            close_sentence()
            if block is not None and (block.sentences or block.comments):
                yield block
            block = _Block(docstart=line.strip() if new_id is None else None, doc_id=new_id)
            if new_id is not None:
                block.comments.append(line)
        elif is_comment(line):
            if block is None:
                block = _Block()
            block.comments.append(line)
        elif not columns:
            close_sentence()
            if not explicit and block is not None and block.sentences:
                yield block
                block = _Block()
        else:
            if len(columns) < 2:
                raise CaneFormatError(f"line {n}: expected a token and a tag: {line!r}")
            current.append((n, columns))
    close_sentence()
    if block is not None and (block.sentences or (explicit and block.docstart)):
        yield block


def _build(block: _Block, scheme: Scheme, repair: bool, doc_id: str | None) -> Document:
    sentences = block.sentences
    text_parts: list[str] = []
    segments: list[Segment] = []
    entities: list[Entity] = []
    pos = 0
    for sentence in sentences:
        if text_parts:
            text_parts.append("\n")
            pos += 1
        sentence_start = pos
        bounds: list[tuple[int, int]] = []
        for i, (_, columns) in enumerate(sentence):
            if i:
                text_parts.append(" ")
                pos += 1
            token = columns[0]
            bounds.append((pos, pos + len(token)))
            text_parts.append(token)
            extra = {COLUMNS_KEY: tuple(columns[1:-1])} if len(columns) > 2 else None
            segments.append(Segment(kind="token", span=(pos, pos + len(token)), metadata=extra))
            pos += len(token)
        segments.append(Segment(kind="sentence", span=(sentence_start, pos)))
        tags = [(n, columns[-1]) for n, columns in sentence]
        for label, first, last in decode(tags, scheme, repair):
            entities.append(Entity(spans=[(bounds[first][0], bounds[last][1])], label=label))
    metadata: dict[str, Any] = {RECONSTRUCTED: True}
    if block.docstart is not None:
        metadata[DOCSTART_KEY] = block.docstart
    if block.comments:
        metadata[COMMENTS_KEY] = tuple(block.comments)
    return Document(
        text="".join(text_parts),
        entities=entities,
        segments=segments,
        id=doc_id,
        metadata=metadata,
    )


def from_tokens(
    tokens: Sequence[str],
    tags: Sequence[str | int],
    *,
    scheme: Scheme = "bio",
    label_names: Sequence[str] | None = None,
    repair: bool = False,
    id: str | None = None,
) -> Document:
    """One sentence given as tokens and tags, e.g. a Hugging Face ``tokens``/``ner_tags`` row.

    Integer tags are looked up in ``label_names``.
    """
    if len(tokens) != len(tags):
        raise CaneFormatError(f"{len(tokens)} tokens but {len(tags)} tags")
    names = [label_names[t] if isinstance(t, int) else t for t in tags] if label_names else tags
    if any(not isinstance(t, str) for t in names):
        raise CaneFormatError("integer tags need label_names")
    sentence = [
        (i + 1, [tok, str(tag)]) for i, (tok, tag) in enumerate(zip(tokens, names, strict=True))
    ]
    block = _Block()
    block.sentences.append(sentence)
    return _build(block, scheme, repair, id)


def align(doc: Document, text: str) -> Document:
    """Move a CoNLL document's annotations onto its true raw text.

    The tokens must appear in ``text`` in order, separated only by whitespace.
    """
    tokens = [s for s in doc.segments if s.kind == "token"]
    mapping: dict[int, int] = {}
    pos = 0
    for segment in tokens:
        token = doc.text[segment.span.start : segment.span.end]
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if not text.startswith(token, pos):
            found = text[pos : pos + len(token) + 10]
            raise CaneFormatError(f"token {token!r} not found at offset {pos} (text has {found!r})")
        mapping[segment.span.start], mapping[segment.span.end] = pos, pos + len(token)
        pos += len(token)
    if text[pos:].strip():
        raise CaneFormatError(f"raw text continues after the last token: {text[pos : pos + 30]!r}")

    def moved(span: Span) -> Span:
        return Span(mapping[span.start], mapping[span.end])

    metadata = {k: v for k, v in doc.metadata.items() if k != RECONSTRUCTED}
    return Document(
        text=text,
        id=doc.id,
        entities=[
            Entity(
                spans=[moved(s) for s in e.spans],
                label=e.label,
                id=e.id,
                concepts=e.concepts,
                attributes=e.attributes,
                metadata=e.metadata,
            )
            for e in doc.entities
        ],
        relations=doc.relations,
        segments=[
            Segment(kind=s.kind, span=moved(s.span), id=s.id, metadata=s.metadata)
            for s in doc.segments
        ],
        metadata=metadata,
    )


def decode(
    tags: Sequence[tuple[int, str]], scheme: Scheme, repair: bool = False
) -> Iterator[tuple[str, int, int]]:
    """Turn ``(line number, tag)`` pairs into ``(label, first token, last token)`` entities."""
    open_label: str | None = None
    first = 0

    def invalid(n: int, tag: str, why: str) -> CaneFormatError:
        return CaneFormatError(f"line {n}: invalid {scheme.upper()} tag {tag!r}: {why}")

    for i, (n, tag) in enumerate(tags):
        prefix, label = _split_tag(tag, n)
        if scheme == "bilou":
            prefix = {"U": "S", "L": "E"}.get(prefix, prefix)
        if prefix not in _PREFIXES[scheme]:
            raise invalid(n, tag, f"prefix {prefix!r} is not part of the scheme")
        continues = open_label is not None and open_label == label
        if prefix == "O":
            if open_label is not None and scheme in ("bioes", "bilou") and not repair:
                raise invalid(n, tag, "the open entity was not ended with E-")
            if open_label is not None:
                yield open_label, first, i - 1
            open_label = None
            continue
        starts: bool
        if scheme == "bio":
            if prefix == "I" and not continues and not repair:
                raise invalid(n, tag, "I- does not continue an entity of this type")
            starts = prefix == "B" or not continues
        elif scheme == "iob1":
            if prefix == "B" and not continues and not repair:
                raise invalid(n, tag, "B- only separates adjacent entities of one type")
            starts = prefix == "B" or not continues
        else:  # bioes
            if prefix in ("I", "E") and not continues and not repair:
                raise invalid(n, tag, f"{prefix}- does not continue an entity of this type")
            if prefix in ("B", "S") and open_label is not None and not repair:
                raise invalid(n, tag, "the open entity was not ended with E-")
            starts = prefix in ("B", "S") or not continues
        if starts:
            if open_label is not None:
                yield open_label, first, i - 1
            open_label, first = label, i
        if scheme in ("bioes", "bilou") and prefix in ("S", "E"):
            yield label, first, i
            open_label = None
    if open_label is not None:
        if scheme in ("bioes", "bilou") and not repair:
            n, tag = tags[-1]
            raise invalid(n, tag, "the sentence ends inside an entity")
        yield open_label, first, len(tags) - 1


_PREFIXES: dict[str, set[str]] = {
    "bio": {"B", "I", "O"},
    "iob1": {"B", "I", "O"},
    "bioes": {"B", "I", "O", "E", "S"},
    "bilou": {"B", "I", "O", "E", "S"},
}


def _split_tag(tag: str, n: int) -> tuple[str, str]:
    if tag == "O":
        return "O", ""
    prefix, sep, label = tag.partition("-")
    if not sep or not label:
        raise CaneFormatError(f"line {n}: tag {tag!r} is neither O nor PREFIX-LABEL")
    return prefix, label


# --- writing ------------------------------------------------------------------------------


def write_conll(docs: Iterable[Document], path: str | PathLike[str], **options: Any) -> None:
    """Write documents to one CoNLL file. Options as for ``format_conll``."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(format_conll(doc, **options) for doc in docs))


def format_conll(
    doc: Document,
    *,
    scheme: Scheme = "bio",
    tokenizer: Tokenizer = regex_tokenizer,
    alignment: Alignment = "strict",
    on_conflict: OnConflict = "raise",
    on_unrepresentable: OnUnrepresentable = "raise",
    lossy: Literal["warn", "ignore"] = "warn",
) -> str:
    """One document as CoNLL lines (ending with a blank line).

    Tokens and sentences come from the document's token and sentence segments when present;
    otherwise ``tokenizer`` splits the text and the document is one sentence.

    Args:
        doc: The document.
        scheme: The tag scheme to write.
        tokenizer: ``text -> (start, end)`` token spans, used without token segments.
        alignment: An entity boundary inside a token: ``"strict"`` raises, ``"expand"`` takes
            the whole token, ``"contract"`` drops the partial token (both warn).
        on_conflict: Entities sharing a token: ``"raise"``, keep the ``"outermost"`` or
            ``"innermost"``, or ``"skip"`` every entity involved (all but raise warn).
        on_unrepresentable: Discontinuous, unlabelled or sentence-crossing entities:
            ``"raise"``, ``"first"`` span, ``"hull"``, ``"split"`` into one entity per span,
            or ``"skip"`` (all but raise warn; only ``"skip"`` applies to unlabelled entities).
        lossy: ``"warn"`` once about information CoNLL cannot carry, or ``"ignore"``.
    """
    notes: list[str] = []
    tokens = [s.span for s in doc.segments if s.kind == "token"]
    columns = {s.span: s.metadata.get(COLUMNS_KEY, ()) for s in doc.segments if s.kind == "token"}
    if not tokens:
        tokens = [Span(s, e) for s, e in tokenizer(doc.text)]
    sentences = [s.span for s in doc.segments if s.kind == "sentence"] or (
        [Span(tokens[0].start, tokens[-1].end)] if tokens else []
    )
    sentence_of = _sentence_index(tokens, sentences)

    candidates: list[tuple[str, int, int]] = []  # (label, first token, last token)
    for e in doc.entities:
        for label, span in _entity_spans(e, on_unrepresentable, notes):
            placed = _to_tokens(span, tokens, alignment, notes, e.id)
            if placed is None:
                continue
            first, last = placed
            if sentence_of[first] != sentence_of[last]:
                if on_unrepresentable == "raise":
                    raise UnrepresentableError(f"entity {e.id} crosses a sentence boundary")
                notes.append(f"entity {e.id} skipped: crosses a sentence boundary")
                continue
            candidates.append((label, first, last))
    kept = _resolve_conflicts(candidates, on_conflict, notes)

    tags = ["O"] * len(tokens)
    for label, first, last in kept:
        tags[first : last + 1] = _encode(label, first, last, tags, scheme)

    if lossy == "warn":
        _warn_lossy(doc, notes)
    out: list[str] = []
    docstart = doc.metadata.get(DOCSTART_KEY)
    if docstart:
        out += [str(docstart), ""]
    out += [str(c) for c in doc.metadata.get(COMMENTS_KEY, ())]
    by_sentence: list[list[int]] = [[] for _ in sentences]
    for t_index, s_index in enumerate(sentence_of):
        by_sentence[s_index].append(t_index)
    for token_indices in by_sentence:
        for t_index in token_indices:
            token = tokens[t_index]
            text = doc.text[token.start : token.end]
            if _WHITESPACE.search(text):
                raise UnrepresentableError(f"token {text!r} contains whitespace")
            out.append(" ".join([text, *columns.get(token, ()), tags[t_index]]))
        out.append("")
    return "\n".join(out) + "\n" if out else ""


def _sentence_index(tokens: list[Span], sentences: list[Span]) -> list[int]:
    index = []
    for token in tokens:
        for i, sentence in enumerate(sentences):
            if sentence.start <= token.start and token.end <= sentence.end:
                index.append(i)
                break
        else:
            raise UnrepresentableError(f"token {token} lies outside every sentence segment")
    return index


def _entity_spans(
    e: Entity, strategy: OnUnrepresentable, notes: list[str]
) -> list[tuple[str, Span]]:
    if e.label is None or _WHITESPACE.search(e.label) or not e.label:
        if e.label is None and strategy == "skip":
            notes.append(f"entity {e.id} skipped: no label")
            return []
        raise UnrepresentableError(f"entity {e.id}: CoNLL needs a one-token label")
    if len(e.spans) == 1:
        return [(e.label, e.spans[0])]
    if strategy == "raise":
        raise UnrepresentableError(f"entity {e.id} is discontinuous, which CoNLL cannot express")
    notes.append(f"discontinuous entity {e.id} ({strategy})")
    if strategy == "skip":
        return []
    if strategy == "first":
        return [(e.label, e.spans[0])]
    if strategy == "hull":
        return [(e.label, e.hull)]
    return [(e.label, s) for s in e.spans]


def _to_tokens(
    span: Span, tokens: list[Span], alignment: Alignment, notes: list[str], eid: str | None
) -> tuple[int, int] | None:
    covered = [i for i, t in enumerate(tokens) if t.start < span.end and span.start < t.end]
    if not covered:
        raise UnrepresentableError(f"entity {eid} covers no token")
    first, last = covered[0], covered[-1]
    exact = tokens[first].start == span.start and tokens[last].end == span.end
    if exact:
        return first, last
    if alignment == "strict":
        raise UnrepresentableError(
            f"entity {eid} at {span} does not start and end on token boundaries"
        )
    notes.append(f"entity {eid} {alignment}ed to token boundaries")
    if alignment == "expand":
        return first, last
    inside = [i for i in covered if span.start <= tokens[i].start and tokens[i].end <= span.end]
    return (inside[0], inside[-1]) if inside else None


def _resolve_conflicts(
    candidates: list[tuple[str, int, int]], strategy: OnConflict, notes: list[str]
) -> list[tuple[str, int, int]]:
    def clash(a: tuple[str, int, int], b: tuple[str, int, int]) -> bool:
        return a[1] <= b[2] and b[1] <= a[2]

    unique = list(dict.fromkeys(candidates))
    if len(unique) < len(candidates):
        notes.append(f"{len(candidates) - len(unique)} duplicate token span(s) merged")
    conflicted = {c for c in unique for d in unique if c is not d and clash(c, d)}
    if not conflicted:
        return unique
    if strategy == "raise":
        raise UnrepresentableError(
            f"{len(conflicted)} entities overlap at token level; choose on_conflict"
        )
    if strategy == "skip":
        notes.append(f"{len(conflicted)} overlapping entities skipped")
        return [c for c in unique if c not in conflicted]
    sign = -1 if strategy == "outermost" else 1
    kept: list[tuple[str, int, int]] = []
    for c in sorted(unique, key=lambda c: (sign * (c[2] - c[1]), c[1])):
        if any(clash(c, k) for k in kept):
            notes.append(f"{c[0]} entity at tokens {c[1]}-{c[2]} dropped ({strategy})")
        else:
            kept.append(c)
    return sorted(kept, key=lambda c: c[1])


def _encode(label: str, first: int, last: int, tags: list[str], scheme: Scheme) -> list[str]:
    n = last - first + 1
    if scheme == "bio":
        return [f"B-{label}"] + [f"I-{label}"] * (n - 1)
    if scheme == "iob1":
        touching = first > 0 and tags[first - 1] != "O" and tags[first - 1][2:] == label
        return [f"{'B' if touching else 'I'}-{label}"] + [f"I-{label}"] * (n - 1)
    single, end = ("U", "L") if scheme == "bilou" else ("S", "E")
    if n == 1:
        return [f"{single}-{label}"]
    return [f"B-{label}"] + [f"I-{label}"] * (n - 2) + [f"{end}-{label}"]


def _warn_lossy(doc: Document, notes: list[str]) -> None:
    lost = [*notes]
    if doc.relations:
        lost.append(f"{len(doc.relations)} relations")
    concepts = sum(len(e.concepts) for e in doc.entities)
    attributes = sum(len(e.attributes) for e in doc.entities)
    if concepts:
        lost.append(f"{concepts} concepts")
    if attributes:
        lost.append(f"{attributes} attributes")
    other = [s for s in doc.segments if s.kind not in ("token", "sentence")]
    if other:
        lost.append(f"{len(other)} other segments")
    extra = set(doc.metadata) - {RECONSTRUCTED, DOCSTART_KEY, COMMENTS_KEY}
    if extra or any(e.metadata for e in doc.entities):
        lost.append("metadata")
    if not doc.metadata.get(RECONSTRUCTED) and doc.text:
        lost.append("the original whitespace between tokens")
    if lost:
        warnings.warn(
            "CoNLL cannot carry: " + "; ".join(lost), LossyConversionWarning, stacklevel=3
        )
