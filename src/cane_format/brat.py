"""brat standoff format: a ``.txt`` file and an ``.ann`` file per document.

Supported annotation lines: ``T`` (text-bound), ``E`` (event), ``R`` (relation), ``*``
(equivalence), ``A`` and legacy ``M`` (attribute), ``N`` (normalisation) and ``#`` (note).
"""

from __future__ import annotations

import re
import warnings
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import replace
from os import PathLike
from pathlib import Path
from typing import Any, Literal

from cane_format._offsets import OffsetMap, OffsetUnit
from cane_format._output import document_name, file_names
from cane_format._verify import covers, unit_hint
from cane_format.errors import (
    CaneFormatError,
    IntegrityError,
    LossyConversionWarning,
    UnrepresentableError,
)
from cane_format.model import Concept, Document, Entity, Member, Relation, Span

Verify = Literal["raise", "warn", "off"]
NOTES_KEY = "brat_notes"
"""Metadata key holding a target's ``#`` notes as a tuple of ``(type, text)`` pairs."""

_WHITESPACE = re.compile(r"\s+")


def read_brat(
    path: str | PathLike[str], *, verify: Verify = "raise", offset_unit: OffsetUnit = "codepoint"
) -> list[Document]:
    """Read a brat directory, or one document given its ``.txt`` or ``.ann`` path."""
    return list(iter_brat(path, verify=verify, offset_unit=offset_unit))


def iter_brat(
    path: str | PathLike[str], *, verify: Verify = "raise", offset_unit: OffsetUnit = "codepoint"
) -> Iterator[Document]:
    """Like ``read_brat``, yielding documents one at a time (sorted by file name)."""
    path = Path(path)
    texts = sorted(path.glob("*.txt")) if path.is_dir() else [path.with_suffix(".txt")]
    for txt in texts:
        ann = txt.with_suffix(".ann")
        if not ann.exists():
            raise CaneFormatError(f"{txt}: no matching {ann.name}")
        yield parse_brat(
            _read(txt), _read(ann), id=txt.stem, verify=verify, offset_unit=offset_unit
        )


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def parse_brat(
    text: str,
    ann: str,
    *,
    id: str | None = None,
    verify: Verify = "raise",
    offset_unit: OffsetUnit = "codepoint",
) -> Document:
    """Build a document from the contents of a ``.txt`` and an ``.ann`` file.

    Args:
        text: The ``.txt`` content, unchanged (read with ``newline=''``).
        ann: The ``.ann`` content.
        id: The document ID, usually the file stem.
        verify: Check every text-bound annotation against its stored text: ``"raise"`` an
            ``IntegrityError`` on mismatch, ``"warn"``, or ``"off"``.
        offset_unit: The unit the offsets count in.
    """
    reader = _Reader(text, id, verify, offset_unit)
    for n, line in enumerate(ann.splitlines(), 1):
        if line.strip():
            reader.line(line, n)
    return reader.document()


