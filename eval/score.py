#!/usr/bin/env python3
"""Score parser output against gold tables extracted from LaTeX (stdlib only;
pypdf optional for the text-coverage number).

  python3 score.py                # uses ./outputs/<engine>/*.md
  python3 score.py --outputs DIR --gold FILE --papers DIR --out DIR

Writes results.json (feeds report.html) and results.csv.
"""
import argparse
import csv
import datetime
import difflib
import html
import json
import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

EVAL = Path(__file__).resolve().parent
NEAR = 0.85       # similarity at which two cells count as "near" matches
MATCH_MIN = 0.25  # minimum content overlap (F1) to call a parsed table "the same table"

NOTES = [
    "Gold tables come from the papers' LaTeX source, so they are exact, but only for tables that exist in the source (not tables embedded as images).",
    "Cells containing math or unresolved LaTeX macros are marked uncertain and excluded from scoring.",
    "Position accuracy is strict: a cell is right only if the same text sits at the same row and column. Merged or shifted headers lower it.",
    "Content recall asks whether the gold cell's text appears anywhere in the matched table, so it ignores structure.",
    "Text coverage compares words in the output with the PDF's own text layer. It is a rough omission check, not a quality score.",
    "Small sample: with a few dozen tables, treat differences of a few points as noise.",
]

# ---------- normalisation ----------
CHECKS, CROSSES = "✓✔☑√", "×✗✘✕"


def norm_cell(s):
    """Lowercase, strip markdown/HTML, unify dashes and check/cross glyphs, drop
    everything except letters, digits and a few meaningful symbols."""
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[‐‑‒–—−]", "-", s)
    for c in CHECKS:
        s = s.replace(c, "✓")
    for c in CROSSES:
        s = s.replace(c, "×")
    s = re.sub(r"[*_`\\]", "", s)
    return re.sub(r"[^a-z0-9.%+\-✓×]", "", s).strip(".")


# ---------- reading tables out of parser output ----------
SEP = re.compile(r"^\|?:?-{2,}:?(\|:?-{2,}:?)*\|?$")


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def pipe_tables(text):
    tables, cur = [], []
    for line in text.splitlines() + [""]:
        st = line.strip()
        if st.startswith("|"):
            cur.append(st)
            continue
        if len(cur) >= 2:
            rows = [split_row(l) for l in cur if not SEP.match(l.replace(" ", ""))]
            if rows:
                tables.append(rows)
        cur = []
    return tables


def _int(v):
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return 1


