# Parser evaluation

Scores document parsers (Docling, small OCR vision models, LlamaParse) on table extraction and text coverage, using ground truth
taken from the LaTeX source of 11 arXiv database papers. You run the parsers yourself.

## Run it

    cd doc-parser/eval
    python3 -m venv .venv && source .venv/bin/activate
    pip install docling requests pypdf

    # 1. Docling (local, nothing leaves your machine). First run downloads models.
    python3 run_batch.py --engine docling

    # 1b. Docling again, exported as HTML (keeps merged cells; markdown cannot). ~7 min on CPU.
    python3 run_batch.py --engine docling-html

    # 1c. Docling's vision-model pipeline (Granite-Docling). Much slower on CPU; try one paper first:
    #     uv pip install mlx-vlm   (Apple Silicon; otherwise it falls back to transformers)
    python3 run_batch.py --engine docling-vlm --only 2310.14021

    # 1d. Small document models, local GPU. Each needs its OWN environment (on Windows,
    #     Paddle and CUDA PyTorch cannot load in one process). See CLAUDE.md for the setup.
    #     PaddleOCR-VL-1.6: env with paddlepaddle-gpu + "paddleocr[doc-parser]", no torch.
    <paddle-env-python> run_batch.py --engine paddleocr-vl --only 2310.14021
    #     GLM-OCR: Ollama serving glm-ocr:latest + env with "glmocr[selfhosted]"; glm_ocr.yaml keeps it local.
    <glm-env-python> run_batch.py --engine glm-ocr --only 2310.14021

    # 2. LlamaParse (cloud, uploads the PDFs; these are public papers only)
    export LLAMA_CLOUD_API_KEY=...
    python3 run_batch.py --engine llamaparse --tier cost_effective --confirm-public

    # 3. Score and build the report
    python3 score.py
    python3 build_report.py
    open report.html

Do not run `run_batch.py` with `python3 -I`; it imports `parsers.py` from this folder.

Useful options for `run_batch.py`: `--only 1802.10233` (one paper), `--force` (redo),
`--papers DIR`. Runs are resumable: finished papers are skipped. Errors go to
`outputs/<engine>/_errors.json`, timings to `outputs/<engine>/_timings.json`.

Cost and time: LlamaParse bills credits per page by tier (206 pages in this set), so check
your plan first, or start with `--only` on one paper. Docling on CPU can take several
seconds per page.

## Files

| File | Role |
|---|---|
| `gold_tables.py` | Builds `gold_tables.json` from the LaTeX tarballs (already generated) |
| `parsers.py` | One adapter per engine (Docling variants, PaddleOCR-VL, GLM-OCR, LlamaParse) |
| `glm_ocr.yaml` | GLM-OCR config: local Ollama, cloud mode off |
| `run_batch.py` | Runs an engine over all papers into `outputs/<engine>/` |
| `score.py` | Compares outputs with gold; writes `results.json`, `texts.json`, `results.csv` |
| `build_report.py` + `report_template.html` | Builds the self-contained `report.html` |
| `selftest.py` | Checks the scorer on synthetic outputs (10 checks) |
| `demo_report.html` | The report on fake data, to show the interface |

You can add a third engine: put its markdown in `outputs/<name>/<paper>.md` and re-run
`score.py` and `build_report.py`.

See `METHODOLOGY.md` for how scores are computed and what they cannot tell you.
