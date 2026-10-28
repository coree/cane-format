"""Writing rendered output, choosing file names, and checking option values."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from os import PathLike
from typing import IO

from cane_format.errors import UnrepresentableError
from cane_format.model import Document

Destination = str | PathLike[str] | IO[str]

_UNSAFE = re.compile(r"[/\\:\x00]|^\.{1,2}$|^\s|\s$")


def write_text(destination: Destination, content: str) -> None:
    """Write fully rendered content to a path or an open text stream."""
    if isinstance(destination, str | PathLike):
        with open(destination, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    else:
        destination.write(content)


def file_names(docs: Sequence[Document], suffix: str) -> list[str]:
    """One safe, unique file name per document, from its ID.

    Raises before anything is written: a missing ID, an ID that is not a plain file name
    (separators, ``..``, ``:``), or two IDs that would collide on a case-insensitive file system.
    """
    names: list[str] = []
    seen: dict[str, str] = {}
    for n, doc in enumerate(docs, 1):
        if not doc.id:
            raise UnrepresentableError(f"document {n} has no id to name its file")
        if _UNSAFE.search(doc.id):
            raise UnrepresentableError(f"document id {doc.id!r} is not a safe file name")
        key = doc.id.casefold()
        if key in seen:
            raise UnrepresentableError(
                f"document ids {seen[key]!r} and {doc.id!r} would write the same file"
            )
        seen[key] = doc.id
        names.append(doc.id + suffix)
    return names


def check(name: str, value: object, allowed: Collection[str]) -> None:
    """Raise ``ValueError`` for an option value outside ``allowed``."""
    if value not in allowed:
        options = ", ".join(repr(a) for a in allowed)
        raise ValueError(f"{name}={value!r} is not one of {options}")
