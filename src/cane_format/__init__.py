"""cane-format: write, parse and convert CANE, a natural-language output format for LLM-based NER.

Usage::

    import cane_format as cane

    prompt_example = cane.dumps(doc, variant="full")
    result = cane.loads(model_output, text=doc.text, variant="full")
    result.entities, result.issues
"""

from cane_format._parser import ParseOptions, ParseResult, loads
from cane_format._writer import dumps
from cane_format.bioc import (
    format_bioc_json,
    iter_bioc_json,
    parse_bioc_json,
    read_bioc_json,
    write_bioc_json,
)
from cane_format.brat import format_brat, iter_brat, parse_brat, read_brat, write_brat
from cane_format.conll import (
    align,
    format_conll,
    from_tokens,
    iter_conll,
    parse_conll,
    read_conll,
    write_conll,
)
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
from cane_format.evaluation import to_nervaluate
from cane_format.json_format import format_json, iter_json, parse_json, read_json, write_json
from cane_format.model import Concept, Document, Entity, Member, Relation, Segment, Span
from cane_format.prompt import build_prompt, guideline
from cane_format.xml_format import format_xml, iter_xml, parse_xml, read_xml, write_xml

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
    "align",
    "build_prompt",
    "dumps",
    "format_bioc_json",
    "format_brat",
    "format_conll",
    "format_json",
    "format_xml",
    "from_tokens",
    "guideline",
    "iter_bioc_json",
    "iter_brat",
    "iter_conll",
    "iter_json",
    "iter_xml",
    "loads",
    "parse_bioc_json",
    "parse_brat",
    "parse_conll",
    "parse_json",
    "parse_xml",
    "read_bioc_json",
    "read_brat",
    "read_conll",
    "read_json",
    "read_xml",
    "to_nervaluate",
    "write_bioc_json",
    "write_brat",
    "write_conll",
    "write_json",
    "write_xml",
]
