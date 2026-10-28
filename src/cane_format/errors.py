"""Exceptions, the warning class, and parse issues reported as data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cane_format.model import Span


class CaneFormatError(Exception):
    """Base class of every exception raised by cane-format."""


class ParseError(CaneFormatError):
    """Raised by ``ParseResult.raise_for_errors()``; carries every issue of the parse."""

    def __init__(self, issues: tuple[ParseIssue, ...]) -> None:
        self.issues = issues
        lines = "\n".join(f"  {issue}" for issue in issues)
        super().__init__(f"{len(issues)} issue(s) while parsing CANE output:\n{lines}")


class IntegrityError(CaneFormatError):
    """A file's offsets do not reproduce the surface text it stores next to them."""


class UnrepresentableError(CaneFormatError):
    """A writer was asked to write something its target format cannot hold."""


class LossyConversionWarning(UserWarning):
    """Information was dropped because the target format cannot hold it."""


class IssueKind(str, Enum):
    """Closed vocabulary of problems found while parsing model output."""

    MALFORMED_LINE = "malformed_line"
    NOT_FOUND = "not_found"
    ANCHOR_NOT_FOUND = "anchor_not_found"
    PART_COUNT_MISMATCH = "part_count_mismatch"
    UNKNOWN_HANDLE = "unknown_handle"
    INVALID_LABEL = "invalid_label"
    INVALID_SPAN = "invalid_span"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseIssue:
    """One problem found while parsing model output.

    Attributes:
        kind: What went wrong.
        message: Human-readable explanation.
        line: The raw output line, if the issue belongs to one.
        line_no: 1-based line number in the model output.
        candidates: Spans that were considered, for debugging grounding decisions.
    """

    kind: IssueKind
    message: str
    line: str | None = None
    line_no: int | None = None
    candidates: tuple[Span, ...] = ()

    def __str__(self) -> str:
        where = f"line {self.line_no}: " if self.line_no is not None else ""
        return f"{where}{self.kind.value}: {self.message}"
