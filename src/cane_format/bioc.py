"""BioC JSON: collections of documents made of passages (and sentences) with annotations.

Offsets are UTF-8 bytes by default, as the BioC specification requires. The document text is
built by placing each passage's text (or its sentences' texts) at its own offset, filling gaps
with spaces, so annotation offsets are used verbatim; writing puts every passage back at its
offset with its exact text.

Information with no field in the model is kept in metadata under these keys, so that BioC ->
BioC is lossless: ``infons`` (on documents, segments, entities, relations), ``bioc_level`` (where
an annotation or relation sat when not on a passage), ``bioc_concept_keys``, ``bioc_text``
(an annotation's stored text, when it is not its parts joined by spaces), ``bioc_extra``
(unknown document fields), ``bioc_relations`` (relations without nodes), ``bioc_collection``
and ``bioc_empty_passages``.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterable, Iterator, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Literal

from cane_format._offsets import OffsetMap, OffsetUnit
from cane_format._verify import covers, unit_hint
from cane_format.errors import (
    CaneFormatError,
    IntegrityError,
    LossyConversionWarning,
    UnrepresentableError,
)
from cane_format.model import Concept, Document, Entity, Member, Relation, Segment, Span

Verify = Literal["raise", "warn", "off"]

INFONS = "infons"
LEVEL = "bioc_level"
CONCEPT_KEYS = "bioc_concept_keys"
EXTRA = "bioc_extra"
RAW_RELATIONS = "bioc_relations"
COLLECTION = "bioc_collection"
EMPTY_PASSAGES = "bioc_empty_passages"
TEXT_IN_SENTENCES = "bioc_text_in_sentences"
TEXT = "bioc_text"

_DOC_FIELDS = {"id", "infons", "passages", "annotations", "relations"}
_TRIGGER = "trigger"


# --- reading ------------------------------------------------------------------------------


def read_bioc_json(
    path: str | PathLike[str],
    *,
    verify: Verify = "raise",
    offset_unit: OffsetUnit = "utf8",
    label_key: str = "type",
    concept_keys: Sequence[str] = ("identifier",),
) -> list[Document]:
    """Read a BioC JSON file. See ``parse_bioc_json``."""
    return list(
        iter_bioc_json(
            path,
            verify=verify,
            offset_unit=offset_unit,
            label_key=label_key,
            concept_keys=concept_keys,
        )
    )


def iter_bioc_json(
    path: str | PathLike[str],
    *,
    verify: Verify = "raise",
    offset_unit: OffsetUnit = "utf8",
    label_key: str = "type",
    concept_keys: Sequence[str] = ("identifier",),
) -> Iterator[Document]:
    """Like ``read_bioc_json``, yielding documents one at a time."""
    content = Path(path).read_text(encoding="utf-8")
    yield from _parse(content, verify, offset_unit, label_key, tuple(concept_keys))


def parse_bioc_json(
    content: str,
    *,
    verify: Verify = "raise",
    offset_unit: OffsetUnit = "utf8",
    label_key: str = "type",
    concept_keys: Sequence[str] = ("identifier",),
) -> list[Document]:
    """Build documents from BioC JSON: a collection, a list of collections, or a PubTator3 export.

    Args:
        content: The JSON text.
        verify: Check every annotation's stored text against its offsets: ``"raise"`` an
            ``IntegrityError`` on mismatch, ``"warn"``, or ``"off"``.
        offset_unit: The unit offsets count in. The BioC specification says UTF-8 bytes.
        label_key: The annotation infon holding the label.
        concept_keys: Annotation infons holding concept identifiers (kept verbatim).
    """
    return list(_parse(content, verify, offset_unit, label_key, tuple(concept_keys)))


def _parse(
    content: str, verify: Verify, unit: OffsetUnit, label_key: str, concept_keys: tuple[str, ...]
) -> Iterator[Document]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as err:
        raise CaneFormatError(f"not valid JSON: {err}") from err
    pubtator = isinstance(data, dict) and "PubTator3" in data
    if pubtator:
        collections = [{"documents": data["PubTator3"]}]
    elif isinstance(data, dict):
        collections = [data]
    elif isinstance(data, list):
        collections = data
    else:
        raise CaneFormatError("expected a BioC collection")
    for collection in collections:
        if not isinstance(collection, dict) or not isinstance(collection.get("documents"), list):
            raise CaneFormatError("a BioC collection needs a 'documents' list")
        info = {k: v for k, v in collection.items() if k != "documents"}
        for raw in collection["documents"]:
            reader = _DocReader(raw, info, verify, unit, label_key, concept_keys, pubtator)
            try:
                yield reader.document()
            except (KeyError, TypeError, ValueError) as err:
                raise CaneFormatError(f"document {raw.get('id')!r}: {err}") from err


class _DocReader:
    def __init__(
        self,
        raw: dict[str, Any],
        collection: dict[str, Any],
        verify: Verify,
        unit: OffsetUnit,
        label_key: str,
        concept_keys: tuple[str, ...],
        pubtator: bool = False,
    ) -> None:
        self.raw, self.collection, self.verify, self.unit = raw, collection, verify, unit
        self.pubtator = pubtator
        self.label_key, self.concept_keys = label_key, concept_keys
        self.doc_id = str(raw["id"])

    def document(self) -> Document:
        text = self._text()
        self.text = text
        self.offsets = OffsetMap(text, self.unit)
        segments: list[Segment] = []
        entities: list[Entity] = []
        relations: list[Relation] = []
        raw_relations: list[Any] = []
        pending: list[tuple[dict[str, Any], str | None]] = []
        empty_passages: list[Any] = []
        for passage in self.raw.get("passages", []):
            span = self._passage_span(passage)
            if span is None:
                empty_passages.append(_frozen(passage))
                continue
            metadata: dict[str, Any] = {}
            _put(metadata, INFONS, _frozen(passage.get("infons")))
            if not passage.get("text") and passage.get("sentences"):
                metadata[TEXT_IN_SENTENCES] = True
            segments.append(Segment(kind="passage", span=span, metadata=metadata))
            for ann in passage.get("annotations", []):
                entities.append(self._entity(ann, None))
            for sentence in passage.get("sentences", []):
                if not sentence.get("text"):
                    raise ValueError("a sentence without text")
                start = self._cp(sentence["offset"])
                segments.append(
                    Segment(
                        kind="sentence",
                        span=(start, start + len(sentence["text"])),
                        metadata=_put({}, INFONS, _frozen(sentence.get("infons"))),
                    )
                )
                for ann in sentence.get("annotations", []):
                    entities.append(self._entity(ann, "sentence"))
                for rel in sentence.get("relations", []):
                    pending.append((rel, "sentence"))
            for rel in passage.get("relations", []):
                pending.append((rel, None))
        for ann in self.raw.get("annotations", []):
            entities.append(self._entity(ann, "document"))
        for rel in self.raw.get("relations", []):
            pending.append((rel, "document"))
        unresolved = self._resolve(pending, entities, relations, raw_relations)
        if unresolved:
            warnings.warn(
                f"document {self.doc_id}: {unresolved} relation(s) do not point at annotations "
                "of this document; kept unchanged in metadata['bioc_relations']",
                stacklevel=5,
            )

        metadata = {}
        _put(metadata, INFONS, _frozen(self.raw.get("infons")))
        _put(metadata, EXTRA, _frozen({k: v for k, v in self.raw.items() if k not in _DOC_FIELDS}))
        _put(metadata, RAW_RELATIONS, tuple(raw_relations))
        _put(metadata, EMPTY_PASSAGES, tuple(empty_passages))
        _put(metadata, COLLECTION, _frozen(self.collection))
        return Document(
            text=text,
            entities=entities,
            relations=relations,
            segments=segments,
            id=self.doc_id,
            metadata=metadata,
        )

    def _text(self) -> str:
        pieces: list[tuple[int, str]] = []
        for passage in self.raw.get("passages", []):
            if passage.get("text"):
                pieces.append((passage["offset"], passage["text"]))
            else:
                pieces += [
                    (s["offset"], s["text"]) for s in passage.get("sentences", []) if s.get("text")
                ]
        chars: list[str] = []
        position = 0  # in offset units
        for offset, text in pieces:
            if offset < position:
                raise ValueError(f"text at offset {offset} overlaps the preceding text")
            chars.append(" " * (offset - position))
            chars.append(text)
            position = offset + _unit_length(text, self.unit)
        return "".join(chars)

    def _cp(self, offset: int) -> int:
        try:
            return self.offsets.to_codepoint(offset)
        except KeyError:
            raise IntegrityError(
                f"document {self.doc_id}: offset {offset} falls inside a character "
                f"({self.unit} offsets)"
            ) from None

    def _passage_span(self, passage: dict[str, Any]) -> Span | None:
        texts = [s for s in passage.get("sentences", []) if s.get("text")]
        if not passage.get("text") and not texts:
            return None
        start = self._cp(passage["offset"])
        if passage.get("text"):
            return Span(start, start + len(passage["text"]))
        last = texts[-1]
        return Span(start, self._cp(last["offset"]) + len(last["text"]))

    def _entity(self, ann: dict[str, Any], level: str | None) -> Entity:
        raw_spans = [(loc["offset"], loc["offset"] + loc["length"]) for loc in ann["locations"]]
        if not raw_spans:
            raise ValueError(f"annotation {ann.get('id')!r} has no location")
        spans = [Span(self._cp(s), self._cp(e)) for s, e in raw_spans]
        stored = ann.get("text")
        if stored is not None and self.verify != "off" and not covers(self.text, spans, stored):
            found = " ".join(self.text[s.start : s.end] for s in spans)
            message = (
                f"document {self.doc_id}, annotation {ann.get('id')!r} stores {stored!r} but the "
                f"text at its {self.unit} offsets reads {found!r}"
            ) + unit_hint(self.text, raw_spans, stored, self.unit)
            if self.verify == "raise":
                raise IntegrityError(message)
            warnings.warn(message, stacklevel=6)
        infons = dict(ann.get("infons") or {})
        label = infons.pop(self.label_key, None)
        concepts, keys = [], []
        for key in self.concept_keys:
            if isinstance(infons.get(key), str):
                concepts.append(Concept(id=infons.pop(key)))
                keys.append(key)
        metadata: dict[str, Any] = {}
        _put(metadata, INFONS, _frozen(infons))
        _put(metadata, CONCEPT_KEYS, tuple(keys))
        _put(metadata, LEVEL, level)
        if stored is not None and stored != " ".join(self.text[s.start : s.end] for s in spans):
            metadata[TEXT] = stored
        return Entity(
            spans=spans,
            label=label if isinstance(label, str) else None,
            id=None if ann.get("id") is None else str(ann["id"]),
            concepts=concepts,
            metadata=metadata,
        )

    def _resolve(
        self,
        pending: list[tuple[dict[str, Any], str | None]],
        entities: list[Entity],
        out: list[Relation],
        raw: list[Any],
    ) -> int:
        """Turn relations into ``Relation``s when every node points at something in the document.

        Relations without nodes, or with nodes pointing elsewhere (PubTator3 uses its own node
        convention), are kept raw. Returns how many had nodes but could not be resolved.
        """
        entity_ids = {e.id for e in entities}
        if self.pubtator:
            # PubTator3 relations link concepts (infons role1/role2); their nodes are not
            # annotation references, so they are never read as mention-level relations.
            raw.extend(_frozen({**rel, LEVEL: level}) for rel, level in pending)
            return 0
        usable = {i: (rel, level) for i, (rel, level) in enumerate(pending) if rel.get("nodes")}
        while True:
            known = entity_ids | {str(pending[i][0].get("id")) for i in usable}
            dropped = [
                i
                for i, (rel, _) in usable.items()
                if any(str(n["refid"]) not in known for n in rel["nodes"])
                or any(
                    n.get("role") == _TRIGGER and str(n["refid"]) not in entity_ids
                    for n in rel["nodes"]
                )
            ]
            if not dropped:
                break
            for i in dropped:
                del usable[i]
        for i, (rel, level) in enumerate(pending):
            if i in usable:
                out.append(self._relation(rel, level))
            else:
                raw.append(_frozen({**rel, LEVEL: level}))
        return sum(1 for i, (rel, _) in enumerate(pending) if rel.get("nodes") and i not in usable)

    def _relation(self, rel: dict[str, Any], level: str | None) -> Relation:
        nodes = rel["nodes"]
        triggers = [n["refid"] for n in nodes if n.get("role") == _TRIGGER]
        if len(triggers) > 1:
            raise ValueError(f"relation {rel.get('id')!r} has several trigger nodes")
        members = [
            Member(str(n["refid"]), n.get("role") or None)
            for n in nodes
            if n.get("role") != _TRIGGER
        ]
        infons = dict(rel.get("infons") or {})
        rel_type = infons.pop("type", "")
        metadata: dict[str, Any] = {}
        _put(metadata, INFONS, _frozen(infons))
        _put(metadata, LEVEL, level)
        return Relation(
            type=str(rel_type),
            members=members,
            trigger=str(triggers[0]) if triggers else None,
            id=None if rel.get("id") is None else str(rel["id"]),
            metadata=metadata,
        )


def _unit_length(text: str, unit: OffsetUnit) -> int:
    if unit == "utf8":
        return len(text.encode("utf-8"))
    if unit == "utf16":
        return len(text.encode("utf-16-le")) // 2
    return len(text)


def _put(obj: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    if value not in (None, (), {}, [], ""):
        obj[key] = value
    return obj


def _frozen(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, dict):
        return {k: _frozen(v) for k, v in value.items()}
    return value


def _thawed(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_thawed(v) for v in value]
    if isinstance(value, dict):
        return {k: _thawed(v) for k, v in value.items()}
    return value


# --- writing ------------------------------------------------------------------------------


def write_bioc_json(docs: Iterable[Document], path: str | PathLike[str], **options: Any) -> None:
    """Write documents as one BioC JSON collection. Options as for ``format_bioc_json``."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(format_bioc_json(docs, **options))


