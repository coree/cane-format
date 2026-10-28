"""Inline XML: the text with annotations as elements around the annotated characters.

The default style writes the label as the element name, ``<DRUG>aspirin</DRUG>``; ``tag=``
switches to one element name with the label in an attribute, ``<entity type="DRUG">``. A
discontinuous entity, or one whose span crosses another's, is written as several elements that
share a ``ref`` attribute; the output is always well-formed. Offsets refer to the unescaped text.

Reading also accepts corpora with their own markup (e.g. GENIA, ``tag="cons", type_attr="sem"``):
elements that are not annotations are structure, whose text flows into the document.
"""

from __future__ import annotations

import re
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape, quoteattr

from cane_format.errors import CaneFormatError, LossyConversionWarning, UnrepresentableError
from cane_format.model import Document, Entity, Segment, Span

COLLECTION_TAG = "documents"
DOCUMENT_TAG = "document"
_NAME = re.compile(r"[^\W\d][\w.\-]*")


# --- reading ------------------------------------------------------------------------------


def read_xml(path: str | PathLike[str], **options: Any) -> list[Document]:
    """Read an XML file. Options as for ``parse_xml``."""
    return list(iter_xml(path, **options))


def iter_xml(path: str | PathLike[str], **options: Any) -> Iterator[Document]:
    """Like ``read_xml``, yielding documents one at a time."""
    yield from parse_xml(Path(path).read_text(encoding="utf-8"), **options)


def parse_xml(
    content: str,
    *,
    tag: str | None = None,
    type_attr: str = "type",
    ref_attr: str = "ref",
    document_tag: str | None = None,
    segment_tags: Sequence[str] = (),
    exclude_tags: Sequence[str] = (),
) -> list[Document]:
    """Build documents from inline XML.

    Content without a single root element (an inline fragment, as a model would write it) is
    one document. A ``<documents>`` root, as ``write_xml`` writes, holds ``<document id=…>``s.

    Args:
        content: The XML text.
        tag: The annotation element name; None means every element is an annotation named by
            its label.
        type_attr: With ``tag``, the attribute holding the label.
        ref_attr: The attribute linking the elements of one entity (space-separated values put
            one element into several entities).
        document_tag: Each element with this name is one document (e.g. ``"article"``).
        segment_tags: Structural elements to keep as segments of that kind (e.g. sentences).
        exclude_tags: Structural elements whose text is not part of the document text; their
            text is kept in ``metadata[name]``.
    """
    root = _root(content)
    children = list(root)
    if document_tag is None and len(children) == 1 and children[0].tag == COLLECTION_TAG:
        units = [(el, el.get("id")) for el in children[0] if el.tag == DOCUMENT_TAG]
        skip = {COLLECTION_TAG, DOCUMENT_TAG}
    elif document_tag is not None:
        units = [(el, None) for el in root.iter(document_tag)]
        skip = {document_tag}
    else:
        units = [(root, None)]
        skip = set()
    reader = _Reader(tag, type_attr, ref_attr, set(segment_tags), set(exclude_tags), skip)
    return [
        reader.document(el, doc_id or (None if len(units) == 1 else str(n)))
        for n, (el, doc_id) in enumerate(units, 1)
    ]


_WRAPPER = "cane-format-fragment"


