"""Command line: ``cane-format convert`` and ``cane-format parse``."""

from __future__ import annotations

import argparse
import sys
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from cane_format import bioc, brat, conll, json_format, xml_format
from cane_format._parser import loads
from cane_format._writer import dumps
from cane_format.dialect import Variant
from cane_format.errors import CaneFormatError
from cane_format.model import Document

READERS = ("brat", "json", "conll", "bioc", "xml")
WRITERS = (*READERS, *(f"cane-{v.value}" for v in Variant))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    previous, warnings.showwarning = warnings.showwarning, _show_warning
    try:
        code: int = args.run(args)
        return code
    except (CaneFormatError, OSError) as err:
        print(f"cane-format: error: {err}", file=sys.stderr)
        return 2
    finally:
        warnings.showwarning = previous


def _show_warning(message: Warning | str, *_: Any, **__: Any) -> None:
    print(f"cane-format: warning: {message}", file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cane-format", description=__doc__)
    sub = p.add_subparsers(required=True, metavar="COMMAND")

    c = sub.add_parser("convert", help="convert annotated documents between formats")
    c.add_argument("input", type=Path, help="input file (a directory for brat)")
    c.add_argument("output", help="output file, '-' for stdout, or a directory (brat, cane-*)")
    c.add_argument("--from", dest="source", choices=READERS, required=True)
    c.add_argument("--to", dest="target", choices=WRITERS, required=True)
    _reader_options(c)
    _writer_options(c)
    c.set_defaults(run=_convert)

    r = sub.add_parser("parse", help="parse CANE model output into a document")
    r.add_argument("model_output", type=Path, help="file with the model's CANE output")
    r.add_argument("--text", type=Path, required=True, help="file with the annotated source text")
    r.add_argument("--variant", choices=[v.value for v in Variant], required=True)
    r.add_argument("--to", dest="target", choices=READERS, default="json")
    r.add_argument("-o", "--output", default="-", help="output file or directory (default stdout)")
    r.add_argument("--labels", help="comma-separated allowed labels")
    r.add_argument("--match", choices=["exact", "normalized", "casefold"], default="exact")
    r.add_argument("--anchor-fallback", action="store_true")
    r.add_argument("--strip-list-markers", action="store_true")
    r.add_argument("--handles", action="store_true")
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
    g.add_argument("--offset-unit", choices=["codepoint", "utf8", "utf16"])
    g.add_argument("--scheme", choices=["bio", "iob1", "bioes", "bilou"], default="bio")
    g.add_argument("--encoding", default="utf-8")
    g.add_argument("--comment-prefix")
    g.add_argument("--concept-keys", default="identifier", help="comma-separated (BioC)")
    g.add_argument("--tag", help="annotation element name (XML)")
    g.add_argument("--type-attr", default="type")
    g.add_argument("--document-tag")


def _writer_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("writing")
    g.add_argument("--out-scheme", choices=["bio", "iob1", "bioes", "bilou"], default="bio")
    g.add_argument("--out-offset-unit", choices=["codepoint", "utf8", "utf16"])
    g.add_argument("--context", type=int, default=1, help="anchor size (cane-context/full)")
    g.add_argument(
        "--on-unrepresentable",
        default="raise",
        help="raise | skip | first | hull (and split for conll)",
    )
    g.add_argument("--on-conflict", default="raise", help="raise | outermost | innermost | skip")
    g.add_argument("--alignment", default="strict", help="strict | expand | contract (conll)")
    g.add_argument("--out-tag", help="generic element name (XML)")


def _read(args: argparse.Namespace) -> list[Document]:
    unit = {"offset_unit": args.offset_unit} if args.offset_unit else {}
    readers: dict[str, Callable[[], list[Document]]] = {
        "brat": lambda: brat.read_brat(args.input, verify=args.verify, **unit),
        "json": lambda: json_format.read_json(args.input),
        "conll": lambda: conll.read_conll(
            args.input,
            scheme=args.scheme,
            encoding=args.encoding,
            comment_prefix=args.comment_prefix,
        ),
        "bioc": lambda: bioc.read_bioc_json(
            args.input, verify=args.verify, concept_keys=args.concept_keys.split(","), **unit
        ),
        "xml": lambda: xml_format.read_xml(
            args.input, tag=args.tag, type_attr=args.type_attr, document_tag=args.document_tag
        ),
    }
    return readers[args.source]()


def _write(docs: list[Document], target: str, output: str, args: argparse.Namespace) -> None:
    unit = {"offset_unit": args.out_offset_unit} if args.out_offset_unit else {}
    if target == "brat":
        brat.write_brat(docs, output, **unit)
        return
    if target.startswith("cane-"):
        rendered = [  # everything first, so an error leaves no partial output
            (
                f"{d.id or n}.cane",
                dumps(
                    d,
                    variant=target[5:],
                    context=args.context,
                    on_unrepresentable=args.on_unrepresentable,
                ),
            )
            for n, d in enumerate(docs, 1)
        ]
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in rendered:
            (directory / name).write_text(text + "\n", encoding="utf-8")
        return
    formatters: dict[str, Callable[[], str]] = {
        "json": lambda: "".join(json_format.format_json(d) + "\n" for d in docs),
        "conll": lambda: "".join(
            conll.format_conll(
                d,
                scheme=args.out_scheme,
                alignment=args.alignment,
                on_conflict=args.on_conflict,
                on_unrepresentable=args.on_unrepresentable,
            )
            for d in docs
        ),
        "bioc": lambda: bioc.format_bioc_json(docs, **unit) + "\n",
        "xml": lambda: "".join(xml_format.format_xml(d, tag=args.out_tag) + "\n" for d in docs),
    }
    content = formatters[target]()
    if output == "-":
        sys.stdout.write(content)
    else:
        with open(output, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)


def _convert(args: argparse.Namespace) -> int:
    _write(_read(args), args.target, args.output, args)
    return 0


def _parse(args: argparse.Namespace) -> int:
    with open(args.text, encoding="utf-8", newline="") as f:
        text = f.read()
    output = args.model_output.read_text(encoding="utf-8")
    options: dict[str, Any] = {
        "text": text,
        "variant": args.variant,
        "labels": args.labels.split(",") if args.labels else None,
        "match": args.match,
        "anchor_fallback": args.anchor_fallback,
        "strip_list_markers": args.strip_list_markers,
        "handles": args.handles,
    }
    result = loads(output, **options)
    doc = Document(text=result.text, entities=result.entities, id=args.text.stem)
    for issue in result.issues:
        print(f"{args.model_output}: {issue}", file=sys.stderr)
    _write([doc], args.target, args.output, args)
    return 0 if result.ok or args.allow_issues else 1


if __name__ == "__main__":
    sys.exit(main())
