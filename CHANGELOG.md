# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/) (`0.x` while the API settles).

## [Unreleased]

### Added
- Documentation site at https://coree.github.io/cane-format/: guide pages with examples that
  run at every build, and an API reference generated from the docstrings. Linked from the
  README and the package metadata.

### Fixed
- `cane-format --help` described exit code 1 as "some lines could not be grounded"; it now
  says "the output has issues", which also covers an empty output or an invalid label.

## [0.1.0] - 2026-10-29

First release. No runtime dependencies; Python 3.10 to 3.14.

### Added
- Document model: `Span`, `Entity`, `Concept`, `Relation`, `Member`, `Segment`, `Document`
  (frozen; missing entity and relation IDs filled on construction; references validated).
- `Dialect` (every literal of the CANE surface form) and the four variants as `Variant`.
- `loads`: parse CANE model output into a document. Problems never raise; they come back as
  `ParseIssue`s (`IssueKind`: `empty_output`, `malformed_line`, `not_found`,
  `anchor_not_found`, `part_count_mismatch`, `unknown_handle`, `invalid_label`,
  `invalid_span`, `duplicate`). Reading-order grounding; strict by default, with opt-in
  `match="normalized"|"casefold"`, `anchor_fallback`, `strip_list_markers`, `handles` and
  `prefer_whole_words`. `NONE`, the header alone, or the header followed by `NONE` mean no
  entities; an empty output is reported as `empty_output`.
- `dumps`: write documents as CANE, in reading order, with anchors of exactly `context` units.
  Every record is parsed back as `loads` would parse it (`parse_options=`); one that would
  ground elsewhere is still written and reported (`on_mismatch="warn"|"raise"|"ignore"`).
  Entities a variant cannot express follow `on_unrepresentable`; information CANE cannot carry
  is reported once as a `LossyConversionWarning`.
- brat standoff: `read_brat`, `iter_brat`, `parse_brat`, `write_brat`, `format_brat` (T, E, R,
  `*`, A/M, N, `#` lines; offsets verified against the stored text).
- Offset JSON (lossless, JSON Lines for collections): `read_json`, `iter_json`, `parse_json`,
  `write_json`, `format_json`.
- CoNLL / IOB (BIO, IOB1, BIOES, BILOU): `read_conll`, `iter_conll`, `parse_conll`,
  `write_conll`, `format_conll`, `from_tokens` (Hugging Face style), `align` (onto raw text);
  `encoding=` and opt-in `comment_prefix=` (CoNLL-U style `# doc_id = …` lines).
- BioC JSON (UTF-8 byte offsets by default; passages placed at their offsets; passage, sentence
  and document-level annotations; trigger nodes; PubTator3 exports): `read_bioc_json`,
  `iter_bioc_json`, `parse_bioc_json`, `write_bioc_json`, `format_bioc_json`.
- Inline XML (label as element name, or a generic element with a type attribute; refs for
  discontinuous and crossing entities; always well-formed; reads corpora such as GENIA with
  structural markup): `read_xml`, `iter_xml`, `parse_xml`, `write_xml`, `format_xml`.
- `to_nervaluate`: documents in nervaluate-disco's span format.
- `build_prompt` and `guideline`: few-shot prompts in the CANE paper's layout, with guideline
  texts written from the dialect and examples written by `dumps`.
- Command line: `cane-format convert` (between all formats, including `cane-*` output) and
  `cane-format parse` (model output to any format; exits 1 when the output has issues unless
  `--allow-issues`, 2 on errors).

## [0.0.0]

- Placeholder release reserving the package name.
