"""Command line: ``cane-format convert`` and ``cane-format parse``.

Exit codes: 0 success, 1 (``parse`` only) some lines could not be grounded, 2 error.
"""

from __future__ import annotations

import argparse
import codecs
import io
import sys
import warnings
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from cane_format import bioc, brat, conll, json_format, xml_format
from cane_format._formatter import dumps
from cane_format._output import file_names, write_text
from cane_format._parser import ParseOptions, loads
from cane_format.dialect import Variant
from cane_format.errors import CaneFormatError
from cane_format.model import Document

READERS = ("brat", "json", "conll", "bioc", "xml")
WRITERS = (*READERS, *(f"cane-{v.value}" for v in Variant))
DIRECTORY_TARGETS = ("brat", *(f"cane-{v.value}" for v in Variant))
SCHEMES = conll.SCHEMES
UNITS = ("codepoint", "utf8", "utf16")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with warnings.catch_warnings():
        warnings.simplefilter("always", UserWarning)  # includes LossyConversionWarning
        warnings.showwarning = _show_warning
        try:
            code: int = args.run(args)
            return code
        except (CaneFormatError, OSError, ValueError) as err:
            print(f"cane-format: error: {err}", file=sys.stderr)
            return 2


def _show_warning(message: Warning | str, *_: Any, **__: Any) -> None:
    print(f"cane-format: warning: {message}", file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cane-format",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(required=True, metavar="COMMAND")

    c = sub.add_parser("convert", help="convert annotated documents between formats")
    c.add_argument("input", type=Path, help="input file (a directory for brat)")
    c.add_argument("output", help="output file or '-' for stdout; a directory for brat, cane-*")
    c.add_argument("--from", dest="source", choices=READERS, required=True)
    c.add_argument("--to", dest="target", choices=WRITERS, required=True)
    _reader_options(c)
    _writer_options(c)
    k = c.add_argument_group("checking cane-* output (the settings it will be parsed with)")
    k.add_argument("--match", choices=["exact", "normalized", "casefold"], default="exact")
    k.add_argument("--anchor-fallback", action="store_true")
    k.add_argument("--prefer-whole-words", action="store_true")
    c.set_defaults(run=_convert)

    r = sub.add_parser("parse", help="parse CANE model output into a document")
    r.add_argument("model_output", type=Path, help="file with the model's CANE output")
    r.add_argument("--text", type=Path, required=True, help="file with the annotated source text")
    r.add_argument("--variant", choices=[v.value for v in Variant], required=True)
    r.add_argument("--to", dest="target", choices=READERS, default="json")
    r.add_argument(
        "-o",
        "--output",
        default="-",
        help="output file or '-' for stdout (default); a directory for brat",
    )
    r.add_argument("--labels", help="comma-separated allowed labels")
    r.add_argument("--match", choices=["exact", "normalized", "casefold"], default="exact")
    r.add_argument("--anchor-fallback", action="store_true")
    r.add_argument("--strip-list-markers", action="store_true")
    r.add_argument("--handles", action="store_true")
    r.add_argument(
        "--prefer-whole-words",
        action="store_true",
        help="try occurrences that do not start or end inside a word first",
    )
    r.add_argument("--encoding", default="utf-8", help="of the text and model output files")
    r.add_argument(
        "--allow-issues",
        action="store_true",
        help="exit with 0 even if some lines could not be grounded",
    )
    _writer_options(r)
    r.set_defaults(run=_parse)
    return p


def _reader_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("reading")
    g.add_argument("--verify", choices=["raise", "warn", "off"], default="raise")
    g.add_argument("--offset-unit", choices=UNITS, help="default: the format's own unit")
    g.add_argument("--scheme", choices=SCHEMES, default="bio", help="CoNLL tag scheme")
    g.add_argument("--encoding", default="utf-8", help="CoNLL file encoding")
    g.add_argument("--comment-prefix", help="CoNLL comment lines, e.g. '#'")
    g.add_argument("--concept-keys", default="identifier", help="BioC, comma-separated")
    g.add_argument("--tag", help="XML annotation element name (default: label as name)")
    g.add_argument("--type-attr", default="type", help="XML label attribute with --tag")
    g.add_argument("--ref-attr", default="ref", help="XML attribute linking fragments")
    g.add_argument("--document-tag", help="XML element holding one document")
    g.add_argument("--segment-tags", default="", help="XML elements kept as segments")
    g.add_argument("--exclude-tags", default="", help="XML elements left out of the text")


def _writer_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("writing")
    g.add_argument("--out-scheme", choices=SCHEMES, default="bio", help="CoNLL tag scheme")
    g.add_argument("--out-offset-unit", choices=UNITS, help="default: the format's own unit")
    g.add_argument("--context", type=int, default=1, help="anchor size (cane-context/full)")
    g.add_argument(
        "--on-unrepresentable",
        choices=["raise", "skip", "first", "hull", "split"],
        default="raise",
        help="split: CoNLL only",
    )
    g.add_argument(
        "--on-mismatch",
        choices=["warn", "raise", "ignore"],
        default="warn",
        help="cane-*: a record that does not parse back on its own spans",
    )
    g.add_argument(
        "--on-conflict",
        choices=["raise", "outermost", "innermost", "skip"],
        default="raise",
        help="CoNLL",
    )
    g.add_argument(
        "--alignment", choices=["strict", "expand", "contract"], default="strict", help="CoNLL"
    )
    g.add_argument("--out-tag", help="XML: one element name with the label in an attribute")
    g.add_argument("--out-type-attr", default="type", help="XML label attribute with --out-tag")


def _names(text: str | None) -> list[str]:
    return [name.strip() for name in (text or "").split(",") if name.strip()]


def _read(args: argparse.Namespace) -> list[Document]:
    unit = {"offset_unit": args.offset_unit} if args.offset_unit else {}
    readers: dict[str, Callable[[], list[Document]]] = {
        "brat": lambda: brat.read_brat(args.input, verify=args.verify, **unit),
        "json": lambda: json_format.read_json(args.input),
        "conll": lambda: conll.read_conll(
            args.input,
            scheme=args.scheme,
            encoding=_encoding(args.encoding),
            comment_prefix=args.comment_prefix,
        ),
        "bioc": lambda: bioc.read_bioc_json(
            args.input, verify=args.verify, concept_keys=_names(args.concept_keys), **unit
        ),
        "xml": lambda: xml_format.read_xml(
            args.input,
            tag=args.tag,
            type_attr=args.type_attr,
            ref_attr=args.ref_attr,
            document_tag=args.document_tag,
            segment_tags=_names(args.segment_tags),
            exclude_tags=_names(args.exclude_tags),
        ),
    }
    return readers[args.source]()


def _encoding(name: str) -> str:
    """Check an --encoding value before any file is read."""
    try:
        codecs.lookup(name)
    except LookupError:
        raise ValueError(f"unknown encoding {name!r}") from None
    return name


def _with_ids(docs: list[Document]) -> list[Document]:
    """Give documents without an ID the next free number, so every document can name a file."""
    taken = {d.id.casefold() for d in docs if d.id}
    named, n = [], 0
    for d in docs:
        if not d.id:
            n += 1
            while str(n) in taken:
                n += 1
            taken.add(str(n))
            d = replace(d, id=str(n))
        named.append(d)
    return named


def _write(docs: list[Document], target: str, output: str, args: argparse.Namespace) -> None:
    if target in DIRECTORY_TARGETS and output == "-":
        raise ValueError(f"{target} writes one file per document; give an output directory")
    unit = {"offset_unit": args.out_offset_unit} if args.out_offset_unit else {}
    if output == "-":
        _to_stdout(lambda stream: _write_file(docs, target, stream, args, unit))
    else:
        _write_file(docs, target, output, args, unit)


def _to_stdout(write: Callable[[Any], None]) -> None:
    """Write UTF-8 to stdout whatever the console encoding, as files are written."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # already a text-only stream (e.g. replaced in tests)
        write(sys.stdout)
        return
    sys.stdout.flush()
    stream = io.TextIOWrapper(buffer, encoding="utf-8", newline="\n", write_through=True)
    try:
        write(stream)
        stream.flush()
    finally:
        stream.detach()


def _write_file(
    docs: list[Document], target: str, destination: Any, args: argparse.Namespace, unit: Any
) -> None:
    if target == "brat":
        brat.write_brat(_with_ids(docs), destination, **unit)
    elif target.startswith("cane-"):
        docs = _with_ids(docs)
        names = file_names(docs, ".cane")
        variant = Variant(target[5:])
        check = ParseOptions(
            variant=variant,
            match=args.match,
            anchor_fallback=args.anchor_fallback,
            prefer_whole_words=args.prefer_whole_words,
        )
        rendered = [  # everything first, so an error leaves no partial output
            dumps(
                d,
                variant=variant,
                context=args.context,
                on_unrepresentable=args.on_unrepresentable,
                on_mismatch=args.on_mismatch,
                parse_options=check,
            )
            for d in docs
        ]
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in zip(names, rendered, strict=True):
            write_text(directory / name, text + "\n")
    elif target == "json":
        json_format.write_json(docs, destination)
    elif target == "conll":
        conll.write_conll(
            docs,
            destination,
            scheme=args.out_scheme,
            alignment=args.alignment,
            on_conflict=args.on_conflict,
            on_unrepresentable=args.on_unrepresentable,
        )
    elif target == "bioc":
        bioc.write_bioc_json(docs, destination, **unit)
    else:
        xml_format.write_xml(docs, destination, tag=args.out_tag, type_attr=args.out_type_attr)


def _convert(args: argparse.Namespace) -> int:
    _write(_read(args), args.target, args.output, args)
    return 0


def _parse(args: argparse.Namespace) -> int:
    encoding = _encoding(args.encoding)
    with open(args.text, encoding=encoding, newline="") as f:
        text = f.read()
    output = args.model_output.read_text(encoding=encoding)
    result = loads(
        output,
        text=text,
        variant=args.variant,
        labels=_names(args.labels) or None,
        match=args.match,
        anchor_fallback=args.anchor_fallback,
        strip_list_markers=args.strip_list_markers,
        handles=args.handles,
        prefer_whole_words=args.prefer_whole_words,
        id=args.text.stem,
    )
    for issue in result.issues:
        print(f"{args.model_output}: {issue}", file=sys.stderr)
    _write([result.document], args.target, args.output, args)
    return 0 if result.ok or args.allow_issues else 1


if __name__ == "__main__":
    sys.exit(main())