def format_bioc_json(
    docs: Iterable[Document],
    *,
    offset_unit: OffsetUnit = "utf8",
    label_key: str = "type",
    concept_key: str = "identifier",
    indent: int | None = None,
    lossy: Literal["warn", "ignore"] = "warn",
) -> str:
    """Documents as one BioC JSON collection.

    Annotations and relations go back where they were read from (``bioc_level``); everything
    else is placed in the passage containing its start, or at document level.

    Args:
        docs: The documents.
        offset_unit: The unit to write offsets in (UTF-8 bytes per the specification).
        label_key: The annotation infon for the label.
        concept_key: The infon for concepts that did not come from BioC.
        indent: JSON indentation; one line when None.
        lossy: ``"warn"`` once about information BioC cannot carry, or ``"ignore"``.
    """
    notes: list[str] = []
    docs = list(docs)
    collection = _thawed(docs[0].metadata.get(COLLECTION, {})) if docs else {}
    out = {"source": "", "date": "", "key": "", "infons": {}, **collection}
    out["documents"] = [
        _DocWriter(d, offset_unit, label_key, concept_key, notes).document() for d in docs
    ]
    if notes and lossy == "warn":
        warnings.warn(
            "BioC cannot carry: " + "; ".join(dict.fromkeys(notes)),
            LossyConversionWarning,
            stacklevel=2,
        )
    return json.dumps(out, ensure_ascii=False, indent=indent)


