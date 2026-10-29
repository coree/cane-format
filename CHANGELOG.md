# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/) (`0.x` while the API settles).

## [Unreleased]

### Added
- Document model: `Span`, `Entity`, `Concept`, `Relation`, `Member`, `Segment`, `Document`.
- `Dialect` (every literal of the CANE surface form) and the four variants as `Variant`.
- `dumps`: write documents as CANE, in reading order.
- `loads`: parse CANE model output into a document, with problems reported as `ParseIssue`s.
- brat standoff: `read_brat`, `iter_brat`, `parse_brat`, `write_brat`, `format_brat`.
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
  texts written from the dialect and matching what `dumps` writes.
- Command line: `cane-format convert` (between all formats) and `cane-format parse` (model
  output to any format; exits 1 when lines could not be grounded unless `--allow-issues`).
- `loads(..., prefer_whole_words=True)` (and `--prefer-whole-words`): when a part occurs
  several times, occurrences that do not start or end inside a word are tried first. Opt-in;
  nothing is rejected.
- `IssueKind.EMPTY_OUTPUT`.
- `dumps(..., on_mismatch=, parse_options=)` (also `build_prompt`; `--on-mismatch` in the CLI):
  how a record that does not parse back is handled, and the parse settings it is checked with.
  `cane-format convert --to cane-*` takes `--match`, `--anchor-fallback` and
  `--prefer-whole-words` for that check.

### Changed
- `dumps` parses back every record it writes; a record that would ground elsewhere is still
  written and reported (`on_mismatch`, separate from `lossy`). Entities that would give the
  same record are written once.
- `loads` and `dumps` are about ten times faster on long documents (overlapping matches are
  found without a lookahead; `Document` fills missing IDs in linear time).
- `dumps` writes parts and anchors that contain the quote character (they parse back).
- `loads` accepts `NONE` after the header (`Entities:` then `NONE`) as no entities.
- `loads` reports an empty model output as `empty_output` (still no entities), so it no longer
  passes as a clean result; `cane-format parse` exits 1 for it.
- `loads(..., id=)` sets the resulting document's ID (needed e.g. to write it as brat).
- Text writers (`write_json`, `write_conll`, `write_bioc_json`, `write_xml`) accept a path or
  an open text stream and render everything before writing; `write_brat` checks every file
  name (unique, no path separators) and renders every document before writing anything.
- Writers validate their option values (a misspelled strategy raises `ValueError`).
- Lossy-conversion warnings name the document.
- Entities whose text starts or ends with whitespace follow `on_unrepresentable` in `dumps`.
- `build_prompt` sorts labels given as a set, omits the example section when there are no
  examples, and requires labels then.
- CLI rebuilt on the library writers: `-` means stdout (and is refused for brat and cane-*
  directories), option values are fixed choices, every error exits 2, warnings are shown for
  every document, file names are safe and unique, `--labels` is trimmed, and the XML reading
  options and `--encoding` (parse) are available.
- `CANE_REQUIRE_DATA=1` makes missing real test documents fail the run instead of skipping.
- `on_unrepresentable="skip"` (and the other strategies) also skip entities whose label the
  target cannot hold, instead of always raising.
- Text verification shared by the brat and BioC readers (`_verify`).
- CLI output to `-` is UTF-8 whatever the console encoding; documents without an ID get the
  next free number; an unknown `--encoding` is reported before any file is read.

### Removed
- `dumps(on_collision=)` and `--on-collision`: a quote character inside content is checked by
  parsing the record back instead.

### Fixed
- `guideline()` with `{` or `}` as quote characters.
- CLI XML output dropped the `<documents>` wrapper and document IDs.
- `write_brat` refused IDs that `read_brat` produces (`:` and spaces are valid file names on
  macOS and Linux); only path separators, NUL, `.` and `..` are refused.
- Lossy warnings for documents without an ID read "document None" or "document :".

## [0.0.0]

- Placeholder release reserving the package name.
