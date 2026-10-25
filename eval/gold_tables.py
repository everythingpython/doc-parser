#!/usr/bin/env python3
"""Extract ground-truth tables from arXiv LaTeX sources (stdlib; pypdf optional).

Usage: python3 -I gold_tables.py PAPERS_DB_DIR OUT_JSON
Reads PAPERS_DB_DIR/source/*.tar.gz, writes OUT_JSON.
"""
import gzip
import io
import json
import re
import sys
import tarfile
import tempfile
from pathlib import Path

RULES = re.compile(
    r"\\(?:hline|toprule|midrule|bottomrule|centering|noindent|small|footnotesize|"
    r"scriptsize|tiny|normalsize|large|Large|bfseries|itshape|bf|em|it|rm|sc|tt|sf|xspace|left|right)(?![A-Za-z])"
    r"|\\cline\{[^}]*\}|\\cmidrule(?:\([^)]*\))?\{[^}]*\}"
    r"|\\(?:rowcolor|cellcolor)(?:\[[^\]]*\])?\{[^}]*\}"
)
SYMBOLS = {
    "times": "×", "pm": "±", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
    "approx": "≈", "cdot": "·", "ldots": "...", "dots": "...", "checkmark": "✓",
    "rightarrow": "→", "to": "→", "alpha": "α", "beta": "β", "mu": "μ", "cmark": "✓", "xmark": "×",
}
UNWRAP1 = ["textbf", "textit", "emph", "texttt", "text", "textsc", "textsf", "textrm",
           "textnormal", "mathrm", "mathbf", "mathit", "mathsf", "mathtt", "mathcal",
           "underline", "mbox", "makecell", "thead", "shortstack", "mathbb", "mathbbm", "mathds", "boldsymbol", "bm", "ensuremath"]
DROP1 = ["cite", "citep", "citet", "ref", "eqref", "label", "footnote", "vspace",
         "hspace", "vphantom", "hphantom"]


def group(s, i):
    """s[i] == '{'. Return (content, index after the matching '}')."""
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def skip_ws(s, i):
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def replace_macro(text, name, nargs, keep):
    """Replace \\name{a}{b}.. by arg number `keep` (or drop it when keep is None)."""
    pat = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z])\*?")
    out, pos = [], 0
    while True:
        m = pat.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        i, args = m.end(), []
        for _ in range(nargs):
            i = skip_ws(text, i)
            while i < len(text) and text[i] == "[":
                j = text.find("]", i)
                i = j + 1 if j != -1 else len(text)
                i = skip_ws(text, i)
            if i < len(text) and text[i] == "{":
                g, i = group(text, i)
                args.append(g)
            else:
                break
        if keep is not None and len(args) > keep:
            out.append(args[keep])
        pos = i
    return "".join(out)


def strip_comments(t):
    return re.sub(r"(?<!\\)%.*", "", t)


MACROS = {}


