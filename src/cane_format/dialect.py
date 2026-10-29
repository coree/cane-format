"""The CANE surface vocabulary (``Dialect``) and the four CANE variants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Variant(str, Enum):
    """The four CANE variants: one grammar, two switches (several parts, anchors)."""

    BASE = "base"
    DISCO = "disco"
    CONTEXT = "context"
    FULL = "full"

    @property
    def multi_part(self) -> bool:
        """Whether a record may have several parts (discontinuous entities)."""
        return self in (Variant.DISCO, Variant.FULL)

    @property
    def anchored(self) -> bool:
        """Whether every part carries a context anchor."""
        return self in (Variant.CONTEXT, Variant.FULL)


@dataclass(frozen=True, slots=True, kw_only=True)
class Dialect:
    """Every literal token of the CANE surface form. ``ENGLISH`` is the default.

    Attributes:
        header: First line of every non-empty output.
        empty: The whole output when there are no entities.
        quote_open: Delimiter opening a part or anchor.
        quote_close: Delimiter closing a part or anchor.
        copula_singular: Verb for one part (``is``).
        copula_plural: Verb for several parts (``are``).
        articles: Accepted articles; the formatter (`dumps`) always writes the first.
        anchor_intro: Phrase introducing the anchors (``found in``).
        part_connective: Joins parts (``and``).
        anchor_connective: Joins anchors (``and``).
        record_separator: Separates records.
        handle_prefix: Prefix of record handles (``T`` as in ``T1``).
    """

    header: str = "Entities:"
    empty: str = "NONE"
    quote_open: str = "`"
    quote_close: str = "`"
    copula_singular: str = "is"
    copula_plural: str = "are"
    articles: tuple[str, ...] = ("a", "an")
    anchor_intro: str = "found in"
    part_connective: str = "and"
    anchor_connective: str = "and"
    record_separator: str = "\n"
    handle_prefix: str = "T"
    _patterns: _Patterns = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        words = (
            self.header,
            self.empty,
            self.quote_open,
            self.quote_close,
            self.copula_singular,
            self.copula_plural,
            self.anchor_intro,
            self.part_connective,
            self.anchor_connective,
            self.record_separator,
            self.handle_prefix,
            *self.articles,
        )
        if not self.articles or not all(isinstance(w, str) and w for w in words):
            raise ValueError("every dialect token must be a non-empty string")
        object.__setattr__(self, "_patterns", _Patterns(self))


def _words(phrase: str) -> str:
    return r"\s+".join(re.escape(w) for w in phrase.split())


class _Patterns:
    """Regular expressions compiled once per dialect."""

    def __init__(self, d: Dialect) -> None:
        qo, qc = re.escape(d.quote_open), re.escape(d.quote_close)
        copula = "|".join(_words(c) for c in (d.copula_singular, d.copula_plural))
        article = "|".join(_words(a) for a in d.articles)
        self.record = re.compile(
            rf"(?:(?P<handle>{re.escape(d.handle_prefix)}\d+)\s+)?"
            rf"(?P<parts>{qo}.*{qc})\s+(?:{copula})"
            rf"(?:\s+(?P<article>{article}))?\s+(?P<label>\S+)"
            rf"(?:\s+{_words(d.anchor_intro)}\s+(?P<anchors>{qo}.*{qc}))?",
            re.DOTALL,
        )
        self.part_split = re.compile(rf"{qc}\s+{_words(d.part_connective)}\s+{qo}")
        self.anchor_split = re.compile(rf"{qc}\s+{_words(d.anchor_connective)}\s+{qo}")
        self.articles = frozenset(d.articles)
        self.list_marker = re.compile(r"(?:[-*•]|\d+[.)])\s+")


ENGLISH = Dialect()
