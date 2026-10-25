# Project context: parser evaluation (Docling vs LlamaParse vs others)

Owner: Abhiram. Goal: understand document parsing from first principles for an AI-security /
document-parsing blog, and find a parsing approach he can use without paying a new service
(Azure OpenAI is the approved vendor at his employer; confidential documents never leave it).
Repo: doc-parser (git; this file lives in eval/). Read README.md and METHODOLOGY.md first.
One copy of every script lives in eval/; it runs unchanged on Mac and Windows. No per-OS folders.

## Hard rules
- This is his PERSONAL machine. Only public documents (the arXiv papers in ../papers_db).
- Never use work Azure OpenAI keys here. Do not upload anything confidential anywhere.
- Ask before anything that spends money (LlamaParse credits, Azure tokens). Log tokens/cost.
- Do not run run_batch.py with `python3 -I` (it imports parsers.py from this folder).
- Do not change the gold data or scorer silently; report any such change and keep a backup
  (results.v1.json / gold_tables.v1.json / report.v1.html are the pre-fix versions).

## Layout
- ../papers_db/*.pdf + source/*.tar.gz: 11 arXiv papers (206 pages). Gold tables come from LaTeX.
- gold_tables.py -> gold_tables.json: 23 usable tables. \cite/\ref cells are flagged uncertain
  (excluded from scoring); ROW_MERGES merges the two-line header of 1812.03651 T1.
- parsers.py: run_docling, run_docling_html, run_docling_vlm, run_paddleocr_vl, run_glm_ocr, run_llamaparse
  (all return (text, secs)). glm_ocr.yaml configures run_glm_ocr (local Ollama, cloud MaaS off).
- run_batch.py --engine {docling,docling-html,docling-vlm,paddleocr-vl,glm-ocr,llamaparse} [--only ID] [--force]
  writes outputs/<engine>/<paper>.md (HTML engines also write .md files containing HTML).
- score.py: auto-discovers every folder under outputs/ as an engine; writes results.json etc.
- build_report.py + report_template.html -> report.html (self-contained). selftest.py: 10 checks.
- Run order: run_batch -> score.py -> build_report.py -> open report.html. score.py needs pypdf for text
  coverage (on the Mac: `uv run --no-project --with pypdf python score.py`).
- eval/outputs/ is gitignored (copy it between machines by hand); papers_db/ is gitignored too.

## Results so far (23 gold tables, after the gold fixes; per-table averages)
- docling (markdown):  found 20/23, position 53%, content recall 63%, precision 84%, ~1.9 s/page (Mac CPU)
- docling-html:        found 20/23, position 57%, recall 63%, precision 85%
- llamaparse (cost_effective): found 23/23, position 87%, recall 93%, precision 96%, ~1.0 s/page, 95 extra tables
  (many extra tables are numbers read off charts; unverified, spot-check against PDFs)
- docling-vlm (Granite-Docling 258M): only 2 papers run (2310.14021, 2402.10460). Fixed several tables
  classic Docling collapsed (2310.14021 T3-T5) but lossy on text-dense tables (2402.10460: 45%/24%).
  Slow: ~37 s/page and ~119 s/page (6 GB RTX 2060, memory nearly full, spilled to system RAM).
- Docling's HTML export only helped merged-cell tables; missed/collapsed tables are a detection problem.
- Unresolved: 1512.00168 I2 scores 13% for all engines (not citations; maybe a long table split across pages).
  Check it in the report's Tables view before trusting it.

## Machines
- Mac (this one): MLX available. Docling classic runs on CPU.
- MSI Windows laptop, RTX 2060 6 GB, reachable over Tailscale at 100.99.179.42 (OpenSSH server needed;
  default shell is cmd, so no `export`). CUDA PyTorch is installed in its venv (2.11.0+cu128).
  Old project copy: D:\Coding\Lab\doc-parsing\doc_parsing_samples\doc_parsing_samples\eval (doubled folder name).
  The user runs commands there and pastes the output; give exact cmd commands, do not assume SSH.
  Separate uv envs: D:\Coding\Lab\envs\paddle (paddlepaddle-gpu 3.2.1 cu126 + paddleocr, NO torch) and
  D:\Coding\Lab\envs\glm (cu128 torch first, then glmocr[selfhosted]). Paddle and CUDA torch in one
  process fail on Windows (WinError 127 loading cudnn_cnn64_9.dll): never install paddle into the torch venv.

## Known issues to check
- report_template.html defines only 3 engine colors (--e0..--e2); the report now has 4+ engines.
  Verify colors/legends/dot plot with 4 engines and fix if needed. Also not yet visually checked:
  "Parsed output" mode, raw markdown viewer, mobile width.
- Granite-Docling unreliable as a "small local model" test; do not generalise from it.

## Next task (what the user asked for)
1. Add engines for small document-specific models and test them on the 23 tables, starting with
   PaddleOCR-VL (~0.96B, Apache 2.0) and GLM-OCR (~1.3B, MIT); MinerU 2.5 is a third candidate.
   Look up each project's CURRENT install/runtime instructions first (they change quickly); do not guess flags.
   They should fit the MSI's 6 GB GPU. Report seconds/page and score them with the existing harness.
2. Build an "escalation" pipeline: classic Docling first; validate each table (cell words must appear in the
   PDF text layer; no collapsed single-row tables; row/col sanity); send only failing table crops to a
   backend model. Backend must be swappable: local model or Azure OpenAI (env vars
   AZURE_OPENAI_ENDPOINT / KEY / DEPLOYMENT; personal resource only here). Ground the model with the PDF
   text and tell it to copy words verbatim. Log tokens and cost per paper.
3. Natively parse XLSX/DOCX/HTML without vision (openpyxl/pandas); vision only for charts/images.
4. Rebuild the report and explain which design wins and why, with the small-sample caveat.

## Progress on next task 1 (2026-10-25)
- Current versions: PaddleOCR-VL-1.6 (0.9B, Apache 2.0, paddleocr>=3.6, pipeline_version "v1.6");
  GLM-OCR is ~0.9B (not 1.3B), MIT; glmocr SDK 0.1.5. glmocr's packaged config has MaaS (Zhipu cloud) ON,
  so run_glm_ocr forces mode="selfhosted" and refuses to run if ZHIPU_API_KEY/GLMOCR_API_KEY is set.
- Mac attempt (MLX-VLM server + PaddleOCR client) hung before any request reached the server; abandoned.
- MSI, PaddleOCR-VL: models load, then OOM on 6 GB. RTX 2060 has no bf16 so the VLM loads in float32
  (~4 GB); default config queues 64 pages and layout batch 8. parsers.py forces batch 1 / no queues, but
  the MSI run still OOMed at the same allocation (unconfirmed whether that run had the fixed parsers.py).
  Next: llama-cpp-server backend. Set PADDLE_VL_SERVER_URL=http://127.0.0.1:8111/v1; llama-server serves
  PaddlePaddle/PaddleOCR-VL-1.6-GGUF (936 MB model + 882 MB mmproj). MSI driver is CUDA 13.3, so use the
  llama.cpp win-cuda-12.4 build, not 13.4. The official GGUF is BF16 (no bf16 on RTX 2060), so convert it:
  `llama-quantize.exe PaddleOCR-VL-1.6-GGUF.gguf PaddleOCR-VL-1.6-F16.gguf F16` and serve the F16 file with
  `-ngl 99 -c 16384` (default ctx 131072 x 4 slots wastes memory). A stale server can keep port 8111:
  `taskkill /IM llama-server.exe /F`; curl /v1/models shows n_ctx and ftype of the server answering.
  The llama-cpp-server backend ignores max_pixels/min_pixels (PADDLE_VL_MAX_PIXELS has no effect there).
- First working run (llama.cpp F16 server, fully serial client): 2310.14021, 25 pages in 287 s (~11.5 s/page,
  incl. warm-up), 146k chars. parsers.py then re-enabled queues + page batch 8 in server mode; re-time it.
- Merge accident on main: ae15198 moved run_batch.py/score.py into src_win, the flattening deleted src_win,
  so both vanished; restored from 6129b45 and recommitted.
- GLM-OCR (via Ollama glm-ocr:latest) not run yet. No paddleocr-vl or glm-ocr scores yet.