def _root(content: str) -> ET.Element:
    """Parse content inside a synthetic root, so that inline fragments and an annotation
    covering the whole text both work."""
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", content)
    body = re.sub(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", "", body)
    try:
        return ET.fromstring(f"<{_WRAPPER}>{body}</{_WRAPPER}>")
    except ET.ParseError as err:
        raise CaneFormatError(f"not well-formed XML: {err}") from err


class _Reader:
    def __init__(
        self,
        tag: str | None,
        type_attr: str,
        ref_attr: str,
        segment_tags: set[str],
        exclude_tags: set[str],
        skip: set[str],
    ) -> None:
        self.tag, self.type_attr, self.ref_attr = tag, type_attr, ref_attr
        self.segment_tags, self.exclude_tags, self.skip = segment_tags, exclude_tags, skip

    def document(self, element: ET.Element, doc_id: str | None) -> Document:
        self.parts: list[str] = []
        self.size = 0
        self.fragments: list[tuple[str | None, list[str], Span]] = []  # (label, refs, span)
        self.segments: list[Segment] = []
        self.excluded: dict[str, str] = {}
        self._walk(element, top=True)
        text = "".join(self.parts)
        return Document(
            text=text,
            entities=self._entities(),
            segments=self.segments,
            id=doc_id,
            metadata=self.excluded,
        )

    def _append(self, s: str | None) -> None:
        if s:
            self.parts.append(s)
            self.size += len(s)

    def _walk(self, el: ET.Element, top: bool = False) -> None:
        if not top and el.tag in self.exclude_tags:
            self.excluded.setdefault(el.tag, "".join(el.itertext()).strip())
            self._append(el.tail)
            return
        start = self.size
        self._append(el.text)
        for child in el:
            self._walk(child)
        end = self.size
        annotation = not top and (self.tag is None or el.tag == self.tag)
        if annotation and el.tag not in self.skip:
            if start == end:
                raise CaneFormatError(f"empty annotation element <{el.tag}>")
            label = el.tag if self.tag is None else el.get(self.type_attr)
            refs = (el.get(self.ref_attr) or "").split()
            self.fragments.append((label, refs, Span(start, end)))
        elif el.tag in self.segment_tags and start < end:
            self.segments.append(Segment(kind=el.tag, span=(start, end)))
        if not top:
            self._append(el.tail)

    def _entities(self) -> list[Entity]:
        """One entity per element without ref; elements sharing a ref form one entity."""
        grouped: dict[tuple[str | None, str], list[Span]] = {}
        order: list[tuple[str | None, str] | tuple[str | None, list[Span]]] = []
        for label, refs, span in sorted(self.fragments, key=lambda f: (f[2].start, -f[2].end)):
            if not refs:
                order.append((label, [span]))
            for ref in refs:
                if (label, ref) not in grouped:
                    grouped[label, ref] = []
                    order.append((label, ref))
                grouped[label, ref].append(span)
        entities = []
        for label, key in order:
            spans = grouped[label, key] if isinstance(key, str) else key
            entity_id = key if isinstance(key, str) and len(self._refs_of(key)) == 1 else None
            entities.append(Entity(spans=_merge(spans), label=label, id=entity_id))
        return entities

    def _refs_of(self, ref: str) -> set[str | None]:
        return {label for label, refs, _ in self.fragments if ref in refs}


def _merge(spans: list[Span]) -> list[Span]:
    """Join fragments that touch (a span split around a crossing element) back into one."""
    merged: list[Span] = []
    for s in sorted(set(spans)):
        if merged and merged[-1].end == s.start:
            merged[-1] = Span(merged[-1].start, s.end)
        else:
            merged.append(s)
    return merged


# --- writing ------------------------------------------------------------------------------


def write_xml(docs: Iterable[Document], path: str | PathLike[str], **options: Any) -> None:
    """Write documents as ``<documents><document id=…>…</document>…</documents>``."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<{COLLECTION_TAG}>\n')
        for doc in docs:
            attr = f" id={quoteattr(doc.id)}" if doc.id else ""
            f.write(f"<{DOCUMENT_TAG}{attr}>{format_xml(doc, **options)}</{DOCUMENT_TAG}>\n")
        f.write(f"</{COLLECTION_TAG}>\n")


def format_xml(
    doc: Document,
    *,
    tag: str | None = None,
    type_attr: str = "type",
    ref_attr: str = "ref",
    lossy: Literal["warn", "ignore"] = "warn",
) -> str:
    """The document text with its entities as inline elements.

    Raises:
        UnrepresentableError: In the default style, a label that is not a valid XML element
            name (e.g. ``protein_N/A``) or a missing label; pass ``tag=`` to write any label.
    """
    pieces = _fragments(doc, tag)
    events: list[tuple[int, int, int, str]] = []  # (position, order, depth key, markup)
    for n, (entity, span, ref) in enumerate(pieces):
        if tag is None:
            name = str(entity.label)
            attrs = ""
        else:
            name = tag
            attrs = "" if entity.label is None else f" {type_attr}={quoteattr(entity.label)}"
        if ref is not None:
            attrs += f" {ref_attr}={quoteattr(ref)}"
        length = span.end - span.start
        events.append((span.start, 1, -length * 10_000 - (len(pieces) - n), f"<{name}{attrs}>"))
        events.append((span.end, 0, length * 10_000 + (len(pieces) - n), f"</{name}>"))
    out: list[str] = []
    last = 0
    for position, _, _, markup in sorted(events):
        out.append(_escape(doc.text[last:position]))
        out.append(markup)
        last = position
    out.append(_escape(doc.text[last:]))
    if lossy == "warn":
        _warn_lossy(doc)
    return "".join(out)


def _escape(text: str) -> str:
    # XML parsers turn \r\n and \r into \n; a character reference keeps the \r.
    return escape(text).replace("\r", "&#13;")


def _fragments(doc: Document, tag: str | None) -> list[tuple[Entity, Span, str | None]]:
    """Each entity's spans, split where they cross another element, with a ref if needed."""
    for e in doc.entities:
        if tag is None and (e.label is None or not _NAME.fullmatch(e.label)):
            raise UnrepresentableError(
                f"entity {e.id}: label {e.label!r} is not an XML element name; pass tag="
            )
    queue = sorted(
        ((e, s) for e in doc.entities for s in e.spans),
        key=lambda x: (x[1].start, -x[1].end, x[0].label or "", x[0].id or ""),
    )
    placed: list[tuple[Entity, Span]] = []
    while queue:
        entity, span = queue.pop(0)
        crossing = next((p for _, p in placed if p.start < span.start < p.end < span.end), None)
        if crossing is None:
            placed.append((entity, span))
            continue
        # Both pieces go back: the head may still cross another element.
        queue.append((entity, Span(span.start, crossing.end)))
        queue.append((entity, Span(crossing.end, span.end)))
        queue.sort(key=lambda x: (x[1].start, -x[1].end, x[0].label or "", x[0].id or ""))
    counts: dict[int, int] = {}
    for entity, _ in placed:
        counts[id(entity)] = counts.get(id(entity), 0) + 1
    return [(e, s, e.id if counts[id(e)] > 1 else None) for e, s in placed]


def _warn_lossy(doc: Document) -> None:
    lost = []
    if doc.relations:
        lost.append(f"{len(doc.relations)} relations")
    if doc.segments:
        lost.append(f"{len(doc.segments)} segments")
    if any(e.concepts for e in doc.entities):
        lost.append("concepts")
    if any(e.attributes for e in doc.entities):
        lost.append("attributes")
    if doc.metadata or any(e.metadata for e in doc.entities):
        lost.append("metadata")
    if lost:
        warnings.warn(
            "inline XML cannot carry: " + "; ".join(lost), LossyConversionWarning, stacklevel=3
        )
