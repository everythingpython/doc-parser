#!/usr/bin/env python3
"""Sanity-check the scorer on fake parser output with known, injected errors.

  python3 selftest.py                  # run checks in a temp folder
  python3 selftest.py --keep DIR       # also keep the fake outputs and results in DIR
"""
import argparse
import html
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

EVAL = Path(__file__).resolve().parent
GOLD = EVAL / "gold_tables.json"
PAPERS = EVAL.parent / "papers_db"


def md_table(rows, extra_col=False):
    esc = lambda c: c.replace("|", "\\|")
    lines = []
    for i, r in enumerate(rows):
        cells = ([str(i + 1)] if extra_col else []) + [esc(c) for c in r]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + "---|" * len(cells))
    return "\n".join(lines)


def html_table(rows):
    skip, span = set(), {}
    for i in range(len(rows)):
        if rows[i][0] and (i, 0) not in skip:
            k = 0
            while i + k + 1 < len(rows) and not rows[i + k + 1][0]:
                k += 1
                skip.add((i + k, 0))
            if k:
                span[i] = k + 1
    out = ["<table>"]
    for i, r in enumerate(rows):
        tag = "th" if i == 0 else "td"
        cells = []
        for j, c in enumerate(r):
            if (i, j) in skip:
                continue
            rs = f' rowspan="{span[i]}"' if j == 0 and i in span else ""
            cells.append(f"<{tag}{rs}>{html.escape(c)}</{tag}>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep")
    args = ap.parse_args()
    random.seed(7)

    gold = json.loads(GOLD.read_text())["papers"]
    pids = sorted(p.stem for p in PAPERS.glob("*.pdf"))
    use = {pid: [t for t in ts if t.get("usable")] for pid, ts in gold.items()}
    n_gold = sum(len(v) for v in use.values())

    tmp = tempfile.TemporaryDirectory()
    root = Path(args.keep) if args.keep else Path(tmp.name)
    for eng in ("fake_good", "fake_html", "fake_bad"):
        (root / "outputs" / eng).mkdir(parents=True, exist_ok=True)

    dropped = ("1802.10233", "T1")
    for pid in pids:
        parts = {"fake_good": [f"# {pid}\n\nSome body text about databases and indexes.\n"],
                 "fake_html": [f"# {pid}\n\nSome body text about databases and indexes.\n"],
                 "fake_bad": [f"# {pid}\n\nSome body text about databases and indexes.\n"]}
        for t in use.get(pid, []):
            parts["fake_good"].append(md_table(t["rows"]))
            parts["fake_html"].append(html_table(t["rows"]))
            if (pid, t["id"]) == dropped:
                continue  # the bad parser misses this table entirely
            rows = [r[:] for r in t["rows"]]
            for _ in range(2):  # inject a typo into two long-ish cells
                cand = [(i, j) for i, r in enumerate(rows) for j, c in enumerate(r) if len(c) >= 8]
                if cand:
                    i, j = random.choice(cand)
                    rows[i][j] = rows[i][j][:-1]
            parts["fake_bad"].append(md_table(rows, extra_col=True))  # shifts every column by one
        if pid == "1802.10233":
            parts["fake_bad"].append(md_table([["Figure", "Value"], ["not", "a table"]]))  # bogus table
        for eng, chunks in parts.items():
            (root / "outputs" / eng / f"{pid}.md").write_text("\n\n".join(chunks), encoding="utf-8")
    for eng in ("fake_good", "fake_html", "fake_bad"):
        (root / "outputs" / eng / "_timings.json").write_text(json.dumps(
            {pid: {"secs": round(random.uniform(5, 60), 1), "pages": 10} for pid in pids}))

    subprocess.run([sys.executable, str(EVAL / "score.py"), "--outputs", str(root / "outputs"),
                    "--gold", str(GOLD), "--papers", str(PAPERS), "--out", str(root)], check=True)
    s = json.loads((root / "results.json").read_text())["summary"]

    checks = [
        ("good parser finds every table", s["fake_good"]["tables_found"] == n_gold),
        ("good parser: position accuracy 100%", s["fake_good"]["position_acc"] > 0.999),
        ("good parser: no extra tables", s["fake_good"]["false_tables"] == 0),
        ("good parser: precision about 100%", s["fake_good"]["precision"] > 0.99),
        ("html tables (rowspan) score like markdown", s["fake_html"]["position_acc"] > 0.999
         and s["fake_html"]["tables_found"] == n_gold),
        ("bad parser misses the dropped table", s["fake_bad"]["tables_found"] == n_gold - 1),
        ("bad parser: shifted columns wreck position accuracy", s["fake_bad"]["position_acc"] < 0.25),
        ("bad parser: content recall stays high despite shifts", s["fake_bad"]["content_recall"] > 0.7),
        ("bad parser: typos recovered as near matches", s["fake_bad"]["soft_recall"] > s["fake_bad"]["content_recall"]),
        ("bad parser: bogus table counted as extra", s["fake_bad"]["false_tables"] >= 1),
    ]
    print()
    failed = 0
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
        failed += not ok
    if args.keep:
        print(f"\nKept synthetic outputs and results in {root}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
