"""Open an AI-tailored resume (output/cv-*.tex, v2 layout) in the Resume Editor and save it back.

parse(tex) -> doc   turns the LaTeX into editable pieces (summary, jobs + bullets, education, skills, ...).
                    Anything it can't read safely becomes a "raw" section that is kept exactly as written.
render(doc) -> tex  writes the same v2 layout back (build_resume.PREAMBLE), so the file stays ATS-clean.

Saving keeps the previous version in output/old-versions/edited-in-editor-<date>/ (career-ops rule: never lose a CV),
then rebuilds output/<name>.pdf in place, so the website's "View tailored CV" link, the Apply button and the
Chrome autofill extension all pick up the edited file.
"""
import datetime, glob, os, re, shutil

import build_resume as B

OUTPUT = os.path.join(B.ROOT, "output")
REPORTS = os.path.join(B.ROOT, "reports")
NAME_RE = re.compile(r"^cv-[A-Za-z0-9_.-]+$")


# ---------------------------------------------------------------- LaTeX <-> plain text
def unesc(s):
    """LaTeX -> plain text (the inverse of build_resume.esc). Returns None if LaTeX we don't understand is left."""
    s = s.strip()
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", s)
    accents = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "c": "\u0327"}
    s = re.sub(r"\\([`'^\"~]|c )\{?([A-Za-z])\}?",
               lambda m: __import__("unicodedata").normalize("NFC", m.group(2) + accents[m.group(1).strip()]), s)
    for a, b in ((r"\textasciitilde{}", "~"), (r"\textasciicircum{}", "^"), (r"\textbackslash{}", "\0B"),
                 (r"\{", "\0L"), (r"\}", "\0R"), (r"\&", "&"), (r"\%", "%"), (r"\$", "\0D"), (r"\#", "#"),
                 (r"\_", "_"), (r"$\rightarrow$", "->"), (r"$\leftrightarrow$", "<->"), (r"$\approx$", "\u2248"),
                 ("---", "\u2014"), ("--", "\u2013"), ("``", "\u201c"), ("''", "\u201d")):
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s)
    if "\\" in s or "{" in s or "}" in s or "$" in s:  # LaTeX we can't turn into plain text
        return None
    return s.replace("\0B", "\\").replace("\0L", "{").replace("\0R", "}").replace("\0D", "$")


def _need(v):
    if v is None:
        raise ValueError("unknown LaTeX")
    return v


# ---------------------------------------------------------------- parse
JOB_RE = re.compile(r"\\job\{((?:[^{}]|\{[^{}]*\})*)\}\{((?:[^{}]|\{[^{}]*\})*)\}\{((?:[^{}]|\{[^{}]*\})*)\}\{((?:[^{}]|\{[^{}]*\})*)\}")
HEAD_RE = re.compile(r"^\\textbf\{([^{}]*)\},\s*(.*?)\s*\\hfill\s*(.*?)\s*(?:\\par|\\\\)\s*$")


def parse_entries(body):
    """\\job{..} (or a one-line project header) followed by an itemize, repeated."""
    entries = []
    rest = body.strip()
    while rest:
        rest = re.sub(r"^\\vspace\{[^}]*\}\s*", "", rest).strip()
        if not rest:
            break
        m = JOB_RE.match(rest)
        if m:
            e = {"org": _need(unesc(m.group(1))), "location": _need(unesc(m.group(2))),
                 "title": _need(unesc(m.group(3))), "dates": _need(unesc(m.group(4))), "kind": "job"}
            rest = rest[m.end():].lstrip()
        else:
            line, _, after = rest.partition("\n")
            h = HEAD_RE.match(line.strip())
            if not h:
                raise ValueError("unknown entry header")
            e = {"org": _need(unesc(h.group(1))), "location": _need(unesc(h.group(2))), "title": "",
                 "dates": _need(unesc(h.group(3))), "kind": "line"}
            rest = after.lstrip()
        if not rest.startswith("\\begin{itemize}"):
            raise ValueError("entry without bullets")
        end = rest.index("\\end{itemize}")
        items = rest[len("\\begin{itemize}"):end].split("\\item")
        e["bullets"] = [_need(unesc(i)) for i in items[1:]]
        if items[0].strip():
            raise ValueError("text before first bullet")
        entries.append(e)
        rest = rest[end + len("\\end{itemize}"):].strip()
    return entries


def parse_education(body):
    out = []
    for block in re.split(r"\\par\s*(?:\\vspace\{[^}]*\})?", body):
        block = block.strip()
        if not block:
            continue
        lines = [l.strip() for l in re.split(r"\\\\\s*\n?", block) if l.strip()]
        h = HEAD_RE.match(lines[0] + "\\par")
        if not h:
            raise ValueError("unknown education header")
        e = {"school": _need(unesc(h.group(1))), "location": _need(unesc(h.group(2))),
             "dates": _need(unesc(h.group(3))), "degree": "", "courses": ""}
        for l in lines[1:]:
            if l.startswith("Relevant Coursework:"):
                e["courses"] = _need(unesc(l[len("Relevant Coursework:"):]))
            elif not e["degree"]:
                e["degree"] = _need(unesc(l))
            else:
                raise ValueError("extra education line")
        out.append(e)
    return out