class _Reader:
    def __init__(self, text: str, doc_id: str | None, verify: Verify, unit: OffsetUnit) -> None:
        self.text, self.doc_id, self.verify, self.unit = text, doc_id, verify, unit
        self.offsets = OffsetMap(text, unit)
        self.entities: list[Entity] = []
        self.relations: list[Relation] = []
        self.concepts: dict[str, list[Concept]] = defaultdict(list)
        self.attributes: dict[str, dict[str, str | bool]] = defaultdict(dict)
        self.notes: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def fail(self, n: int, message: str) -> CaneFormatError:
        return CaneFormatError(f"{self.doc_id or 'document'}, .ann line {n}: {message}")

    def line(self, line: str, n: int) -> None:
        fields = line.split("\t")
        if len(fields) < 2:
            raise self.fail(n, f"expected tab-separated fields: {line!r}")
        key, body = fields[0], fields[1].split()
        rest = fields[2] if len(fields) > 2 else None
        kind = key[:1]
        try:
            if kind == "T":
                self.text_bound(key, fields[1], rest, n)
            elif kind == "E":
                event_type, trigger = body[0].split(":", 1)
                self.relations.append(
                    Relation(type=event_type, trigger=trigger, id=key, members=_members(body[1:]))
                )
            elif kind == "R":
                self.relations.append(Relation(type=body[0], id=key, members=_members(body[1:])))
            elif kind == "*":
                self.relations.append(Relation(type=body[0], members=[Member(r) for r in body[1:]]))
            elif kind in "AM":
                name, target, *value = body
                if name in self.attributes[target]:
                    raise self.fail(n, f"attribute {name} set twice on {target}")
                self.attributes[target][name] = " ".join(value) if value else True
            elif kind == "N":
                norm_type, target, ref = body
                if norm_type != "Reference":
                    raise self.fail(n, f"unsupported normalisation type {norm_type!r}")
                self.concepts[target].append(Concept(id=ref, name=rest or None))
            elif kind == "#":
                note_type, target = body
                self.notes[target].append((note_type, rest or ""))
            else:
                raise self.fail(n, f"unsupported annotation line {line!r}")
        except (ValueError, IndexError) as err:
            raise self.fail(n, f"cannot read {line!r} ({err})") from err

    def text_bound(self, key: str, spec: str, stored: str | None, n: int) -> None:
        label, _, offsets = spec.partition(" ")
        raw = [tuple(int(x) for x in frag.split()) for frag in offsets.split(";")]
        if not raw or any(len(r) != 2 for r in raw):
            raise ValueError("offsets must be start-end pairs")
        try:
            spans = [
                Span(self.offsets.to_codepoint(s), self.offsets.to_codepoint(e)) for s, e in raw
            ]
        except KeyError as err:
            raise IntegrityError(
                f"{self.doc_id}, .ann line {n}: offset {err} falls inside a character "
                f"({self.unit} offsets)"
            ) from None
        if stored is not None and self.verify != "off" and not covers(self.text, spans, stored):
            self.mismatch(n, key, spans, stored, raw)
        self.entities.append(Entity(spans=spans, label=label, id=key))

    def mismatch(
        self, n: int, key: str, spans: list[Span], stored: str, raw: list[tuple[int, ...]]
    ) -> None:
        found = " ".join(self.text[s.start : s.end] for s in spans)
        message = (
            f"{self.doc_id}, .ann line {n}: {key} stores {stored!r} but the text at its "
            f"{self.unit} offsets reads {found!r}"
        ) + unit_hint(self.text, [(r[0], r[1]) for r in raw], stored, self.unit)
        if self.verify == "raise":
            raise IntegrityError(message)
        warnings.warn(message, stacklevel=5)

    def document(self) -> Document:
        def attach(item: Any) -> Any:
            changes: dict[str, Any] = {}
            if item.id in self.attributes:
                changes["attributes"] = self.attributes.pop(item.id)
            if item.id in self.notes:
                changes["metadata"] = {NOTES_KEY: tuple(self.notes.pop(item.id))}
            if isinstance(item, Entity) and item.id in self.concepts:
                changes["concepts"] = tuple(self.concepts.pop(item.id))
            return replace(item, **changes) if changes else item

        entities = [attach(e) for e in self.entities]
        relations = [attach(r) for r in self.relations]
        dangling = sorted({*self.attributes, *self.notes, *self.concepts})
        if dangling:
            raise CaneFormatError(
                f"{self.doc_id}: attributes, notes or normalisations point at unknown or "
                f"unsupported targets: {', '.join(dangling)}"
            )
        try:
            return Document(
                text=self.text, entities=tuple(entities), relations=tuple(relations), id=self.doc_id
            )
        except ValueError as err:
            raise CaneFormatError(f"{self.doc_id}: {err}") from err


def _members(tokens: Iterable[str]) -> list[Member]:
    members = []
    for token in tokens:
        role, ref = token.split(":", 1)
        members.append(Member(ref, role))
    return members


# --- writing -------------------------------------------------------------------------------


def write_brat(
    docs: Iterable[Document],
    directory: str | PathLike[str],
    *,
    offset_unit: OffsetUnit = "codepoint",
    lossy: Literal["warn", "ignore"] = "warn",
) -> None:
    """Write each document as ``<id>.txt`` and ``<id>.ann`` into ``directory``.

    Every file name is checked and every document rendered before anything is written, so an
    error leaves no partial output.
    """
    docs = list(docs)
    stems = file_names(docs, "")
    rendered = [format_brat(doc, offset_unit=offset_unit, lossy=lossy) for doc in docs]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for stem, doc, ann in zip(stems, docs, rendered, strict=True):
        for suffix, content in ((".txt", doc.text), (".ann", ann)):
            with open(directory / f"{stem}{suffix}", "w", encoding="utf-8", newline="") as f:
                f.write(content)


