#!/usr/bin/env python3
"""Build report.html (one self-contained file, works offline) from results.json.

  python3 build_report.py
  python3 build_report.py --results DIR --out FILE
"""
import argparse
import csv
import json
from pathlib import Path

EVAL = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(EVAL))
    ap.add_argument("--out", default=str(EVAL / "report.html"))
    ap.add_argument("--papers", default=str(EVAL.parent / "papers_db"))
    ap.add_argument("--template", default=str(EVAL / "report_template.html"))
    args = ap.parse_args()
    rdir = Path(args.results)

    data = json.loads((rdir / "results.json").read_text(encoding="utf-8"))
    texts_file = rdir / "texts.json"
    data["texts"] = json.loads(texts_file.read_text(encoding="utf-8")) if texts_file.exists() else {}
    titles = {}
    manifest = Path(args.papers) / "manifest.csv"
    if manifest.exists():
        with open(manifest, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                titles[row["arxiv_id"].replace("/", "_")] = row["title"]
    data["titles"] = titles

    blob = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    template = Path(args.template).read_text(encoding="utf-8")
    Path(args.out).write_text(template.replace("__DATA__", blob), encoding="utf-8")
    print(f"Wrote {args.out} ({Path(args.out).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