def parse_skills(body):
    out = []
    for l in re.split(r"\\\\", body):
        l = l.strip()
        if not l:
            continue
        m = re.match(r"^\\textbf\{([^{}]*?):?\}\s*(.*)$", l, re.S)
        if not m:
            raise ValueError("unknown skills line")
        out.append({"label": _need(unesc(m.group(1).rstrip(":"))), "text": _need(unesc(m.group(2)))})
    return out


def parse(tex):
    if "\\newcommand{\\job}" not in tex or "\\begin{document}" not in tex:
        raise ValueError("not a v2 resume (no \\job macro)")
    pre, body = tex.split("\\begin{document}", 1)
    body = body.replace("\\end{document}", "")
    fmt = {}
    g = re.search(r"top=([\d.]+)in,bottom=([\d.]+)in,left=([\d.]+)in,right=([\d.]+)in", pre)
    if g:
        fmt["margin"], fmt["side"] = float(g.group(1)), float(g.group(3))
    m = re.search(r"itemsep=([\d.]+)pt", pre)
    if m:
        fmt["itemsep"] = float(m.group(1))
    m = re.search(r"\\fontsize\{([\d.]+)\}\{([\d.]+)\}", body)
    if m:
        fmt["font"], fmt["leading"] = float(m.group(1)), float(m.group(2))
    m = re.search(r"\\setlength\{\\jobgap\}\{([\d.]+)pt\}", pre)
    if m:
        fmt["jobgap"] = float(m.group(1))
    m = re.search(r"\\renewcommand\{\\section\}\[1\]\{\\vspace\{([\d.]+)pt\}", pre)
    if m:
        fmt["secgap"] = float(m.group(1))
    body = re.sub(r"^\s*\\fontsize\{[^}]*\}\{[^}]*\}\\selectfont\s*", "", body)
    hm = re.search(r"\\begin\{center\}.*?\\end\{center\}", body, re.S)
    header = hm.group(0) if hm else ""
    parts = re.split(r"\\section\{([^}]*)\}", body[hm.end():] if hm else body)
    doc = {"format": fmt, "header": header, "sections": []}
    for name, content in zip(parts[1::2], parts[2::2]):
        content = content.strip()
        key = name.upper()
        try:
            if key == "SUMMARY":
                sec = {"type": "summary", "text": _need(unesc(content))}
            elif key in ("EXPERIENCE", "PROJECTS", "ACADEMIC PROJECTS"):
                sec = {"type": "entries", "entries": parse_entries(content)}
            elif key == "EDUCATION":
                sec = {"type": "education", "entries": parse_education(content)}
            elif key == "SKILLS":
                sec = {"type": "skills", "lines": parse_skills(content)}
            elif key == "AFFILIATIONS":
                sec = {"type": "list", "items": [_need(unesc(x)) for x in re.split(r"\\quad\s*\|\s*\\quad", content)]}
            else:
                raise ValueError("unknown section")
        except (ValueError, IndexError):
            try:  # a bare bullet list with no job header
                if not (content.startswith("\\begin{itemize}") and content.endswith("\\end{itemize}")):
                    raise ValueError
                items = content[len("\\begin{itemize}"):-len("\\end{itemize}")].split("\\item")
                if items[0].strip():
                    raise ValueError
                sec = {"type": "bullets", "items": [_need(unesc(i)) for i in items[1:]]}
                sec["name"] = name
                doc["sections"].append(sec)
                continue
            except ValueError:
                pass
            try:  # plain one-line paragraphs, e.g. "\textbf{Project} (Dec 2025): what it did."
                lines = "\\\\" in content  # separated by \\ line breaks rather than blank lines
                paras = [p for p in re.split(r"\\\\|\n\s*\n|\\par\b", content) if p.strip()]
                sec = {"type": "paras", "lines": lines, "items": [_need(unesc(p)) for p in paras]}
            except ValueError:
                sec = {"type": "raw", "tex": content}
        sec["name"] = name
        doc["sections"].append(sec)
    return doc


