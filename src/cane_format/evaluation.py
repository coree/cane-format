"""Handing documents to nervaluate-disco (https://github.com/coree/nervaluate-disco).

The CANE paper evaluates with nervaluate-disco: strict matching on label and character spans,
discontinuous and overlapping entities supported. It is not a dependency of this package.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from cane_format.errors import UnrepresentableError
from cane_format.model import Document


def to_nervaluate(
    docs: Iterable[Document], *, unlabelled: Literal["raise", "skip"] = "raise"
) -> list[dict[str, Any]]:
    """Documents in nervaluate-disco's span format, one dict per document.

    Pass gold and predicted documents in the same order::

        from nervaluate import Evaluator
        true = cane.to_nervaluate(gold_docs)
        pred = cane.to_nervaluate(result.document for result in results)
        Evaluator(true, pred, tags=labels).evaluate()

    Args:
        docs: The documents.
        unlabelled: Entities without a label cannot be evaluated: ``"raise"`` or ``"skip"``.
    """
    out = []
    for doc in docs:
        entities = []
        for e in doc.entities:
            if e.label is None:
                if unlabelled == "raise":
                    raise UnrepresentableError(f"entity {e.id} has no label to evaluate")
                continue
            entities.append(
                {
                    "spans": [(s.start, s.end) for s in e.spans],
                    "label": e.label,
                    "text": " ".join(e.parts(doc.text)),
                }
            )
        out.append({"text": doc.text, "entities": entities})
    return out
