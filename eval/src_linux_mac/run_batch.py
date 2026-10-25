#!/usr/bin/env python3
"""Run one parser over every PDF in papers_db and save markdown + timings.

  python3 run_batch.py --engine docling
  python3 run_batch.py --engine docling-html   # same model, HTML export (keeps merged cells)
  python3 run_batch.py --engine llamaparse --tier cost_effective --confirm-public

Resumable: papers that already have an output file are skipped (use --force to redo).
Outputs go to outputs/<engine>/<paper>.md and outputs/<engine>/_timings.json.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import parsers

EVAL = Path(__file__).resolve().parent
PAPERS = EVAL.parent / "papers_db"


def page_count(pdf):
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf)).pages)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True,
                    choices=["docling", "docling-html", "docling-vlm", "paddleocr-vl", "glm-ocr", "llamaparse"])
    ap.add_argument("--tier", default="cost_effective", choices=parsers.LLAMA_TIERS)
    ap.add_argument("--only", nargs="*", help="paper ids to run, e.g. 1802.10233")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--confirm-public", action="store_true",
                    help="required for llamaparse: confirms the files are public and may be uploaded")
    ap.add_argument("--papers", default=str(PAPERS))
    args = ap.parse_args()

    pdfs = sorted(Path(args.papers).glob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if p.stem in args.only]
    if not pdfs:
        sys.exit(f"No PDFs found in {args.papers}")

    if args.engine == "llamaparse":
        if not args.confirm_public:
            sys.exit("LlamaParse uploads files to LlamaIndex's servers. These are public arXiv papers; "
                     "re-run with --confirm-public to go ahead.")
        if not os.environ.get("LLAMA_CLOUD_API_KEY"):
            sys.exit("Set LLAMA_CLOUD_API_KEY first.")
        total = sum(page_count(p) or 0 for p in pdfs)
        print(f"Uploading {len(pdfs)} PDFs (~{total} pages) at tier '{args.tier}'. "
              f"This uses LlamaCloud credits.")

    out = EVAL / "outputs" / args.engine
    out.mkdir(parents=True, exist_ok=True)
    timings_file = out / "_timings.json"
    timings = json.loads(timings_file.read_text()) if timings_file.exists() else {}
    errors = {}

    for n, pdf in enumerate(pdfs, 1):
        pid, target = pdf.stem, out / f"{pdf.stem}.md"
        if target.exists() and not args.force:
            print(f"[{n}/{len(pdfs)}] skip   {pid} (already done)")
            continue
        pages = page_count(pdf)
        print(f"[{n}/{len(pdfs)}] parsing {pid} ({pages} pages)...", flush=True)
        try:
            if args.engine == "docling":
                md, secs = parsers.run_docling(pdf)
            elif args.engine == "docling-html":
                md, secs = parsers.run_docling_html(pdf)
            elif args.engine == "docling-vlm":
                md, secs = parsers.run_docling_vlm(pdf)
            elif args.engine == "paddleocr-vl":
                md, secs = parsers.run_paddleocr_vl(pdf)
            elif args.engine == "glm-ocr":
                md, secs = parsers.run_glm_ocr(pdf)
            else:
                md, secs = parsers.run_llamaparse(pdf, args.tier)
            target.write_text(md, encoding="utf-8")
            timings[pid] = {"secs": round(secs, 2), "pages": pages}
            if args.engine == "llamaparse":
                timings[pid]["tier"] = args.tier
            timings_file.write_text(json.dumps(timings, indent=1))
            print(f"           done in {secs:.1f}s, {len(md):,} characters")
        except Exception as e:  # keep going, report at the end
            errors[pid] = repr(e)
            print(f"           FAILED: {e!r}")

    if errors:
        (out / "_errors.json").write_text(json.dumps(errors, indent=1))
        print(f"\n{len(errors)} paper(s) failed; see {out / '_errors.json'}")
    print(f"\nOutputs are in {out}")


if __name__ == "__main__":
    main()
