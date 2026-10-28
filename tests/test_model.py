from __future__ import annotations

import pytest

from cane_format import Document, Entity, Member, Relation, Segment, Span


def test_span_validates() -> None:
    assert Span(1, 3) == (1, 3)
    for bad in ((3, 3), (4, 2), (-1, 2)):
        with pytest.raises(ValueError):
            Span(*bad)
    with pytest.raises(TypeError):
        Span(True, 3)


def test_entity_sorts_and_validates_spans() -> None:
    e = Entity(spans=[(5, 7), (0, 2)], label="X")
    assert e.spans == (Span(0, 2), Span(5, 7))
    assert (e.start, e.end, e.hull) == (0, 7, Span(0, 7))
    assert e.parts("ab---cd") == ("ab", "cd")
    with pytest.raises(ValueError):
        Entity(spans=[], label="X")
    with pytest.raises(ValueError):
        Entity(spans=[(0, 3), (2, 5)], label="X")


def test_entity_identity_is_label_and_spans() -> None:
    a = Entity(spans=[(0, 2)], label="X", id="T1", attributes={"Negation": True})
    b = Entity(spans=[(0, 2)], label="X", id="T9")
    assert a == b and hash(a) == hash(b)
    assert a != Entity(spans=[(0, 2)], label="Y")
    assert Entity(spans=[(0, 2)]).label is None


def test_entity_is_immutable() -> None:
    e = Entity(spans=[(0, 2)], label="X", attributes={"a": True})
    with pytest.raises(AttributeError):
        e.label = "Y"  # type: ignore[misc]
    with pytest.raises(TypeError):
        e.attributes["a"] = False  # type: ignore[index]


def test_relation_equality_ignores_member_order_and_id() -> None:
    a = Relation(type="Equiv", members=[Member("T1"), Member("T2")], id="R1")
    b = Relation(type="Equiv", members=[Member("T2"), Member("T1")], id="R7")
    assert a == b and hash(a) == hash(b)
    roled = Relation(type="Bind", members=[Member("T1", "Arg1"), Member("T2", "Arg2")])
    assert roled != Relation(type="Bind", members=[Member("T1", "Arg2"), Member("T2", "Arg1")])
    with pytest.raises(ValueError):
        Relation(type="Empty")


def test_document_fills_missing_ids_without_touching_inputs() -> None:
    e1, e2 = Entity(spans=[(0, 1)], label="X"), Entity(spans=[(1, 2)], label="X", id="T1")
    d = Document(text="ab", entities=(e1, e2), relations=(Relation(type="R", members=[("T1",)]),))
    assert [e.id for e in d.entities] == ["T2", "T1"]
    assert d.relations[0].id == "R1"
    assert e1.id is None


def test_document_keeps_duplicate_annotations() -> None:
    d = Document(
        text="ab",
        entities=(
            Entity(spans=[(0, 1)], label="X", id="T1"),
            Entity(spans=[(0, 1)], label="X", id="T5"),
        ),
    )
    assert len(d.entities) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"entities": (Entity(spans=[(0, 9)], label="X"),)},
        {"segments": (Segment(kind="sentence", span=Span(0, 9)),)},
        {"entities": (Entity(spans=[(0, 1)], id="T1"), Entity(spans=[(1, 2)], id="T1"))},
        {"relations": (Relation(type="R", members=[("T9", "Arg1")]),)},
        {"relations": (Relation(type="E", trigger="T9"),)},
    ],
)
def test_document_validates(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Document(text="abc", **kwargs)  # type: ignore[arg-type]


def test_relation_may_reference_relation() -> None:
    d = Document(
        text="ab",
        entities=(
            Entity(spans=[(0, 1)], label="P", id="T1"),
            Entity(spans=[(1, 2)], label="Reg", id="T2"),
        ),
        relations=(
            Relation(type="Reg", trigger="T2", members=[("E2", "Theme")], id="E1"),
            Relation(type="Bind", trigger="T2", members=[("T1", "Theme")], id="E2"),
        ),
    )
    assert d.entity("T2").label == "Reg"
