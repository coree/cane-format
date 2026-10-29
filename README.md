# cane-format

A lightweight, dependency-free Python library for CANE (Context-Anchored Natural Expression),
an output format for LLM-based named entity recognition: write annotated text as CANE for
few-shot prompts, parse model output back into character spans, and convert between CANE and
common annotation formats.

CANE is introduced in the paper [CANE is a Format: Rethinking Output Formats for Few-Shot
LLM-Based Named Entity Recognition](https://aclanthology.org/2026.findings-emnlp.1398/)
(Findings of EMNLP 2026).

```bash
pip install cane-format          # Python 3.10+, no dependencies
```

Early release; the API may change before 1.0.

## Example

```
Entities:
`metastatic breast cancer` is a DISEASE found in `metastatic breast cancer cells`
`breast cancer cells` is a CELL found in `metastatic breast cancer cells caused`
`headache` and `nausea` are a ADR found in `caused headache and` and `and nausea`
```

One record per entity. The text after `found in` is an anchor that locates the entity;
discontinuous entities list their parts joined by `and`.

| Variant | Anchor | Discontinuous entities |
|---|:---:|:---:|
| **Base** | ✗ | ✗ |
| **Disco** | ✗ | ✓ |
| **Context** | ✓ | ✗ |
| **Full** | ✓ | ✓ |

## Usage

```python
import cane_format as cane

examples = cane.read_brat("corpus/train")
prompt = cane.build_prompt(new_text, examples=examples[:5], variant="full")

output = your_llm(prompt)  # this library makes no model calls

result = cane.loads(output, text=new_text, variant="full", labels={"DRUG", "ADR"})
result.entities  # entities with character offsets
result.issues    # lines that could not be grounded

cane.write_brat([result.document], "predictions/")
```

Evaluation: [nervaluate-disco](https://github.com/coree/nervaluate-disco) via
`cane.to_nervaluate(docs)`.

## Formats

| Format | Read / write |
|---|---|
| CANE | `loads`, `dumps` |
| brat standoff | `read_brat`, `write_brat` |
| BioC JSON | `read_bioc_json`, `write_bioc_json` |
| CoNLL / IOB | `read_conll`, `write_conll` |
| Inline XML | `read_xml`, `write_xml` |
| Offset JSON | `read_json`, `write_json` |

```bash
cane-format convert corpus/ train.conll --from brat --to conll --on-conflict outermost
cane-format parse output.cane --text doc.txt --variant full --to brat -o predictions/
```

## Behaviour

- Text is kept unchanged; offsets are verified against the text.
- What a format cannot represent raises an error, or is dropped with a warning if requested.
- Strict by default; lenient matching is opt-in.

## Grammar

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