def format_brat(
    doc: Document,
    *,
    offset_unit: OffsetUnit = "codepoint",
    lossy: Literal["warn", "ignore"] = "warn",
) -> str:
    """The ``.ann`` content for a document. The text is written unchanged as the ``.txt``.

    Relations map to line kinds by structure: a trigger makes an ``E`` line, members without
    roles a ``*`` line, two members with roles an ``R`` line. IDs that do not fit brat's
    ``T``/``E``/``R`` numbering are renumbered consistently.
    """
    offsets = OffsetMap(doc.text, offset_unit)
    kinds = {r.id: _relation_kind(r) for r in doc.relations}
    ids = _brat_ids(doc, kinds)
    dropped: list[str] = []
    lines: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for e in doc.entities:
        if e.label is None or _WHITESPACE.search(e.label) or not e.label:
            raise UnrepresentableError(f"entity {e.id}: brat needs a one-token label")
        frags = ";".join(
            f"{offsets.from_codepoint(s.start)} {offsets.from_codepoint(s.end)}" for s in e.spans
        )
        covered = " ".join(re.sub(r"[\t\r\n]", " ", p) for p in e.parts(doc.text))
        new = ids[e.id]
        lines["T"].append((_number(new), f"{new}\t{e.label} {frags}\t{covered}"))

    for r in doc.relations:
        kind = kinds[r.id]
        members = " ".join(f"{m.role}:{ids[m.refid]}" for m in r.members)
        if kind == "E":
            body = f"{r.type}:{ids[r.trigger]}" + (f" {members}" if members else "")
            lines["E"].append((_number(ids[r.id]), f"{ids[r.id]}\t{body}"))
        elif kind == "R":
            lines["R"].append((_number(ids[r.id]), f"{ids[r.id]}\t{r.type} {members}"))
        else:
            refs = " ".join(ids[m.refid] for m in r.members)
            lines["*"].append((len(lines["*"]), f"*\t{r.type} {refs}"))

    counters = {"A": 0, "N": 0, "#": 0}

    def numbered(kind: str, body: str) -> None:
        counters[kind] += 1
        lines[kind].append((counters[kind], f"{kind}{counters[kind]}\t{body}"))

    items: tuple[Entity | Relation, ...] = (*doc.entities, *doc.relations)
    for item in items:
        target = ids[item.id]
        for name, value in item.attributes.items():
            if value is False:
                dropped.append(f"false attribute {name} on {item.id}")
            elif value is True:
                numbered("A", f"{name} {target}")
            elif _WHITESPACE.search(f"{name}{value}") or not value:
                raise UnrepresentableError(f"attribute {name}={value!r} on {item.id}")
            else:
                numbered("A", f"{name} {target} {value}")
        for concept in getattr(item, "concepts", ()):
            if _WHITESPACE.search(concept.id):
                raise UnrepresentableError(f"concept id {concept.id!r} contains whitespace")
            if concept.source is not None:
                dropped.append(f"source of concept {concept.id}")
            name = f"\t{concept.name}" if concept.name is not None else ""
            numbered("N", f"Reference {target} {concept.id}{name}")
        for note_type, note in item.metadata.get(NOTES_KEY, ()):
            numbered("#", f"{note_type} {target}\t{note}")
        if set(item.metadata) - {NOTES_KEY}:
            dropped.append(f"metadata of {item.id}")

    if doc.segments:
        dropped.append(f"{len(doc.segments)} segments")
    if doc.metadata:
        dropped.append("document metadata")
    if dropped and lossy == "warn":
        warnings.warn(
            f"{document_name(doc)}: brat cannot carry: " + "; ".join(dropped),
            LossyConversionWarning,
            stacklevel=2,
        )
    out = [line for kind in "TER*AN#" for _, line in sorted(lines[kind], key=lambda x: x[0])]
    return "".join(f"{line}\n" for line in out)


def _relation_kind(r: Relation) -> str:
    roles = [m.role for m in r.members]
    if r.trigger is not None:
        if None in roles:
            raise UnrepresentableError(f"event {r.id}: every argument needs a role in brat")
        return "E"
    if len(roles) >= 2 and all(role is None for role in roles):
        return "*"
    if len(roles) == 2 and None not in roles:
        return "R"
    raise UnrepresentableError(
        f"relation {r.id}: brat holds two roled members (R), roleless sets (*) or events (E)"
    )


def _number(brat_id: str) -> int:
    return int(brat_id[1:])


def _brat_ids(doc: Document, kinds: dict[str | None, str]) -> dict[str | None, str]:
    """Keep IDs that fit brat, renumber the rest with the next free numbers."""
    wanted = [(e.id, "T") for e in doc.entities] + [
        (r.id, kinds[r.id]) for r in doc.relations if kinds[r.id] != "*"
    ]
    ids: dict[str | None, str] = {}
    used = {i for i, prefix in wanted if i and re.fullmatch(rf"{prefix}\d+", i)}
    for old, prefix in wanted:
        if old in used and old not in ids.values():
            ids[old] = old
            continue
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        ids[old] = f"{prefix}{n}"
        used.add(ids[old])
    for r in doc.relations:
        ids.setdefault(r.id, "*")
    return ids