# ---------------------------------------------------------------- render
def render(doc):
    out = [B.PREAMBLE % B.fmt_vals(doc.get("format"))]
    out.append((doc.get("header") or B.contact_block(B.load()).strip()) + "\n\n")
    for s in doc["sections"]:
        out.append("\\section{%s}\n" % s["name"])
        t = s["type"]
        if t == "summary":
            out.append(B.esc(s["text"]) + "\n\n")
        elif t == "entries":
            for i, e in enumerate(s["entries"]):
                if i:
                    out.append("\\vspace{\\jobgap}\n")
                if e.get("kind") == "line" and not e.get("title"):
                    out.append("\\textbf{%s}, %s \\hfill %s\\par\n" % (B.esc(e["org"]), B.esc(e["location"]), B.esc(e["dates"])))
                else:
                    out.append("\\job{%s}{%s}{%s}{%s}\n" % (B.esc(e["org"]), B.esc(e["location"]),
                                                          B.esc(e["title"]), B.esc(e["dates"])))
                out.append("\\begin{itemize}\n")
                for b in e["bullets"]:
                    if b.strip():
                        out.append("  \\item %s\n" % B.esc(b))
                out.append("\\end{itemize}\n\n")
        elif t == "education":
            for i, e in enumerate(s["entries"]):
                if i:
                    out.append("\\vspace{2pt}\n")
                out.append("\\textbf{%s}, %s \\hfill %s\\\\\n%s" % (B.esc(e["school"]), B.esc(e["location"]),
                                                                  B.esc(e["dates"]), B.esc(e["degree"])))
                if e.get("courses", "").strip():
                    out.append("\\\\\nRelevant Coursework: %s" % B.esc(e["courses"]))
                out.append("\\par\n")
            out.append("\n")
        elif t == "skills":
            out.append("\\\\\n".join("\\textbf{%s:} %s" % (B.esc(l["label"]), B.esc(l["text"])) for l in s["lines"]))
            out.append("\n\n")
        elif t == "bullets":
            out.append("\\begin{itemize}\n" + "".join("  \\item %s\n" % B.esc(x) for x in s["items"] if x.strip())
                       + "\\end{itemize}\n\n")
        elif t == "paras":
            sep = "\\\\\n" if s.get("lines") else "\n\n"
            out.append(sep.join(B.esc(x) for x in s["items"] if x.strip()) + "\n\n")
        elif t == "list":
            out.append(" \\quad | \\quad ".join(B.esc(x) for x in s["items"] if x.strip()) + "\n\n")
        else:
            out.append(s["tex"].strip() + "\n\n")
    out.append("\\end{document}\n")
    return "".join(out)


# ---------------------------------------------------------------- files
def safe_name(name):
    name = os.path.basename(name or "")
    name = re.sub(r"\.(tex|pdf)$", "", name)
    if not NAME_RE.match(name) or not os.path.isfile(os.path.join(OUTPUT, name + ".tex")):
        return None
    return name


def for_report(n):
    """The tailored CV named in a report's header (**PDF:** output/cv-...pdf), as a bare name."""
    n = str(n).lstrip("0") or "0"
    for p in glob.glob(os.path.join(REPORTS, "*.md")):
        if os.path.basename(p).split("-")[0].lstrip("0") != n:
            continue
        try:
            head = open(p, encoding="utf-8").read().splitlines()[:40]
        except OSError:
            continue
        for line in head:
            if line.startswith("**PDF:**"):
                m = re.search(r"output/([A-Za-z0-9_.-]+?)\.(pdf|tex)\b", line)
                if m and safe_name(m.group(1)):
                    return m.group(1), os.path.basename(p)
    # fallback: data/pdf-index.tsv (report <TAB> output/cv-....pdf), the index the website itself uses
    try:
        with open(os.path.join(B.ROOT, "data", "pdf-index.tsv"), encoding="utf-8") as f:
            rows = [l.rstrip("\n").split("\t") for l in f if not l.startswith("#")]
    except OSError:
        rows = []
    for r in reversed(rows):
        if len(r) > 1 and r[0].lstrip("0") == n:
            m = re.search(r"output/([A-Za-z0-9_.-]+?)\.pdf$", r[1])
            if m and safe_name(m.group(1)):
                return m.group(1), None
    return None, None


_backed_up = {}


def save(name, doc):
    path = os.path.join(OUTPUT, name + ".tex")
    # keep the version from before this editing session (once per 10 minutes per file)
    now = datetime.datetime.now()
    last = _backed_up.get(name)
    if not last or (now - last).total_seconds() > 600:
        dest = os.path.join(OUTPUT, "old-versions", "edited-in-editor-" + now.strftime("%Y-%m-%d"))
        os.makedirs(dest, exist_ok=True)
        stamp = now.strftime("%H%M%S")
        for ext in (".tex", ".pdf"):
            src = os.path.join(OUTPUT, name + ext)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(dest, "%s_%s%s" % (name, stamp, ext)))
        _backed_up[name] = now
    tex = render(doc)
    B.write(path, tex)
    pdf, pages, err = B.compile_tex(tex, name, outdir=OUTPUT)
    return {"file": name, "pdf": pdf, "pages": pages, "error": err}