class _HTMLTables(HTMLParser):
    """Collects <table> elements, expanding colspan/rowspan into a rectangular grid
    (merged cells keep their text in the first cell, the rest are empty)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.depth = [], 0
        self.rows = self.cells = self.text = None
        self.occupied, self.span = {}, (1, 1)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.rows, self.occupied = [], {}
            return
        if self.depth != 1:
            return
        if tag == "tr":
            self.cells = []
        elif tag in ("td", "th"):
            self.text, self.span = [], (_int(a.get("colspan")), _int(a.get("rowspan")))
        elif tag == "br" and self.text is not None:
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            if self.depth == 1 and self.rows is not None:
                self.tables.append(self.rows)
                self.rows = None
            self.depth = max(0, self.depth - 1)
            return
        if self.depth != 1:
            return
        if tag in ("td", "th") and self.text is not None and self.cells is not None:
            self.cells.append(("".join(self.text), *self.span))
            self.text = None
        elif tag == "tr" and self.cells is not None:
            self._finish_row()
            self.cells = None

    def handle_data(self, data):
        if self.text is not None:
            self.text.append(data)

    def _finish_row(self):
        row, col = [], 0

        def fill():
            nonlocal col
            while self.occupied.get(col, 0) > 0:
                row.append("")
                self.occupied[col] -= 1
                col += 1

        for text, colspan, rowspan in self.cells:
            fill()
            row.append(text.strip())
            row.extend([""] * (colspan - 1))
            if rowspan > 1:
                for k in range(colspan):
                    self.occupied[col + k] = rowspan - 1
            col += colspan
        fill()
        if any(c for c in row):
            self.rows.append(row)


def extract_tables(text):
    tables = pipe_tables(text)
    parser = _HTMLTables()
    try:
        parser.feed(text)
    except Exception:
        pass
    tables += parser.tables
    out = []
    for t in tables:
        width = max((len(r) for r in t), default=0)
        if len(t) >= 2 and width >= 2:
            out.append([r + [""] * (width - len(r)) for r in t])
    return out


# ---------- comparing one gold table with one parsed table ----------
def compare(G, U, C):
    """Return per-cell states for the gold grid and the parsed grid, plus metrics.

    Gold states:   ok (same text, same position), moved (same text elsewhere in the
                   table), near (similar text), missing, empty, uncertain.
    Parsed states: ok, moved, near, extra (matches nothing in gold), empty.
    """
    gn = [[norm_cell(x) for x in r] for r in G]
    cn = [[norm_cell(x) for x in r] for r in C]
    gs = [["empty" if not g else None for g in r] for r in gn]
    for i, r in enumerate(U):
        for j, u in enumerate(r):
            if u and gs[i][j] is None:
                gs[i][j] = "uncertain"
    cs = [["empty" if not x else "extra" for x in r] for r in cn]
    free = {}  # normalised text -> unclaimed positions in the parsed table
    for i, r in enumerate(cn):
        for j, x in enumerate(r):
            if x:
                free.setdefault(x, []).append((i, j))

    def todo():
        return [(i, j) for i, r in enumerate(gs) for j, s in enumerate(r) if s is None]

    for i, j in todo():  # pass 1: same text, same position
        g = gn[i][j]
        if i < len(cn) and j < len(cn[i]) and cn[i][j] == g and (i, j) in free.get(g, []):
            free[g].remove((i, j))
            gs[i][j] = cs[i][j] = "ok"
    for i, j in todo():  # pass 2: same text elsewhere
        g = gn[i][j]
        if free.get(g):
            pi, pj = free[g].pop(0)
            gs[i][j] = "moved"
            cs[pi][pj] = "moved"
    for i, j in todo():  # pass 3: similar text
        g, best, where = gn[i][j], 0.0, None
        if len(g) >= 4:
            for x, positions in free.items():
                if not positions:
                    continue
                sm = difflib.SequenceMatcher(None, g, x)
                if sm.real_quick_ratio() < NEAR or sm.quick_ratio() < NEAR:
                    continue
                r = sm.ratio()
                if r > best:
                    best, where = r, (x, positions[0])
        if where and best >= NEAR:
            free[where[0]].remove(where[1])
            gs[i][j] = "near"
            cs[where[1][0]][where[1][1]] = "near"
        else:
            gs[i][j] = "missing"

    for i, r in enumerate(gs):  # untrusted gold cells: do not count the parsed cell against precision
        for j, st in enumerate(r):
            if st == "uncertain" and i < len(cs) and j < len(cs[i]) and cs[i][j] == "extra":
                cs[i][j] = "uncertain"
    states = [s for r in gs for s in r]
    n = sum(s in ("ok", "moved", "near", "missing") for s in states)
    ok, moved, near = (states.count(k) for k in ("ok", "moved", "near"))
    cand_cells = sum(1 for r in cs for st in r if st not in ("empty", "uncertain"))
    matched = sum(1 for r in cs for s in r if s in ("ok", "moved", "near"))
    return dict(
        gold_states=gs, cand_states=cs, scored_cells=n,
        position_acc=ok / n if n else None,
        content_recall=(ok + moved) / n if n else None,
        soft_recall=(ok + moved + near) / n if n else None,
        precision=matched / cand_cells if cand_cells else None,
        rows_gold=len(G), cols_gold=len(G[0]) if G else 0,
        rows_out=len(C), cols_out=len(C[0]) if C else 0,
    )


def bag(rows, skip=None):
    c = Counter()
    for i, r in enumerate(rows):
        for j, x in enumerate(r):
            if skip and skip[i][j]:
                continue
            n = norm_cell(x)
            if n:
                c[n] += 1
    return c


# ---------- text coverage ----------
def pdf_words(pdf):
    try:
        from pypdf import PdfReader

        text = " ".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages)
    except Exception:
        return None
    return set(re.findall(r"[a-z]{4,}", text.lower()))


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", default=str(EVAL / "outputs"))
    ap.add_argument("--gold", default=str(EVAL / "gold_tables.json"))
    ap.add_argument("--papers", default=str(EVAL.parent / "papers_db"))
    ap.add_argument("--out", default=str(EVAL))
    args = ap.parse_args()
    outputs, papers, outdir = Path(args.outputs), Path(args.papers), Path(args.out)

    gold = json.loads(Path(args.gold).read_text())["papers"]
    tables = []
    for pid, ts in gold.items():
        for t in ts:
            if t.get("usable"):
                tables.append(dict(paper=pid, id=t["id"], kind=t["kind"], caption=t["caption"],
                                   rows=t["rows"], uncertain=t["uncertain"], engines={}))
    engines = sorted(d.name for d in outputs.iterdir() if d.is_dir() and not d.name.startswith("_")) \
        if outputs.is_dir() else []
    if not engines:
        raise SystemExit(f"No engine folders found in {outputs}. Run run_batch.py first.")

    pdf_ids = sorted(p.stem for p in papers.glob("*.pdf"))
    ref_words = {pid: pdf_words(papers / f"{pid}.pdf") for pid in pdf_ids}
    paper_info, texts = {pid: {"engines": {}} for pid in pdf_ids}, {}
    summary = {}

    for eng in engines:
        timings_file = outputs / eng / "_timings.json"
        timings = json.loads(timings_file.read_text()) if timings_file.exists() else {}
        texts[eng] = {}
        for pid in pdf_ids:
            f = outputs / eng / f"{pid}.md"
            md = f.read_text(encoding="utf-8", errors="replace") if f.exists() else None
            texts[eng][pid] = md
            cands = extract_tables(md) if md else []
            mine = [t for t in tables if t["paper"] == pid]

            pairs = []
            for gi, t in enumerate(mine):
                gb = bag(t["rows"], t["uncertain"])
                for ci, c in enumerate(cands):
                    cb = bag(c)
                    overlap = sum((gb & cb).values())
                    denom = sum(gb.values()) + sum(cb.values())
                    pairs.append((2 * overlap / denom if denom else 0.0, gi, ci))
            assigned, used_g, used_c = {}, set(), set()
            for score, gi, ci in sorted(pairs, reverse=True):
                if score < MATCH_MIN:
                    break
                if gi in used_g or ci in used_c:
                    continue
                assigned[gi] = (ci, score)
                used_g.add(gi)
                used_c.add(ci)

            for gi, t in enumerate(mine):
                if gi in assigned:
                    ci, score = assigned[gi]
                    res = compare(t["rows"], t["uncertain"], cands[ci])
                    res.update(found=True, match_f1=round(score, 3), cand_rows=cands[ci])
                else:
                    res = dict(found=False, match_f1=0.0, position_acc=0.0, content_recall=0.0,
                               soft_recall=0.0, precision=None, scored_cells=None, cand_rows=None,
                               no_output=md is None)
                t["engines"][eng] = res

            ow = set(re.findall(r"[a-z]{4,}", md.lower())) if md else set()
            ref = ref_words.get(pid)
            tm = timings.get(pid, {})
            paper_info[pid]["engines"][eng] = dict(
                has_output=md is not None, md_chars=len(md) if md else 0,
                secs=tm.get("secs"), pages=tm.get("pages"),
                text_coverage=round(len(ref & ow) / len(ref), 3) if ref and md else None,
                tables_found=len(assigned), tables_gold=len(mine),
                false_tables=len(cands) - len(assigned) if md else None,
            )

        mine_all = [t["engines"][eng] for t in tables]
        found = [r for r in mine_all if r["found"]]
        cells = sum(r["scored_cells"] for r in found)

        def mean(key, rows):
            vals = [r[key] for r in rows if r.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        def weighted(key):
            return (sum(r[key] * r["scored_cells"] for r in found if r[key] is not None) / cells
                    if cells else None)

        secs = sum(v["secs"] for v in timings.values() if v.get("secs") is not None)
        pgs = sum(v["pages"] for v in timings.values() if v.get("secs") is not None and v.get("pages"))
        cov = [p["engines"][eng]["text_coverage"] for p in paper_info.values()
               if p["engines"][eng]["text_coverage"] is not None]
        summary[eng] = dict(
            n_tables=len(tables), tables_found=len(found),
            position_acc=mean("position_acc", mine_all),
            content_recall=mean("content_recall", mine_all),
            soft_recall=mean("soft_recall", mine_all),
            precision=mean("precision", found),
            position_acc_cells=weighted("position_acc"),
            content_recall_cells=weighted("content_recall"),
            false_tables=sum(p["engines"][eng]["false_tables"] or 0 for p in paper_info.values()),
            secs_total=secs or None, secs_per_page=(secs / pgs) if secs and pgs else None,
            text_coverage=sum(cov) / len(cov) if cov else None,
            tier=next((v.get("tier") for v in timings.values() if v.get("tier")), None),
        )

    scored = sum(sum(1 for r in t["rows"] for c in r if c) for t in tables)
    result = dict(
        meta=dict(generated=datetime.datetime.now().isoformat(timespec="seconds"), engines=engines,
                  n_tables=len(tables), n_papers=len(pdf_ids), notes=NOTES,
                  near_threshold=NEAR, match_min=MATCH_MIN, gold_cells=scored),
        summary=summary, papers=paper_info, tables=tables,
    )
    (outdir / "results.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    (outdir / "texts.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")

    with open(outdir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["engine", "paper", "table", "found", "match_f1", "position_acc", "content_recall",
                    "soft_recall", "precision", "scored_cells", "rows_gold", "cols_gold", "rows_out", "cols_out"])
        for t in tables:
            for eng in engines:
                r = t["engines"][eng]
                fmt = lambda v: "" if v is None else round(v, 3)
                w.writerow([eng, t["paper"], t["id"], int(r["found"]), r["match_f1"],
                            fmt(r["position_acc"]), fmt(r["content_recall"]), fmt(r["soft_recall"]),
                            fmt(r["precision"]), r["scored_cells"] if r["scored_cells"] is not None else "",
                            r.get("rows_gold", len(t["rows"])), r.get("cols_gold", len(t["rows"][0]) if t["rows"] else 0),
                            r.get("rows_out", ""), r.get("cols_out", "")])

    pc = lambda v: "-" if v is None else f"{v * 100:.0f}%"
    print(f"{'engine':<14}{'found':>8}{'position':>10}{'recall':>8}{'precision':>11}{'extra tbl':>11}{'s/page':>8}{'text cov':>10}")
    for eng, s in summary.items():
        spp = "-" if s["secs_per_page"] is None else f"{s['secs_per_page']:.1f}"
        print(f"{eng:<14}{str(s['tables_found']) + '/' + str(s['n_tables']):>8}{pc(s['position_acc']):>10}"
              f"{pc(s['content_recall']):>8}{pc(s['precision']):>11}{s['false_tables']:>11}{spp:>8}{pc(s['text_coverage']):>10}")
    print(f"\nWrote {outdir / 'results.json'}, texts.json and results.csv")


if __name__ == "__main__":
    main()
