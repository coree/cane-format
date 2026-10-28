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

## [0.0.0]

- Placeholder release reserving the package name.
