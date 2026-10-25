# Methodology

## Ground truth
Each paper's arXiv LaTeX source is parsed for table environments (`table`, `tabular`,
`tabularx`, `longtable`, `longtabu`). Formatting commands are stripped, the author's own
macros are expanded, nested tabulars and `\multicolumn`/`\multirow` are handled. Cells that
contain math or unresolved macros are flagged `uncertain` and excluded from every score.
Each table is cross-checked against the PDF's text layer (`pdf_cell_match`); tables that fail
sanity checks are marked unusable. Result: 23 usable tables, 1,448 cells, about 1,391 scorable.

## Matching
Parsed tables are read from markdown pipe tables and HTML tables (spans expanded to a grid).
Per paper, each gold table is compared with each parsed table by overlap of cell text (bag F1).
Pairs are assigned greedily, best first, needing at least 0.25. Unmatched gold tables count as
not found and score zero. Unmatched parsed tables are "extra tables".

## Cell states
Text is normalized (lowercase, markup and punctuation stripped, check/cross glyphs unified).
Each gold cell is: ok (right text, right place), moved (text present, wrong cell), near
(similarity 0.85 or more), missing, or uncertain (not scored).

## Measures
- Position accuracy: ok cells / scored gold cells. Strict about structure.
- Content recall: ok + moved. Shows what text survived regardless of structure.
- Precision: parsed cells that match gold among matched tables; uncertain cells excluded.
- Extra tables: parsed tables with no gold partner (some may be real tables the LaTeX lacked).
- Text coverage: distinct words of 4+ letters in the PDF text layer that appear in the output.
- Seconds per page: wall time from the runner.

## Limits
- 23 tables is small. Differences of a few points are noise.
- Only LaTeX-born tables; tables embedded as images are not covered.
- Two papers (1603.09320, cs_0701157) have no LaTeX, so they get text and timing only.
- Math-heavy cells are not scored.
- The scorer was validated on synthetic outputs, not on real Docling or LlamaParse output.
  If a real engine's table format is read wrongly, the first symptom is zero tables found;
  check the raw markdown in the Papers view.
- Not tested: scanned documents, forms, very long PDFs, non-English text.