def collect_macros(text):
    MACROS.clear()
    for m in re.finditer(r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\\([A-Za-z]+)\}?\s*(?=\{|\[)", text):
        i = m.end()
        if text[i:i + 1] == "{":
            MACROS[m.group(1)] = group(text, i)[0]
    for m in re.finditer(r"\\def\s*\\([A-Za-z]+)\s*\{", text):
        MACROS[m.group(1)] = group(text, m.end() - 1)[0]


def strip_nested_tabular(t):
    pat = re.compile(r"\\begin\{(tabular\*?|tabularx|tabulary)\}")
    while True:
        m = pat.search(t)
        if not m:
            break
        i = skip_ws(t, m.end())
        if t[i:i + 1] == "[":
            i = t.find("]", i) + 1
        for _ in range(1 if m.group(1) == "tabular" else 2):
            i = skip_ws(t, i)
            if t[i:i + 1] == "{":
                _, i = group(t, i)
        t = t[:m.start()] + " " + t[i:]
    return re.sub(r"\\end\{(?:tabular\*?|tabularx|tabulary)\}", " ", t)


def clean_cell(t, warn):
    t = re.sub(r"\\\\(\[[^\]]*\])?", " ", t)
    t = RULES.sub(" ", t)
    for name, body in MACROS.items():
        if name in SYMBOLS or name in ("cmark", "xmark"):
            continue
        t = re.sub(r"\\" + re.escape(name) + r"(?![A-Za-z])\s*", lambda m, b=body: b + " ", t)
    t = strip_nested_tabular(t)
    t = re.sub(r"^\s*\[[^\]]*\d(?:pt|em|ex|mm|cm)\]", "", t)
    t = replace_macro(t, "specialrule", 3, None)
    t = replace_macro(t, "rotatebox", 2, 1)
    t = replace_macro(t, "multirow", 3, 2)
    t = replace_macro(t, "textcolor", 2, 1)
    t = replace_macro(t, "href", 2, 1)
    for n in UNWRAP1:
        t = replace_macro(t, n, 1, 0)
    for n in DROP1:
        t = replace_macro(t, n, 1, None)
    t = t.replace(r"\$", "\x00")
    for k, v in SYMBOLS.items():
        t = re.sub(r"\\" + k + r"(?![A-Za-z])", v, t)
    for esc, ch in ((r"\%", "%"), (r"\&", "&"), (r"\_", "_"), (r"\#", "#"),
                    (r"\{", "{"), (r"\}", "}")):
        t = t.replace(esc, ch)
    t = t.replace("~", " ").replace("$", "").replace("{", "").replace("}", "")
    warn.extend(re.findall(r"\\[A-Za-z]+", t))
    t = re.sub(r"\\[A-Za-z]+\*?", " ", t).replace("\\", " ").replace("\x00", "$")
    return re.sub(r"\s+", " ", t).strip()


def split_table(body):
    rows, cells, buf, depth, env, i = [], [], [], 0, 0, 0

    def end_cell():
        cells.append("".join(buf))
        buf.clear()

    while i < len(body):
        c = body[i]
        if c == "\\":
            if body.startswith("\\begin{", i):
                env += 1
            elif body.startswith("\\end{", i):
                env = max(0, env - 1)
            if body[i + 1:i + 2] == "\\" and depth == 0 and env == 0:
                i += 2
                if body[i:i + 1] == "*":
                    i += 1
                m = re.match(r"\s*\[[^\]]*\]", body[i:])
                if m:
                    i += m.end()
                end_cell()
                rows.append(cells[:])
                cells.clear()
                continue
            buf.append(body[i:i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif c == "&" and depth == 0 and env == 0:
            end_cell()
            i += 1
            continue
        buf.append(c)
        i += 1
    end_cell()
    rows.append(cells[:])
    return rows


def parse_rows(body, warn):
    out, unc = [], []
    for raw in split_table(body):
        row, urow = [], []
        for cell in raw:
            cell = re.sub(r"\\(?:toprule|midrule|bottomrule|hline)\s*\[[^\]]*\]", " ", cell)
            cell = RULES.sub(" ", cell)
            m = re.match(r"\s*\\multicolumn\s*\{(\d+)\}", cell)
            span = 1
            if m:
                span = int(m.group(1))
                i = skip_ws(cell, m.end())
                if i < len(cell) and cell[i] == "{":
                    _, i = group(cell, i)
                i = skip_ws(cell, i)
                cell = group(cell, i)[0] if i < len(cell) and cell[i] == "{" else ""
            before = len(warn)
            if CITE_RE.search(cell):
                # The PDF shows "[24]" or "[Author, 2011]" here, which depends on the bibliography.
                warn.append("cite")
            row.append(clean_cell(cell, warn))
            urow.append(len(warn) > before)
            row.extend([""] * (span - 1))
            urow.extend([False] * (span - 1))
        if any(row):
            out.append(row)
            unc.append(urow)
    width = max((len(r) for r in out), default=0)
    return ([r + [""] * (width - len(r)) for r in out],
            [u + [False] * (width - len(u)) for u in unc])


CITE_RE = re.compile(r"\\(?:cite[A-Za-z]*|ref|autoref|eqref|cref|Cref)\*?\s*(?:\[[^\]]*\]\s*)*\{")

BEGIN = re.compile(r"\\begin\{(tabular\*|tabularx|tabulary|longtable|longtabu|tabu|tabular)\}")


def find_tabulars(text):
    found, last_end = [], -1
    for m in BEGIN.finditer(text):
        if m.start() < last_end:
            continue
        env, i = m.group(1), skip_ws(text, m.end())
        if text[i:i + 1] == "[":
            i = text.find("]", i) + 1
        if env in ("tabu", "longtabu"):
            m2 = re.match(r"\s*(?:to|spread)\s*[^\s{]+", text[i:])
            if m2:
                i += m2.end()
        for _ in range(2 if env in ("tabular*", "tabularx", "tabulary") else 1):
            i = skip_ws(text, i)
            if text[i:i + 1] == "{":
                _, i = group(text, i)
        begin_tag, end_tag = "\\begin{%s}" % env, "\\end{%s}" % env
        depth, j, end = 1, i, -1
        while j < len(text):
            nb, ne = text.find(begin_tag, j), text.find(end_tag, j)
            if ne == -1:
                break
            if nb != -1 and nb < ne:
                depth += 1
                j = nb + len(begin_tag)
            else:
                depth -= 1
                j = ne + len(end_tag)
                if depth == 0:
                    end = ne
                    break
        if end == -1:
            continue
        found.append((m.start(), end + len(end_tag), text[i:end]))
        last_end = end + len(end_tag)
    return found


def caption_of(float_text):
    m = re.search(r"\\caption(?![A-Za-z])", float_text)
    if not m:
        return ""
    i = skip_ws(float_text, m.end())
    if float_text[i:i + 1] == "[":
        i = float_text.find("]", i) + 1
    i = skip_ws(float_text, i)
    if float_text[i:i + 1] != "{":
        return ""
    return clean_cell(group(float_text, i)[0], [])


def inline_inputs(text, files, depth=0):
    if depth > 4:
        return text

    def rep(m):
        t = files.get(Path(m.group(1)).stem)
        return inline_inputs(strip_comments(t), files, depth + 1) if t is not None else ""

    return re.sub(r"\\(?:input|include)\{([^}]+)\}", rep, text)


def unpack(path, dest):
    data = path.read_bytes()
    base = dest.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for mem in tf.getmembers():
                target = (dest / mem.name).resolve()
                if not (mem.isfile() or mem.isdir()) or not str(target).startswith(str(base)):
                    continue
                try:
                    tf.extract(mem, dest, filter="data")
                except TypeError:
                    tf.extract(mem, dest)
        return True
    except tarfile.TarError:
        pass
    try:
        txt = gzip.decompress(data)
    except OSError:
        return False
    if b"\\begin" not in txt and b"\\documentclass" not in txt:
        return False
    (dest / "main.tex").write_bytes(txt)
    return True


def paper_text(d):
    files = {p.stem: p.read_text(errors="ignore") for p in d.rglob("*.tex")}
    if not files:
        return None
    root = next((t for t in files.values() if "\\begin{document}" in t), None)
    if root is not None:
        return inline_inputs(strip_comments(root), files)
    return "\n".join(strip_comments(t) for t in files.values())


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pdf_norm_text(pdf):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    if not pdf.exists():
        return None
    try:
        return norm("".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages))
    except Exception:
        return None


def extract_paper(text):
    collect_macros(text)
    floats = [(m.start(), m.end(), m.group(2))
              for m in re.finditer(r"\\begin\{(table\*?)\}(.*?)\\end\{\1\}", text, re.S)]
    tables, fnum, inum = [], 0, 0
    used = []
    for start, end, ftext in floats:
        fnum += 1
        tabs = find_tabulars(ftext)
        cap = caption_of(ftext)
        for k, (_, _, body) in enumerate(tabs):
            warn = []
            rows, unc = parse_rows(body, warn)
            tid = f"T{fnum}" + (chr(97 + k) if len(tabs) > 1 else "")
            tables.append(dict(id=tid, kind="float", caption=cap, rows=rows, uncertain=unc, warnings=sorted(set(warn))))
        used.append((start, end))
    for s, e, body in find_tabulars(text):
        if any(a <= s < b for a, b in used):
            continue
        inum += 1
        warn = []
        rows, unc = parse_rows(body, warn)
        tables.append(dict(id=f"I{inum}", kind="inline", caption="", rows=rows, uncertain=unc, warnings=sorted(set(warn))))
    for t in tables:
        t["n_rows"] = len(t["rows"])
        t["n_cols"] = len(t["rows"][0]) if t["rows"] else 0
        t["degenerate"] = t["n_rows"] < 2 or t["n_cols"] < 2
    return tables


# Verified by hand against the PDF: the LaTeX writes a two-line header as two rows,
# but the PDF shows one header row (each cell wraps over two lines).
ROW_MERGES = {("1812.03651", "T1"): (0, 1)}


def merge_rows(t, a, b):
    t["rows"][a] = [(x + " " + y).strip() for x, y in zip(t["rows"][a], t["rows"][b])]
    t["uncertain"][a] = [x or y for x, y in zip(t["uncertain"][a], t["uncertain"][b])]
    del t["rows"][b], t["uncertain"][b]
    t["n_rows"] = len(t["rows"])
    t["degenerate"] = t["n_rows"] < 2 or t["n_cols"] < 2
    t.setdefault("notes", []).append(f"rows {a} and {b} merged (two-line header)")


def main():
    papers_dir, out_json = Path(sys.argv[1]), Path(sys.argv[2])
    result, summary = {}, []
    for tarball in sorted((papers_dir / "source").glob("*.tar.gz")):
        pid = tarball.name[: -len(".tar.gz")]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            if not unpack(tarball, dest):
                summary.append((pid, "no LaTeX source", 0, 0, 0, None))
                continue
            text = paper_text(dest)
        if text is None:
            summary.append((pid, "no .tex files", 0, 0, 0, None))
            continue
        tables = extract_paper(text)
        for t in tables:
            if (pid, t["id"]) in ROW_MERGES:
                merge_rows(t, *ROW_MERGES[(pid, t["id"])])
        ptxt = pdf_norm_text(papers_dir / f"{pid}.pdf")
        for t in tables:
            cells = [c for r in t["rows"] for c in r if len(norm(c)) >= 3]
            t["pdf_cell_match"] = (round(sum(norm(c) in ptxt for c in cells) / len(cells), 2)
                                   if ptxt and cells else None)
            t["usable"] = (not t["degenerate"] and "includegraphics" not in t["warnings"]
                           and (t["pdf_cell_match"] is None or t["pdf_cell_match"] >= 0.5))
        result[pid] = tables
        fl = [t for t in tables if t["usable"]]
        ms = [t["pdf_cell_match"] for t in fl if t["pdf_cell_match"] is not None]
        summary.append((pid, "ok", len(fl), sum(t["kind"] == "inline" for t in tables),
                        sum(t["degenerate"] for t in tables),
                        round(sum(ms) / len(ms), 2) if ms else None))
    out_json.write_text(json.dumps({"papers": result}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{'paper':<14}{'status':<18}{'float tables':>13}{'inline':>8}{'degenerate':>11}{'avg pdf match':>14}")
    for row in summary:
        print(f"{row[0]:<14}{row[1]:<18}{row[2]:>13}{row[3]:>8}{row[4]:>11}{str(row[5]):>14}")
    print("TOTAL float tables:", sum(r[2] for r in summary))


if __name__ == "__main__":
    main()
