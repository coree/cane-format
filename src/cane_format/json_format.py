"""Offset JSON: a lossless serialisation of the document model.

One document is one JSON object; a collection is JSON Lines (one object per line). Offsets are
code points, spans are ``[start, end]`` pairs. Empty and unset fields are omitted.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from os import PathLike
from pathlib import Path
from typing import Any

from cane_format._output import Destination, document_name, write_text
from cane_format.errors import CaneFormatError, UnrepresentableError
from cane_format.model import Concept, Document, Entity, Member, Relation, Segment, Span

FORMAT_VERSION = 1


def read_json(path: str | PathLike[str]) -> list[Document]:
    """Read a JSON Lines file, a single JSON document, or a JSON array of documents."""
    return list(iter_json(path))


def iter_json(path: str | PathLike[str]) -> Iterator[Document]:
    """Like ``read_json``, yielding documents one at a time."""
    content = Path(path).read_text(encoding="utf-8")
    try:
        whole = json.loads(content)
    except json.JSONDecodeError:
        for n, line in enumerate(content.splitlines(), 1):
            if line.strip():
                yield _parse_object(_loads(line, f"{path}, line {n}"), f"{path}, line {n}")
        return
    if isinstance(whole, list):
        for i, item in enumerate(whole):
            yield _parse_object(item, f"{path}, item {i}")
    else:
        yield _parse_object(whole, str(path))


def write_json(docs: Iterable[Document], destination: Destination) -> None:
    """Write documents as JSON Lines, one per line, to a path or an open text stream."""
    write_text(destination, "".join(format_json(doc) + "\n" for doc in docs))


def parse_json(content: str) -> Document:
    """Build a document from one JSON object."""
    return _parse_object(_loads(content, "input"), "input")


def format_json(doc: Document, *, indent: int | None = None) -> str:
    """One document as a JSON object (on one line unless ``indent`` is given)."""
    obj: dict[str, Any] = {"format_version": FORMAT_VERSION}
    _put(obj, "id", doc.id)
    obj["text"] = doc.text
    obj["entities"] = [_entity(e) for e in doc.entities]
    _put(obj, "relations", [_relation(r) for r in doc.relations])
    _put(obj, "segments", [_segment(s) for s in doc.segments])
    _put(obj, "metadata", dict(doc.metadata))
    try:
        return json.dumps(obj, ensure_ascii=False, indent=indent)
    except TypeError as err:
        raise UnrepresentableError(f"{document_name(doc)}: metadata is not JSON: {err}") from err


# --- writing ------------------------------------------------------------------------------


def _put(obj: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, [], {}):
        obj[key] = value


def _entity(e: Entity) -> dict[str, Any]:
    obj: dict[str, Any] = {"id": e.id}
    _put(obj, "label", e.label)
    obj["spans"] = [list(s) for s in e.spans]
    _put(obj, "concepts", [_concept(c) for c in e.concepts])
    _put(obj, "attributes", dict(e.attributes))
    _put(obj, "metadata", dict(e.metadata))
    return obj


def _concept(c: Concept) -> dict[str, Any]:
    obj: dict[str, Any] = {"id": c.id}
    _put(obj, "source", c.source)
    _put(obj, "name", c.name)
    return obj


def _relation(r: Relation) -> dict[str, Any]:
    obj: dict[str, Any] = {"id": r.id, "type": r.type}
    _put(obj, "trigger", r.trigger)
    obj["members"] = [
        {"refid": m.refid} if m.role is None else {"refid": m.refid, "role": m.role}
        for m in r.members
    ]
    _put(obj, "attributes", dict(r.attributes))
    _put(obj, "metadata", dict(r.metadata))
    return obj


def _segment(s: Segment) -> dict[str, Any]:
    obj: dict[str, Any] = {"kind": s.kind, "span": list(s.span)}
    _put(obj, "id", s.id)
    _put(obj, "metadata", dict(s.metadata))
    return obj


# --- reading ------------------------------------------------------------------------------


def _loads(content: str, where: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as err:
        raise CaneFormatError(f"{where}: not valid JSON ({err})") from err


def _parse_object(obj: Any, where: str) -> Document:
    try:
        if not isinstance(obj, dict):
            raise TypeError("expected a JSON object")
        version = obj.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported format_version {version!r} (expected 1)")
        return Document(
            text=obj["text"],
            id=obj.get("id"),
            entities=[
                Entity(
                    spans=[Span(*s) for s in e["spans"]],
                    label=e.get("label"),
                    id=e.get("id"),
                    concepts=[
                        Concept(id=c["id"], source=c.get("source"), name=c.get("name"))
                        for c in e.get("concepts", ())
                    ],
                    attributes=e.get("attributes"),
                    metadata=_frozen(e.get("metadata")),
                )
                for e in obj.get("entities", ())
            ],
            relations=[
                Relation(
                    type=r["type"],
                    members=[Member(m["refid"], m.get("role")) for m in r.get("members", ())],
                    trigger=r.get("trigger"),
                    id=r.get("id"),
                    attributes=r.get("attributes"),
                    metadata=_frozen(r.get("metadata")),
                )
                for r in obj.get("relations", ())
            ],
            segments=[
                Segment(
                    kind=s["kind"],
                    span=Span(*s["span"]),
                    id=s.get("id"),
                    metadata=_frozen(s.get("metadata")),
                )
                for s in obj.get("segments", ())
            ],
            metadata=_frozen(obj.get("metadata")),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise CaneFormatError(f"{where}: {type(err).__name__}: {err}") from err


def _frozen(value: Any) -> Any:
    """JSON arrays become tuples, so metadata reads back as the immutable values it was."""
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, dict):
        return {k: _frozen(v) for k, v in value.items()}
    return value
