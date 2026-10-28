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

### Changed
- Text verification shared by the brat and BioC readers (`_verify`).

## [0.0.0]

- Placeholder release reserving the package name.
