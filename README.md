# doc-parser

Experiments in document parsing: how well different parsers pull tables and text out of
PDFs, measured against ground truth instead of eyeballed.

## What's here

| Path | Contents |
|---|---|
| `eval/` | The evaluation harness: parser adapters, batch runner, scorer, HTML report. Start with `eval/README.md`. |
| `papers_db/` | 11 public arXiv papers (206 pages) plus their LaTeX sources, which supply the gold tables. |
| `papers/`, `frameworks/`, `filings/`, `forms/` | Other public sample documents (papers, NIST/OWASP frameworks, a 10-K, FUNSD forms). Not scored yet. |

The data folders and `eval/outputs/` are gitignored; only code, gold data and results are tracked.

## Engines compared

- **Docling**, classic pipeline (markdown and HTML export) and its Granite-Docling vision pipeline. Local.
- **PaddleOCR-VL-1.6** and **GLM-OCR**, small (~0.9B) document vision models. Local GPU. In progress.
- **LlamaParse**. Cloud; public documents only.

Current scores are in `eval/results.csv` and `eval/report.html`. `eval/METHODOLOGY.md`
explains how they are computed and what 23 gold tables can and cannot tell you.

## Ground rules

Public documents only. Nothing confidential goes into this repo or into any cloud parser.
