"""Few-shot prompts for CANE, in the layout used by the CANE paper."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from cane_format._formatter import OnUnrepresentable, dumps
from cane_format.dialect import ENGLISH, Dialect, Variant
from cane_format.model import Document

_IMPORTANT = (
    "Important: Output only the final answer in the required format. All predictions must "
    "exactly match the input verbatim. Do not alter capitalization, do not add or remove "
    "whitespace, and do not change punctuation. Do not add explanations, commentary, markdown, "
    "or any extra text."
)


def guideline(
    variant: Variant | str,
    *,
    context: int = 1,
    handles: bool = False,
    dialect: Dialect = ENGLISH,
) -> str:
    """The format instructions for one CANE variant, worded with the dialect's tokens."""
    v = Variant(variant)
    d = dialect

    def q(word: str) -> str:
        return d.quote_open + word + d.quote_close

    one = f"{q('entity')} {d.copula_singular} {d.articles[0]} TYPE"
    words = "word" if context == 1 else f"{context} words"
    lines = [
        f"Start the output with the line '{d.header}', then write one line per entity.",
        f"Each line is {one}: the entity text copied verbatim between {d.quote_open} and "
        f"{d.quote_close}, then '{d.copula_singular} {d.articles[0]}' and the entity type.",
    ]
    if v.anchored:
        lines.append(
            f"After the type, write '{d.anchor_intro}' and a snippet copied verbatim from the "
            f"input between {d.quote_open} and {d.quote_close}: the entity with the "
            f"neighbouring {words} on each side."
        )
    if v.multi_part:
        parts = f"{q('part1')} {d.part_connective} {q('part2')}"
        line = (
            f"An entity made of separate parts is written as {parts} "
            f"{d.copula_plural} {d.articles[0]} TYPE, with the parts in text order"
        )
        if v.anchored:
            line += f" and one snippet per part, joined by '{d.anchor_connective}'"
        lines.append(line + ".")
    lines += [
        "List the entities in the order they appear in the text. Write one line per "
        "occurrence, also when the same text occurs again; nested and overlapping entities "
        "get their own lines.",
    ]
    if handles:
        lines.append(
            f"Begin each line with an identifier {d.handle_prefix}1, "
            f"{d.handle_prefix}2, … in order."
        )
    lines.append(f"If there are no entities, output only: {d.empty}")
    return " ".join(lines)


def build_prompt(
    text: str,
    *,
    examples: Sequence[Document],
    variant: Variant | str,
    labels: Iterable[str] | None = None,
    context: int = 1,
    handles: bool = False,
    on_unrepresentable: OnUnrepresentable = "raise",
    lossy: Literal["warn", "ignore"] = "warn",
    dialect: Dialect = ENGLISH,
) -> str:
    """A few-shot prompt asking a model to annotate ``text`` in CANE.

    The layout follows the CANE paper: task, entity types, format and guideline, the
    'Important' instruction, the worked examples, then the input. Examples are written with
    ``dumps`` and the same options, so the prompt teaches exactly what ``loads`` expects.

    Args:
        text: The text to annotate.
        examples: Annotated documents shown as few-shot examples.
        variant: The CANE variant.
        labels: The entity types in the order to list them (a set is sorted); by default
            the examples' labels, sorted. Required when there are no examples.
        context, handles, on_unrepresentable, lossy, dialect: As for ``dumps``.
    """
    v = Variant(variant)
    if labels is None:
        names = sorted({e.label for d in examples for e in d.entities if e.label is not None})
    elif isinstance(labels, (set, frozenset)):
        names = sorted(labels)  # sets have no stable order; prompts must be reproducible
    else:
        names = list(labels)
    if not names:
        raise ValueError("build_prompt needs labels= or examples with labelled entities")
    shots = [
        f"Input: {d.text}\nOutput:\n"
        + dumps(
            d,
            variant=v,
            context=context,
            handles=handles,
            on_unrepresentable=on_unrepresentable,
            lossy=lossy,
            dialect=dialect,
        )
        for d in examples
    ]
    return "\n\n".join(
        [
            "Task: Named Entity Recognition",
            "Entities: " + ", ".join(names),
            f"Format: CANE-{v.value.title()}\n"
            f"Guidelines: {guideline(v, context=context, handles=handles, dialect=dialect)}",
            _IMPORTANT,
            *(["Examples:", "\n\n".join(shots)] if shots else []),
            f"---\nInput: {text}\nOutput:",
        ]
    )
