"""cane-format: write, parse and convert CANE, a natural-language output format for LLM-based NER.

Usage::

    import cane_format as cane

    prompt_example = cane.dumps(doc, variant="full")
    result = cane.loads(model_output, text=doc.text, variant="full")
    result.entities, result.issues
"""

from cane_format._parser import ParseOptions, ParseResult, loads
from cane_format._writer import dumps
from cane_format.brat import format_brat, iter_brat, parse_brat, read_brat, write_brat
from cane_format.dialect import ENGLISH, Dialect, Variant
from cane_format.errors import (
    CaneFormatError,
    IntegrityError,
    IssueKind,
    LossyConversionWarning,
    ParseError,
    ParseIssue,
    UnrepresentableError,
)
from cane_format.json_format import format_json, iter_json, parse_json, read_json, write_json
from cane_format.model import Concept, Document, Entity, Member, Relation, Segment, Span

__all__ = [
    "ENGLISH",
    "CaneFormatError",
    "Concept",
    "Dialect",
    "Document",
    "Entity",
    "IntegrityError",
    "IssueKind",
    "LossyConversionWarning",
    "Member",
    "ParseError",
    "ParseIssue",
    "ParseOptions",
    "ParseResult",
    "Relation",
    "Segment",
    "Span",
    "UnrepresentableError",
    "Variant",
    "dumps",
    "format_brat",
    "format_json",
    "iter_brat",
    "iter_json",
    "loads",
    "parse_brat",
    "parse_json",
    "read_brat",
    "read_json",
    "write_brat",
    "write_json",
]