class _DocWriter:
    def __init__(
        self, doc: Document, unit: OffsetUnit, label_key: str, concept_key: str, notes: list[str]
    ) -> None:
        self.doc, self.label_key, self.concept_key, self.notes = doc, label_key, concept_key, notes
        self.offsets = OffsetMap(doc.text, unit)

    def document(self) -> dict[str, Any]:
        doc = self.doc
        passages = [s for s in doc.segments if s.kind == "passage"]
        if not passages and doc.text:
            passages = [Segment(kind="passage", span=(0, len(doc.text)))]
        sentences = [s for s in doc.segments if s.kind == "sentence"]
        other = [s for s in doc.segments if s.kind not in ("passage", "sentence")]
        if other:
            self.notes.append(f"{len(other)} segments other than passages and sentences")
        p_objs = [self._passage(p, sentences) for p in passages]
        s_objs = [s for p in p_objs for s in p.get("sentences", [])]
        top: dict[str, Any] = {"annotations": [], "relations": []}

        for e in doc.entities:
            ann = self._annotation(e)
            container = self._container(e.start, e.metadata.get(LEVEL), p_objs, s_objs, top)
            container["annotations"].append(ann)
        starts = {e.id: e.start for e in doc.entities}
        for r in doc.relations:
            anchor = [r.trigger] if r.trigger else [m.refid for m in r.members]
            start = next((starts[i] for i in anchor if i in starts), None)
            container = self._container(start, r.metadata.get(LEVEL), p_objs, s_objs, top)
            container["relations"].append(self._relation(r))
        for raw in doc.metadata.get(RAW_RELATIONS, ()):
            rel = _thawed(raw)
            level = rel.pop(LEVEL, None)
            self._container(None, level, p_objs, s_objs, top)["relations"].append(rel)

        empty = [_thawed(p) for p in doc.metadata.get(EMPTY_PASSAGES, ())]
        all_passages = sorted([*p_objs, *empty], key=lambda p: int(p["offset"]))
        for p in all_passages:
            p.pop("_span", None)
            for s in p.get("sentences", []):
                s.pop("_span", None)
        known = {INFONS, EXTRA, RAW_RELATIONS, EMPTY_PASSAGES, COLLECTION}
        if set(doc.metadata) - known:
            self.notes.append("document metadata")
        return {
            "id": doc.id or "",
            "infons": _thawed(doc.metadata.get(INFONS, {})),
            "passages": all_passages,
            "annotations": top["annotations"],
            "relations": top["relations"],
            **_thawed(doc.metadata.get(EXTRA, {})),
        }

    def _passage(self, p: Segment, sentences: list[Segment]) -> dict[str, Any]:
        text = self.doc.text[p.span.start : p.span.end]
        obj: dict[str, Any] = {
            "infons": _thawed(p.metadata.get(INFONS, {})),
            "offset": self.offsets.from_codepoint(p.span.start),
            "text": "" if p.metadata.get(TEXT_IN_SENTENCES) else text,
            "annotations": [],
            "relations": [],
            "_span": p.span,
        }
        inside = [s for s in sentences if p.span.start <= s.span.start < p.span.end]
        if inside:
            obj["sentences"] = [
                {
                    "infons": _thawed(s.metadata.get(INFONS, {})),
                    "offset": self.offsets.from_codepoint(s.span.start),
                    "text": self.doc.text[s.span.start : s.span.end],
                    "annotations": [],
                    "relations": [],
                    "_span": s.span,
                }
                for s in inside
            ]
        return obj

    def _container(
        self,
        start: int | None,
        level: Any,
        passages: list[dict[str, Any]],
        sentences: list[dict[str, Any]],
        top: dict[str, Any],
    ) -> dict[str, Any]:
        if level == "document" or (start is None and level is None):
            return top
        pool = sentences if level == "sentence" else passages
        for obj in pool:
            span = obj["_span"]
            if start is not None and span.start <= start < span.end:
                return obj
        return top

    def _annotation(self, e: Entity) -> dict[str, Any]:
        infons: dict[str, Any] = {}
        if e.label is not None:
            infons[self.label_key] = e.label
        keys = list(e.metadata.get(CONCEPT_KEYS, ())) or [self.concept_key]
        concepts = list(e.concepts)
        if any(c.source is not None or c.name is not None for c in concepts):
            self.notes.append("concept sources and names")
        if len(concepts) > len(keys):
            head, tail = concepts[: len(keys) - 1], concepts[len(keys) - 1 :]
            self.notes.append(f"several concepts joined with ';' under {keys[-1]!r}")
            concepts = [*head, Concept(id=";".join(c.id for c in tail))]
        for key, concept in zip(keys, concepts, strict=False):
            infons[key] = concept.id
        for name, value in e.attributes.items():
            infons[name] = value if isinstance(value, str) else str(value).lower()
            self.notes.append("attributes (written as string infons)")
        infons.update(_thawed(e.metadata.get(INFONS, {})))
        if set(e.metadata) - {INFONS, CONCEPT_KEYS, LEVEL, TEXT}:
            self.notes.append("entity metadata")
        ann: dict[str, Any] = {"id": e.id, "infons": infons}
        ann["text"] = e.metadata.get(TEXT, " ".join(e.parts(self.doc.text)))
        ann["locations"] = [
            {
                "offset": self.offsets.from_codepoint(s.start),
                "length": self.offsets.from_codepoint(s.end) - self.offsets.from_codepoint(s.start),
            }
            for s in e.spans
        ]
        return ann

    def _relation(self, r: Relation) -> dict[str, Any]:
        infons: dict[str, Any] = {"type": r.type} if r.type else {}
        infons.update(_thawed(r.metadata.get(INFONS, {})))
        for name, value in r.attributes.items():
            infons[name] = value if isinstance(value, str) else str(value).lower()
            self.notes.append("attributes (written as string infons)")
        nodes = [{"refid": m.refid, "role": m.role or ""} for m in r.members]
        if r.trigger is not None:
            if any(m.role == _TRIGGER for m in r.members):
                raise UnrepresentableError(f"relation {r.id}: a member already has role 'trigger'")
            nodes.insert(0, {"refid": r.trigger, "role": _TRIGGER})
        return {"id": r.id, "infons": infons, "nodes": nodes}
