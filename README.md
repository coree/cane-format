# cane-format

A lightweight, dependency-free Python library for CANE (Context-Anchored Natural Expression), an output format for LLM-based named entity recognition: write annotated text as CANE for few-shot prompts, parse model output back into character spans, and convert between CANE and common annotation formats.

> Cornelius, Ito, Rinaldi. *CANE is a Format: Rethinking Output Formats for Few-Shot LLM-Based
> Named Entity Recognition.* Findings of EMNLP 2026. https://aclanthology.org/2026.findings-emnlp.1398/

Status: in development, not yet released.

```bash
pip install cane-format          # Python 3.10+, no dependencies
```

## What CANE looks like

Instead of offsets, tags or a marked-up copy of the input, the model writes one short
statement per entity, optionally with a verbatim snippet ("anchor") that locates it:

```
Entities:
`metastatic breast cancer` is a DISEASE found in `metastatic breast cancer cells`
`breast cancer cells` is a CELL found in `metastatic breast cancer cells caused`
`headache` and `nausea` are a ADR found in `caused headache and` and `and nausea`
```

Four variants: **Base** (no anchor), **Disco** (several parts for discontinuous entities),
**Context** (one anchor), **Full** (several parts, one anchor each).

## How it is meant to be used

```python
from pathlib import Path

import cane_format as cane

# 1. Load annotated documents (brat, BioC JSON, CoNLL, inline XML or JSON).
examples = cane.read_brat("corpus/train")

# 2. Build a few-shot prompt; the examples are written in CANE exactly as the parser expects.
prompt = cane.build_prompt(new_text, examples=examples[:5], variant="full")

# 3. Ask your model (any client; this library makes no model calls).
output = your_llm(prompt)

# 4. Keep the raw output: it is what you look at when something goes wrong.
Path("raw/doc-17.cane").write_text(output)

# 5. Parse it back into character spans. Problems never raise; they are reported.
result = cane.loads(output, text=new_text, variant="full", labels={"DRUG", "ADR"}, id="doc-17")
result.entities          # grounded entities with character offsets
result.issues            # e.g. line 4: not_found: part 'fever' not found in the text

# 6. Write the result out, e.g. as brat to inspect it in an annotation tool.
cane.write_brat([result.document], "predictions/")
```

Evaluate with [nervaluate-disco](https://github.com/coree/nervaluate-disco) via
`cane.to_nervaluate(docs)`.

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

## Behaviour you can rely on

- **Text is never changed.** Files that carry text keep it character for character; offsets
  are verified against stored surface text, and a mismatch raises `IntegrityError` (with a
  hint when the offsets fit another unit, such as UTF-8 bytes).
- **Nothing is lost silently.** What a format cannot hold raises `UnrepresentableError`, or,
  with an explicit strategy, is dropped with a `LossyConversionWarning`.
- **Strict by default.** Leniency (case-insensitive matching, anchor fallback, list-marker
  repair, lenient tag sequences) is always an explicit switch, and the parser never tries a
  looser setting on its own.

## The CANE grammar

```
output   ::= [HEADER NEWLINE] EMPTY | [HEADER NEWLINE] record { NEWLINE record }
record   ::= [HANDLE] parts COPULA [ARTICLE] LABEL [ANCHOR_INTRO anchors]
parts    ::= QUOTE text QUOTE { PART_CONNECTIVE QUOTE text QUOTE }
anchors  ::= QUOTE text QUOTE { ANCHOR_CONNECTIVE QUOTE text QUOTE }
```

Defaults (`Dialect`): `Entities:`, `NONE`, `` ` ``, `is` / `are`, `a` / `an` (`a` is written),
`found in`, `and`, handles `T1`, `T2`, …. Labels are one token. There is no escaping: records
are parsed by structure first, and whitespace in parts and anchors is matched flexibly.

**Writing** emits one record per entity in reading order (left to right, outer before nested),
always with the header, `NONE` when empty, and anchors of one whitespace unit on each side
(`context=`).

**Parsing** requires the variant, accepts a missing header and any article, and grounds each
record at the earliest unused occurrence at or after the previous record's position (so
repeated mentions and nested entities land where a reader expects them). Anchors select the
occurrence. Overlap never rejects an entity; a record that would repeat an earlier entity
exactly is reported as `duplicate`. `NONE` (any case, with or without the header) means no
entities. An empty output also yields no entities but is reported as `empty_output`, because
it usually means the generation failed.

**Choosing an occurrence.** The parser grounds what the model wrote; it never judges whether
a prediction is plausible, so a part may land inside a longer word if that is where the text
has it. When a part occurs several times, though, the choice matters. Without anchors (Base,
Disco) only the reading order decides, and the earliest occurrence can be inside a longer
word:

```python
text = "Maurice Tate against Northamptonshire at Northampton"
cane.loads("`Northampton` is a LOC", text=text, variant="base")
# -> "Northampton" inside "Northamptonshire" (the earliest occurrence)
cane.loads("`Northampton` is a LOC", text=text, variant="base", prefer_whole_words=True)
# -> the standalone "Northampton"
```

`prefer_whole_words=True` (opt-in) tries occurrences that neither start nor end between two
letters or digits first, then the rest, each in reading order. It only reorders candidates:
an entity that occurs only inside a word is still found, and in scripts written without
spaces (every occurrence counts as inside a word) nothing changes. With anchors the anchor
picks the occurrence first, so the switch matters only when the anchor leaves several open.
On the CANE paper's model outputs it grounded about 0.1% more entities correctly, nearly all
in Base and Disco.

---

This code base is developed with the assistance of Claude (Anthropic).
