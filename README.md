# cane-format

LLMs are bad at counting characters and at copying long text exactly, so asking them for
offsets or a tagged copy of the text goes wrong easily. With CANE (Context-Anchored Natural
Expression), the model writes one plain statement per entity instead, and this library finds
each one in the text and gives you exact character spans back. It also writes your annotated
examples as CANE for few-shot prompts, and converts between CANE and the usual annotation
formats.

CANE is introduced in the paper [CANE is a Format: Rethinking Output Formats for Few-Shot
LLM-Based Named Entity Recognition](https://aclanthology.org/2026.findings-emnlp.1398/)
(Findings of EMNLP 2026). If you use it, please [cite the paper](#citation).

```bash
pip install cane-format          # Python 3.10+, no dependencies
```

This is an early release; the API may still change before 1.0.

## What CANE looks like

Asked to find diseases, cell types and adverse drug reactions, a model answers like this:

```
Entities:
`metastatic breast cancer` is a DISEASE found in `metastatic breast cancer cells`
`breast cancer cells` is a CELL found in `metastatic breast cancer cells caused`
`headache` and `nausea` are a ADR found in `caused headache and` and `and nausea`
```

Each line names an entity and its type. The part after `found in` is the anchor: the entity
with a word of context on each side, copied from the text, so the parser knows which
occurrence is meant. An entity made of separate pieces lists them joined by `and`, as in the
last line. CANE comes in four variants, depending on whether you want anchors and
discontinuous entities:

| Variant | Anchor | Discontinuous entities |
|---|:---:|:---:|
| **Base** | ✗ | ✗ |
| **Disco** | ✗ | ✓ |
| **Context** | ✓ | ✗ |
| **Full** | ✓ | ✓ |

## How to use it

```python
from pathlib import Path

import cane_format as cane

examples = cane.read_brat("corpus/train")                  # or BioC, CoNLL, XML, JSON
prompt = cane.build_prompt(new_text, examples=examples[:5], variant="full")

output = your_llm(prompt)                                  # this library makes no model calls
Path("raw/doc-17.cane").write_text(output)                 # keep the raw output

result = cane.loads(output, text=new_text, variant="full", labels={"DRUG", "ADR"}, id="doc-17")
result.entities          # the entities, with character offsets
result.issues            # what could not be placed, e.g. line 4: not_found: part 'fever' …

cane.write_brat([result.document], "predictions/")
```

To score predictions against gold annotations, pass them to
[nervaluate-disco](https://github.com/coree/nervaluate-disco) with `cane.to_nervaluate(docs)`.

## Formats

| Format | Read / write | Notes |
|---|---|---|
| CANE | `loads` / `dumps` | four variants, any language via `Dialect` |
| brat standoff | `read_brat`, `write_brat` | T, E, R, `*`, A/M, N, `#` lines |
| BioC JSON | `read_bioc_json`, `write_bioc_json` | UTF-8 byte offsets by default; PubTator3 exports |
| CoNLL / IOB | `read_conll`, `write_conll` | BIO, IOB1, BIOES, BILOU; `from_tokens` for Hugging Face rows |
| Inline XML | `read_xml`, `write_xml` | `<DRUG>…</DRUG>` or `<entity type=…>`; reads GENIA-style markup |
| Offset JSON | `read_json`, `write_json` | lossless, JSON Lines |

Each reader also has an `iter_*` version for large corpora, and `parse_*` / `format_*`
functions that work on strings. The same conversions work from the command line:

```bash
cane-format convert corpus/ train.conll --from brat --to conll --on-conflict outermost
cane-format parse output.cane --text doc.txt --variant full --to brat -o predictions/
```

## How it behaves

- **Your text is never changed.** Every character is kept, and offsets are checked against
  the text a file stores. If they don't match, you get an `IntegrityError`, not wrong spans.
- **Nothing is lost silently.** If a format can't hold something, such as a discontinuous
  entity in CoNLL, you get an error, or a warning if you chose to drop it.
- **Strict unless you ask otherwise.** Leniency, such as case-insensitive matching, is always
  an option you switch on yourself.
- **The parser takes the model at its word.** It looks for each entity in the order the model
  wrote them, so repeated and nested mentions land where you'd expect. It never corrects a
  prediction, and whatever it can't place ends up in `result.issues` rather than vanishing.
- **Your examples are checked.** `dumps` parses every line it writes back, and warns if one
  would land somewhere else, so a few-shot example never quietly teaches the wrong thing.
- **Whole words, if you want them.** Without anchors, an entity can match inside a longer
  word (`Northampton` in `Northamptonshire`). `prefer_whole_words=True` tries whole-word
  matches first.

## The CANE grammar

For anyone who wants to write their own parser. The defaults are `Entities:`, `NONE`,
backticks, `is` / `are`, `a` / `an`, `found in` and `and`; `Dialect` changes them, for
example for other languages.

```
output   ::= HEADER | [HEADER NEWLINE] ( EMPTY | record { NEWLINE record } )
record   ::= [HANDLE] parts COPULA [ARTICLE] LABEL [ANCHOR_INTRO anchors]
parts    ::= QUOTE text QUOTE { PART_CONNECTIVE QUOTE text QUOTE }
anchors  ::= QUOTE text QUOTE { ANCHOR_CONNECTIVE QUOTE text QUOTE }
```

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
