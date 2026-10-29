"""The document model: text with entities, relations and segments over character spans.

All classes are immutable. Offsets are 0-based Python code points, end-exclusive.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from itertools import pairwise
from types import MappingProxyType
from typing import Any, NamedTuple, TypeVar


def _set(obj: object, **values: Any) -> None:
    for name, value in values.items():
        object.__setattr__(obj, name, value)


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


class _SpanBase(NamedTuple):
    start: int
    end: int


class Span(_SpanBase):
    """A contiguous character range ``text[start:end]``. Requires ``0 <= start < end``."""

    __slots__ = ()

    def __new__(cls, start: int, end: int) -> Span:
        for value in (start, end):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"span offsets must be int, got {value!r}")
        if not 0 <= start < end:
            raise ValueError(f"invalid span ({start}, {end}): requires 0 <= start < end")
        return super().__new__(cls, start, end)

    def __repr__(self) -> str:
        return f"Span({self.start}, {self.end})"


def _to_spans(spans: Iterable[tuple[int, int]]) -> tuple[Span, ...]:
    return tuple(sorted(s if isinstance(s, Span) else Span(*s) for s in spans))


@dataclass(frozen=True, slots=True, kw_only=True)
class Concept:
    """A link from an entity to a concept in a vocabulary.

    Attributes:
        id: The identifier exactly as the source wrote it (``"MESH:D008687"``); never parsed.
        source: The vocabulary, when the source names it separately.
        name: The concept's preferred name, when the source gives one.
    """

    id: str
    source: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True, init=False)
class Entity:
    """A labelled annotation over one or more spans (more than one = discontinuous).

    Equality and hashing use ``(label, spans)`` only: two entities over the same characters with
    the same label are the same entity, whatever their IDs, concepts or attributes.
    """

    spans: tuple[Span, ...]
    label: str | None = None
    id: str | None = field(default=None, compare=False)
    concepts: tuple[Concept, ...] = field(default=(), compare=False)
    attributes: Mapping[str, str | bool] = field(default_factory=_empty_mapping, compare=False)
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping, compare=False)

    def __init__(
        self,
        *,
        spans: Iterable[tuple[int, int]],
        label: str | None = None,
        id: str | None = None,
        concepts: Iterable[Concept] = (),
        attributes: Mapping[str, str | bool] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        sorted_spans = _to_spans(spans)
        if not sorted_spans:
            raise ValueError("an entity needs at least one span")
        for a, b in pairwise(sorted_spans):
            if a.end > b.start:
                raise ValueError(f"spans of one entity overlap: {a} and {b}")
        _set(
            self,
            spans=sorted_spans,
            label=label,
            id=id,
            concepts=tuple(concepts),
            attributes=_frozen_mapping(attributes),
            metadata=_frozen_mapping(metadata),
        )

    @property
    def start(self) -> int:
        return self.spans[0].start

    @property
    def end(self) -> int:
        return self.spans[-1].end

    @property
    def hull(self) -> Span:
        """The smallest single span covering all parts, gaps included. Not the extent."""
        return Span(self.start, self.end)

    def parts(self, text: str) -> tuple[str, ...]:
        """The covered text of each span."""
        return tuple(text[s.start : s.end] for s in self.spans)


class Member(NamedTuple):
    """A participant in a relation: the ID of an entity or relation, and its role.

    ``role=None`` marks an unordered participant (e.g. in an equivalence set).
    """

    refid: str
    role: str | None = None


def _member_key(member: Member) -> tuple[str, bool, str]:
    return (member.refid, member.role is not None, member.role or "")


@dataclass(frozen=True, slots=True, init=False, eq=False)
class Relation:
    """A relation, event or equivalence set over entities and relations.

    Attributes:
        type: The relation or event type.
        members: The participants. Their order is kept but not significant for equality.
        trigger: ID of the entity whose text expresses the relation (event trigger, verb).
        id: Stable identifier; filled in by ``Document`` when missing.

    Equality uses type, trigger and members as a multiset. Symmetry needs no flag: members
    without distinguishing roles are interchangeable.
    """

    type: str
    members: tuple[Member, ...] = ()
    trigger: str | None = None
    id: str | None = None
    attributes: Mapping[str, str | bool] = field(default_factory=_empty_mapping)
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)

    def __init__(
        self,
        *,
        type: str,
        members: Iterable[Member | tuple[str] | tuple[str, str | None]] = (),
        trigger: str | None = None,
        id: str | None = None,
        attributes: Mapping[str, str | bool] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        as_members = tuple(m if isinstance(m, Member) else Member(*m) for m in members)
        if not as_members and trigger is None:
            raise ValueError("a relation needs members or a trigger")
        _set(
            self,
            type=type,
            members=as_members,
            trigger=trigger,
            id=id,
            attributes=_frozen_mapping(attributes),
            metadata=_frozen_mapping(metadata),
        )

    def _key(self) -> tuple[str, str | None, tuple[Member, ...]]:
        return (self.type, self.trigger, tuple(sorted(self.members, key=_member_key)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Relation):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


@dataclass(frozen=True, slots=True, init=False)
class Segment:
    """A typed region of the text, such as a passage, sentence or token."""

    kind: str
    span: Span
    id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping, compare=False)

    def __init__(
        self,
        *,
        kind: str,
        span: tuple[int, int],
        id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        as_span = span if isinstance(span, Span) else Span(*span)
        _set(self, kind=kind, span=as_span, id=id, metadata=_frozen_mapping(metadata))


_T = TypeVar("_T", "Entity", "Relation")


@dataclass(frozen=True, slots=True, init=False)
class Document:
    """A text with its annotations.

    On construction, missing entity IDs become ``T<n>`` and missing relation IDs ``R<n>`` (the
    next free numbers), and the document is validated: every span and segment lies inside the
    text, IDs are unique, and every member and trigger refers to something that exists.
    """

    text: str
    entities: tuple[Entity, ...] = ()
    relations: tuple[Relation, ...] = ()
    segments: tuple[Segment, ...] = ()
    id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping, compare=False)

    def __init__(
        self,
        *,
        text: str,
        entities: Iterable[Entity] = (),
        relations: Iterable[Relation] = (),
        segments: Iterable[Segment] = (),
        id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        entities, relations = tuple(entities), tuple(relations)
        ids = [e.id for e in entities] + [r.id for r in relations]
        counts = Counter(i for i in ids if i is not None)
        duplicates = sorted(i for i, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate IDs: {', '.join(duplicates)}")
        used = set(counts)
        start: dict[str, int] = {}
        _set(
            self,
            text=text,
            entities=tuple(_with_id(e, "T", used, start) for e in entities),
            relations=tuple(_with_id(r, "R", used, start) for r in relations),
            segments=tuple(segments),
            id=id,
            metadata=_frozen_mapping(metadata),
        )
        self._validate()

    def _validate(self) -> None:
        size = len(self.text)
        for entity in self.entities:
            if entity.end > size:
                raise ValueError(f"entity {entity.id} ends at {entity.end}, beyond text ({size})")
        for segment in self.segments:
            if segment.span.end > size:
                raise ValueError(f"segment {segment.span} lies beyond the text ({size})")
        entity_ids = {e.id for e in self.entities}
        all_ids = entity_ids | {r.id for r in self.relations}
        for relation in self.relations:
            if relation.trigger is not None and relation.trigger not in entity_ids:
                raise ValueError(f"relation {relation.id}: trigger {relation.trigger} not found")
            for member in relation.members:
                if member.refid not in all_ids:
                    raise ValueError(f"relation {relation.id}: member {member.refid} not found")

    def entity(self, id: str) -> Entity:
        """Look up an entity by ID."""
        for entity in self.entities:
            if entity.id == id:
                return entity
        raise KeyError(id)


def _with_id(item: _T, prefix: str, used: set[str], start: dict[str, int]) -> _T:
    """``item`` with the next free ID ``prefix<n>`` if it has none.

    ``start`` remembers where the last search for ``prefix`` stopped: IDs are only ever added,
    so no smaller number becomes free again.
    """
    if item.id is not None:
        return item
    n = start.get(prefix, 1)
    while f"{prefix}{n}" in used:
        n += 1
    new_id = f"{prefix}{n}"
    used.add(new_id)
    start[prefix] = n + 1
    return replace(item, id=new_id)
