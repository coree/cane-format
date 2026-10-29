# cane-format

A lightweight, dependency-free Python library for CANE (Context-Anchored Natural Expression),
an output format for LLM-based named entity recognition. Write annotated examples as CANE for
few-shot prompts, parse model output back into character spans, and convert between CANE and
common annotation formats.

CANE is introduced in the paper [CANE is a Format: Rethinking Output Formats for Few-Shot
LLM-Based Named Entity Recognition](https://aclanthology.org/2026.findings-emnlp.1398/)
(Findings of EMNLP 2026). If you use it, please [cite the paper](#citation).

Status: early release; the API may still change before 1.0.

```bash
pip install cane-format          # Python 3.10+, no dependencies
```

## What CANE looks like

The model writes one short statement per entity, optionally with a verbatim snippet
("anchor") that locates it:

```
Entities:
`metastatic breast cancer` is a DISEASE found in `metastatic breast cancer cells`
`breast cancer cells` is a CELL found in `metastatic breast cancer cells caused`
`headache` and `nausea` are a ADR found in `caused headache and` and `and nausea`
```

| Variant | Anchor | Discontinuous entities |
|---|:---:|:---:|
| **Base** | ✗ | ✗ |
| **Disco** | ✗ | ✓ |
| **Context** | ✓ | ✗ |
| **Full** | ✓ | ✓ |

## How it is meant to be used

```python
from pathlib import Path

import cane_format as cane

examples = cane.read_brat("corpus/train")                  # or BioC, CoNLL, XML, JSON
prompt = cane.build_prompt(new_text, examples=examples[:5], variant="full")

output = your_llm(prompt)                                  # this library makes no model calls
Path("raw/doc-17.cane").write_text(output)                 # keep the raw output

result = cane.loads(output, text=new_text, variant="full", labels={"DRUG", "ADR"}, id="doc-17")
result.entities          # grounded entities with character offsets
result.issues            # problems never raise, e.g. line 4: not_found: part 'fever' …

cane.write_brat([result.document], "predictions/")
```

Evaluate with [nervaluate-disco](https://github.com/coree/nervaluate-disco) via `cane.to_nervaluate(docs)`.

## Formats

| Format | Read / write | Notes |
|---|---|---|
| CANE | `loads` / `dumps` | four variants, any language via `Dialect` |
| brat standoff | `read_brat`, `write_brat` | T, E, R, `*`, A/M, N, `#` lines |
| BioC JSON | `read_bioc_json`, `write_bioc_json` | UTF-8 byte offsets by default; PubTator3 exports |
| CoNLL / IOB | `read_conll`, `write_conll` | BIO, IOB1, BIOES, BILOU; `from_tokens` for Hugging Face rows |
| Inline XML | `read_xml`, `write_xml` | `<DRUG>…</DRUG>` or `<entity type=…>`; reads GENIA-style markup |
| Offset JSON | `read_json`, `write_json` | lossless, JSON Lines |

Every reader has an `iter_*` twin, and a `parse_*` / `format_*` pair for strings.

```bash
cane-format convert corpus/ train.conll --from brat --to conll --on-conflict outermost
cane-format parse output.cane --text doc.txt --variant full --to brat -o predictions/
```

## Behaviour

- **Integrity.** Text is kept character for character; offsets are checked against stored
  text, and a mismatch raises `IntegrityError`.
- **Reporting.** What a format cannot hold raises `UnrepresentableError`, or, with an
  explicit strategy, is dropped with a `LossyConversionWarning`.
- **Strictness.** Strict by default; leniency (case-insensitive matching, anchor fallback,
  list-marker repair, lenient tag sequences) is an explicit, opt-in switch.

## The CANE grammar

```
output   ::= HEADER | [HEADER NEWLINE] ( EMPTY | record { NEWLINE record } )
record   ::= [HANDLE] parts COPULA [ARTICLE] LABEL [ANCHOR_INTRO anchors]
parts    ::= QUOTE text QUOTE { PART_CONNECTIVE QUOTE text QUOTE }
anchors  ::= QUOTE text QUOTE { ANCHOR_CONNECTIVE QUOTE text QUOTE }
```

Defaults (`Dialect`): `Entities:`, `NONE`, `` ` ``, `is` / `are`, `a` / `an`, `found in`,
`and`, handles `T1`, `T2`, …. Labels are one token; there is no escaping.

- **Formatting** (`dumps`) writes one record per entity in reading order, with anchors of
  `context=1` word on each side, and parses every record back: one that would land elsewhere
  is still written, but reported (`on_mismatch=`).
- **Parsing** (`loads`) grounds each record at the earliest unused occurrence from the previous
  record's position on; anchors pick the occurrence, and overlap never rejects. `NONE` or the
  header alone means no entities; an empty output is reported as `empty_output`.
- **Whole words, opt-in.** Without anchors the earliest occurrence can be inside a longer
  word (`Northampton` in `Northamptonshire`). `prefer_whole_words=True` tries standalone
  occurrences first; it only reorders candidates and never rejects one.

## Citation

If you use CANE or this library in your work, please cite the paper:

```bibtex
@inproceedings{cornelius-etal-2026-cane,
    title = "{CANE} is a Format: Rethinking Output Formats for Few-Shot {LLM}-Based Named Entity Recognition",
    author = "Cornelius, Joseph  and
      Ito, Kei K  and
      Rinaldi, Fabio",
    editor = "Lee, Hung-Yi  and
      Dev, Sunipa  and
      Li, Jessy  and
      Elliott, Desmond",
    booktitle = "Findings of the {A}ssociation for {C}omputational {L}inguistics: {EMNLP} 2026",
    month = oct,
    year = "2026",
    address = "Budapest, Hungary",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2026.findings-emnlp.1398/",
    pages = "29773--29800",
    ISBN = "979-8-89176-462-0"
}
```

---

This code base is developed with the assistance of Claude (Anthropic).
