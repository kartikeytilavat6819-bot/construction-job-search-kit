"""Build your resumes from ONE master file: <career-ops>/master-resume.json.

The master holds every unique point (bullet) you have ever written. Each "track" is just a
selection + order of those points. Tracks are DATA, not code: they are the top-level "tracks"
list in master-resume.json, e.g.

  "tracks": [{"id": "project-engineer", "name": "Project Engineer"},
             {"id": "field", "name": "Field Engineer"}]

A bullet's "tracks" tag says which tracks it fits. "layout" holds each track's picks (summary, which
jobs/bullets in which order, skills lines...). A track with no layout yet gets one generated
automatically from the bullets tagged with it, which you can then refine in the Resume Editor.

  python local/resume-builder/build_resume.py              build every track + the full master
  python local/resume-builder/build_resume.py field        build one track (by its id)
  python local/resume-builder/build_resume.py --md         only rewrite master-resume.md

Outputs (career-ops root):
  resume-<track>.tex / .pdf         one-page v2 (ATS) resume per track - the base for tailoring
  master-resume-full.tex / .pdf     EVERY point, several pages - for reading, not for sending
  master-resume.md                  the same library as Markdown, for AI tailoring (bullet ids + tags)

Optional: set "settings": {"copy_outputs_to": "D:/My resumes"} in master-resume.json to
also copy the PDFs, .tex and master-resume.md into that folder after each build. Off by default.

Bullets with status "never" are never printed; "confirm" ones print only in the full master,
until you mark them "ok".
"""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # career-ops/ (this file lives in career-ops/local/resume-builder/)
MASTER = os.path.join(ROOT, "master-resume.json")
PROFILE_YML = os.path.join(ROOT, "config", "profile.yml")
ALL_SECTIONS = ["SUMMARY", "EXPERIENCE", "PROJECTS", "EDUCATION", "SKILLS", "AFFILIATIONS"]
TRACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

PREAMBLE = r"""%% ATS-friendly resume (v2): single column, standard headings, no hyphenation, text-extractable PDF.
%% GENERATED from master-resume.json by local/resume-builder/build_resume.py - edit there (or in the Resume Editor).
\documentclass[10pt]{article}
\usepackage[letterpaper,top=%(top)sin,bottom=%(top)sin,left=%(side)sin,right=%(side)sin]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\input{glyphtounicode}
\pdfgentounicode=1
\pagestyle{empty}
\setlength{\parindent}{0pt}
\hyphenpenalty=10000
\exhyphenpenalty=10000
\sloppy
\setlist[itemize]{leftmargin=1.1em,itemsep=%(itemsep)spt,topsep=2pt,parsep=0pt,label=\textbullet}
\newlength{\jobgap}\setlength{\jobgap}{%(jobgap)spt}
\renewcommand{\section}[1]{\vspace{%(secgap)spt}{\large\bfseries #1}\par\vspace{-3pt}\rule{\linewidth}{0.4pt}\par\vspace{2pt}}
\newcommand{\job}[4]{\textbf{#1}, #2 \hfill #4\\ \textit{#3}\par}

\begin{document}
\fontsize{%(fs)s}{%(ls)s}\selectfont

"""


# Page layout knobs (the editor's sliders). Defaults = the approved v2 template.
FORMAT_DEFAULTS = {"font": 10, "leading": 12, "margin": 0.5, "side": 0.6, "itemsep": 1, "secgap": 4, "jobgap": 3}


def fmt_vals(fmt):
    f = dict(FORMAT_DEFAULTS, **{k: v for k, v in (fmt or {}).items() if v is not None})
    return {"top": f["margin"], "side": f["side"], "itemsep": f["itemsep"], "fs": f["font"], "ls": f["leading"],
            "secgap": f["secgap"], "jobgap": f["jobgap"]}


def load(path=MASTER):
    with open(path, encoding="utf-8") as f:
        return normalize(json.load(f))


def default_layout(m, tid):
    """A starting layout for a track that has none yet: every job/project with at least one bullet tagged
    for this track (those bullets, in library order), all skills lines and all short affiliations."""
    def picks(entries):
        out = []
        for e in entries:
            ids = [b["id"] for b in e.get("bullets", []) if tid in b.get("tracks", []) and b.get("status", "ok") != "never"]
            if ids:
                out.append({"id": e["id"], "bullets": ids})
        return out
    return {
        "sections": list(ALL_SECTIONS),
        "summary": "",
        "experience": picks(m["experience"]),
        "projects": picks(m["projects"]),
        "show_gpa": False,
        "courses": {e["id"]: list(e.get("courses", []))[:5] for e in m["education"]},
        "skills": [{"label": s["label"], "text": s["text"]} for s in m["skills"]],
        "affiliations": [a["id"] for a in m["affiliations"] if a.get("short")],
        "format": {},
    }


def normalize(m):
    """Fill in optional parts so a hand-written or older master still builds, and give every track a layout."""
    if not isinstance(m.get("contact"), dict):
        m["contact"] = {}
    for k in ("name", "location", "phone", "email", "linkedin"):
        m["contact"].setdefault(k, "")
    for k in ("tracks", "experience", "projects", "education", "skills", "affiliations", "never_claim", "references"):
        if not isinstance(m.get(k), list):
            m[k] = []
    if not isinstance(m.get("layout"), dict):
        m["layout"] = {}
    if not isinstance(m.get("settings"), dict):
        m["settings"] = {"copy_outputs_to": None}
    for e in m["experience"] + m["projects"]:
        e.setdefault("bullets", [])
    for e in m["education"]:
        e.setdefault("courses", [])
    for t in m["tracks"]:
        if not TRACK_ID_RE.match(str(t.get("id", ""))):
            raise ValueError('track id %r: use lowercase letters, digits and dashes only (e.g. "project-engineer")'
                             % t.get("id"))
        t.setdefault("name", t["id"])
        if not isinstance(m["layout"].get(t["id"]), dict):
            m["layout"][t["id"]] = default_layout(m, t["id"])
        m["layout"][t["id"]].setdefault("sections", list(ALL_SECTIONS))
    return m


def candidate_name(m=None):
    """Your full name: config/profile.yml candidate.full_name (career-ops names tailored files
    output/cv-<your-name>-<company>-<date>.pdf from it), else the master's contact name."""
    try:
        with open(PROFILE_YML, encoding="utf-8") as f:
            for line in f:
                g = re.match(r"""^\s+full_name:\s*["']?(.*?)["']?\s*(#.*)?$""", line)
                if g and g.group(1).strip():
                    return g.group(1).strip()
    except OSError:
        pass
    return ((m or {}).get("contact") or {}).get("name", "")


def candidate_slug(m=None):
    """'Jane Q. Smith' -> 'jane-q-smith', the way career-ops names output/cv-<slug>-<company>-<date>.pdf."""
    return re.sub(r"[^a-z0-9]+", "-", candidate_name(m).lower()).strip("-")


def esc(s):
    """Plain text -> LaTeX. **bold** is allowed; everything else is escaped."""
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                 ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    s = s.replace("\u2013", "--").replace("\u2014", "---").replace("\u2019", "'").replace("\u2018", "`")
    s = s.replace("\u201c", "``").replace("\u201d", "''").replace("\u2192", r"$\rightarrow$")
    s = s.replace("\u2248", r"$\approx$").replace("\u20b9", "INR ")
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = s.replace("<->", r"$\leftrightarrow$").replace("->", r"$\rightarrow$")
    return s


def contact_block(m):
    c = m["contact"]
    parts = [c.get("location"), c.get("phone"), c.get("email"), c.get("linkedin")]
    return ("\\begin{center}\n{\\LARGE\\bfseries %s}\\\\[3pt]\n%s\n\\end{center}\n\n"
            % (esc(c.get("name") or "YOUR NAME")," \\quad | \\quad ".join(esc(p) for p in parts if p)))


def bullet_map(entries):
    return {e["id"]: (e, {b["id"]: b for b in e["bullets"]}) for e in entries}


def track_tex(m, tid):
    if tid not in m["layout"]:
        raise ValueError("unknown track %r (tracks: %s)" % (tid, ", ".join(t["id"] for t in m["tracks"]) or "none"))
    t = m["layout"][tid]
    fmt = t.get("format", {})
    out = [PREAMBLE % fmt_vals(fmt)]
    out.append(contact_block(m))
    exp = bullet_map(m["experience"])
    proj = bullet_map(m["projects"])
    edu = {e["id"]: e for e in m["education"]}
    aff = {a["id"]: a for a in m["affiliations"]}

    for sec in t["sections"]:
        if sec == "SUMMARY" and t.get("summary"):
            out.append("\\section{SUMMARY}\n%s\n\n" % esc(t["summary"]))
        elif sec in ("EXPERIENCE", "PROJECTS"):
            pool, picks = (exp, t["experience"]) if sec == "EXPERIENCE" else (proj, t.get("projects", []))
            # only entries with at least one printable ("ok") bullet: an empty list would break LaTeX
            picks = [p for p in picks if p["id"] in pool and any(
                pool[p["id"]][1].get(b, {}).get("status", "ok") == "ok" for b in p.get("bullets", []))]
            if not picks:
                continue
            out.append("\\section{%s}\n" % ("ACADEMIC PROJECTS" if sec == "PROJECTS" else sec))
            for i, p in enumerate(picks):
                e, bullets = pool[p["id"]]
                title = p.get("title") or e.get("title", "")
                if i:
                    out.append("\\vspace{\\jobgap}\n")
                if sec == "PROJECTS":  # one header line, no title line (saves space)
                    out.append("\\textbf{%s}, %s \\hfill %s\\par\n" % (esc(e["org"]), esc(e.get("location", "")),
                                                                     esc(e.get("dates", ""))))
                else:
                    out.append("\\job{%s}{%s}{%s}{%s}\n" % (esc(e["org"]), esc(e.get("location", "")),
                                                          esc(title), esc(e.get("dates", ""))))
                out.append("\\begin{itemize}\n")
                for bid in p["bullets"]:
                    b = bullets.get(bid)
                    if b and b.get("status", "ok") == "ok":
                        out.append("  \\item %s\n" % esc(b["text"]))
                out.append("\\end{itemize}\n\n")
        elif sec == "EDUCATION":
            out.append("\\section{EDUCATION}\n")
            for i, eid in enumerate([x for x in t.get("education", [e["id"] for e in m["education"]]) if x in edu]):
                e = edu[eid]
                if i:
                    out.append("\\vspace{2pt}\n")
                deg = e["degree"]
                if t.get("show_gpa") and e.get("gpa"):
                    deg += " | GPA: " + e["gpa"]
                out.append("\\textbf{%s}, %s \\hfill %s\\\\\n%s" % (esc(e["school"]), esc(e["location"]),
                                                                  esc(e["dates"]), esc(deg)))
                courses = t.get("courses", {}).get(eid, [])
                if courses:
                    out.append("\\\\\nRelevant Coursework: %s" % esc(", ".join(courses)))
                out.append("\\par\n")
            out.append("\n")
        elif sec == "SKILLS" and t.get("skills"):
            out.append("\\section{SKILLS}\n")
            out.append("\\\\\n".join("\\textbf{%s:} %s" % (esc(s["label"]), esc(s["text"])) for s in t["skills"]))
            out.append("\n\n")
        elif sec == "AFFILIATIONS" and any(a in aff and aff[a].get("short") for a in t.get("affiliations", [])):
            out.append("\\section{AFFILIATIONS}\n")
            out.append(" \\quad | \\quad ".join(esc(aff[a]["short"]) for a in t["affiliations"] if a in aff and aff[a].get("short")))
            out.append("\n\n")
    out.append("\\end{document}\n")
    return "".join(out)


def full_tex(m):
    """Every point in the library, grouped, with its id and tags - a multi-page reference copy."""
    out = [PREAMBLE % fmt_vals({"margin": 0.6}), contact_block(m)]
    out.append("\\begin{center}\\textit{MASTER RESUME - every point ever used. Not for sending: build a track "
               "resume from it.}\\end{center}\n")
    tracks = {t["id"]: t["name"] for t in m["tracks"]}

    def tagline(b):
        tags = [tracks.get(x, x) for x in b.get("tracks", [])]
        extra = []
        if b.get("status", "ok") != "ok":
            extra.append(b["status"].upper())
        if b.get("note"):
            extra.append(b["note"])
        s = " [" + ", ".join(tags) + "]" if tags else ""
        return s + (" -- " + "; ".join(extra) if extra else "")

    # LaTeX refuses an empty list, so each list below is only written when it has items
    sums = [(t["name"], m["layout"].get(t["id"], {}).get("summary")) for t in m["tracks"]]
    sums = [(n, s) for n, s in sums if s]
    if sums:
        out.append("\\section{SUMMARIES}\n\\begin{itemize}\n")
        for n, s in sums:
            out.append("  \\item \\textbf{%s:} %s\n" % (esc(n), esc(s)))
        out.append("\\end{itemize}\n")
    for sec, entries in (("EXPERIENCE", m["experience"]), ("ACADEMIC PROJECTS", m["projects"])):
        if not entries:
            continue
        out.append("\\section{%s}\n" % sec)
        for e in entries:
            out.append("\\job{%s}{%s}{%s}{%s}\n" % (esc(e.get("org", "")), esc(e.get("location", "")),
                                                  esc(e.get("title", "")), esc(e.get("dates", ""))))
            if e.get("note"):
                out.append("{\\small\\textit{%s}}\\par\n" % esc(e["note"]))
            if not e["bullets"]:
                out.append("\\vspace{3pt}\n")
                continue
            out.append("\\begin{itemize}\n")
            for b in e["bullets"]:
                txt = esc(b["text"])
                if b.get("status") == "never":
                    txt = "\\textit{(never use)} " + txt
                out.append("  \\item %s{\\small\\textit{%s}}\n" % (txt, esc(tagline(b))))
            out.append("\\end{itemize}\\vspace{3pt}\n")
    if m["education"]:
        out.append("\\section{EDUCATION}\n")
    for e in m["education"]:
        out.append("\\textbf{%s}, %s \\hfill %s\\\\\n%s%s\\\\\nAll coursework: %s\\par\\vspace{2pt}\n" % (
            esc(e.get("school", "")), esc(e.get("location", "")), esc(e.get("dates", "")), esc(e.get("degree", "")),
            (" | GPA: " + esc(e["gpa"])) if e.get("gpa") else "", esc(", ".join(e.get("courses", [])))))
    if m["skills"]:
        out.append("\\section{SKILLS (everything)}\n")
        out.append("\\\\\n".join("\\textbf{%s:} %s" % (esc(s["label"]), esc(s["text"])) for s in m["skills"]))
        out.append("\n")
    affs = [a for a in m["affiliations"] if a.get("text")]
    if affs:
        out.append("\\section{AFFILIATIONS AND OTHER}\n\\begin{itemize}\n")
        for a in affs:
            out.append("  \\item %s\n" % esc(a["text"]))
        out.append("\\end{itemize}\n")
    out.append("\\end{document}\n")
    return "".join(out)


def master_md(m):
    tracks = {t["id"]: t["name"] for t in m["tracks"]}
    L = ["<!-- GENERATED from master-resume.json by local/resume-builder/build_resume.py. Do not edit here;",
         "     use the Resume Editor (http://127.0.0.1:3002) or edit master-resume.json. -->",
         "", "# Master resume library - %s" % (m["contact"].get("name") or candidate_name(m) or "candidate"), "",
         "Every unique point from every resume the candidate has made, with a stable id and the tracks it fits.",
         "**How to tailor:** start from the track resume (`resume-<track>.tex`), then swap/reorder bullets using",
         "ONLY the texts below (light rewording is fine; never add tools, numbers, dates or titles).",
         "Status `confirm` = a fact the candidate has not confirmed yet: do not use it. "
         "Status `never` = must not appear.", ""]
    L.append("Tracks: " + ", ".join("`%s` (%s)" % (k, v) for k, v in tracks.items()))
    L.append("")
    L.append("## Summaries (per track)")
    for t in m["tracks"]:
        s = m["layout"].get(t["id"], {}).get("summary")
        if s:
            L.append("- **%s:** %s" % (t["name"], s))
    for sec, entries in (("Experience", m["experience"]), ("Projects", m["projects"])):
        L += ["", "## " + sec]
        for e in entries:
            L += ["", "### %s | %s | %s | %s  (id: `%s`)" % (e["org"], e.get("title", ""), e.get("location", ""),
                                                            e.get("dates", ""), e["id"])]
            for track_id, ttl in e.get("titles", {}).items():
                L.append("- *Title on the %s resume:* %s" % (tracks.get(track_id, track_id), ttl))
            if e.get("note"):
                L.append("- *Note:* " + e["note"])
            for b in e["bullets"]:
                st = b.get("status", "ok")
                flag = "" if st == "ok" else " **[%s]**" % st.upper()
                tags = ", ".join(b.get("tracks", []))
                note = (" - _%s_" % b["note"]) if b.get("note") else ""
                L.append("- `%s` [%s]%s %s%s" % (b["id"], tags, flag, b["text"], note))
    L += ["", "## Education"]
    for e in m["education"]:
        L.append("- **%s**, %s - %s - %s%s" % (e.get("school", ""), e.get("location", ""), e.get("degree", ""), e.get("dates", ""),
                                             (" - GPA " + e["gpa"]) if e.get("gpa") else ""))
        L.append("  - Courses: " + "; ".join(e.get("courses", [])))
    L += ["", "## Skills (full list; pick what the JD asks for)"]
    for s in m["skills"]:
        L.append("- **%s:** %s" % (s["label"], s["text"]))
    L += ["", "## Affiliations and other facts"]
    for a in m["affiliations"]:
        L.append("- " + a.get("text", ""))
    if m.get("never_claim"):
        L += ["", "## Never claim"]
        for n in m["never_claim"]:
            L.append("- " + n)
    return "\n".join(L) + "\n"


def count_pages(pdf, log=""):
    """Page count: pdflatex's own "Output written on x.pdf (N pages" line, else pypdf if installed,
    else page objects in an uncompressed PDF."""
    g = re.search(r"Output written on .*?\((\d+) pages?", log or "", re.S)
    if g:
        return int(g.group(1))
    try:
        from pypdf import PdfReader
        return len(PdfReader(pdf).pages)
    except ImportError:
        with open(pdf, "rb") as f:
            return len(re.findall(rb"/Type\s*/Page[^s]", f.read()))


def compile_tex(tex, name, outdir=ROOT):
    """Compile in a temp dir (keeps aux files out of the repo). Returns (pdf_path, pages, log_tail)."""
    tmp = tempfile.mkdtemp(prefix="resume-")
    src = os.path.join(tmp, name + ".tex")
    with open(src, "w", encoding="utf-8") as f:
        f.write(tex)
    r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", name + ".tex"],
                       cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace")
    pdf = os.path.join(tmp, name + ".pdf")
    if r.returncode != 0 or not os.path.exists(pdf):
        err = [l for l in r.stdout.splitlines() if l.startswith("!") or l.startswith("l.")]
        return None, 0, "\n".join(err[-6:]) or r.stdout[-800:]
    pages = count_pages(pdf, r.stdout)
    dest = os.path.join(outdir, name + ".pdf")
    try:
        shutil.copyfile(pdf, dest)
    except PermissionError:
        return None, pages, "%s is open in another program (close the PDF viewer and build again)" % dest
    shutil.rmtree(tmp, ignore_errors=True)
    return dest, pages, ""


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def copy_out(m, *paths):
    """Optional extra copy: settings.copy_outputs_to in master-resume.json. Off when unset or the folder is missing."""
    dest = ((m or {}).get("settings") or {}).get("copy_outputs_to")
    if not dest or not os.path.isdir(dest):
        return
    for p in paths:
        if p and os.path.exists(p):
            try:
                shutil.copyfile(p, os.path.join(dest, os.path.basename(p)))
            except OSError:
                pass


def build_track(m, tid):
    tex = track_tex(m, tid)
    name = "resume-" + tid
    write(os.path.join(ROOT, name + ".tex"), tex)
    pdf, pages, err = compile_tex(tex, name)
    copy_out(m, os.path.join(ROOT, name + ".tex"), pdf)
    return {"track": tid, "pdf": pdf, "pages": pages, "error": err}


def build_full(m):
    tex = full_tex(m)
    write(os.path.join(ROOT, "master-resume-full.tex"), tex)
    pdf, pages, err = compile_tex(tex, "master-resume-full")
    copy_out(m, pdf)
    return {"track": "full", "pdf": pdf, "pages": pages, "error": err}


def build_md(m):
    p = os.path.join(ROOT, "master-resume.md")
    write(p, master_md(m))
    copy_out(m, p)
    return p


def main(argv):
    if not os.path.exists(MASTER):
        print("No master-resume.json in %s. Copy templates/master-resume.json there and fill it in." % ROOT)
        return 1
    try:
        m = load()
    except (ValueError, KeyError) as e:  # bad JSON or a bad track id: say what is wrong
        print("master-resume.json has a problem: %s" % e)
        return 1
    build_md(m)
    if "--md" in argv:
        return 0
    if shutil.which("pdflatex") is None:
        print("pdflatex was not found. Install TinyTeX (or MiKTeX) and make sure pdflatex is on PATH.")
        return 1
    want = [a for a in argv if not a.startswith("-")] or [t["id"] for t in m["tracks"]] + ["full"]
    unknown = [t for t in want if t != "full" and t not in m["layout"]]
    if unknown:
        print("Unknown track(s): %s. Tracks in master-resume.json: %s"
              % (", ".join(unknown), ", ".join(t["id"] for t in m["tracks"]) or "none"))
        return 1
    bad = 0
    for tid in want:
        r = build_full(m) if tid == "full" else build_track(m, tid)
        status = r["error"] or ("%d pages (reference copy)" % r["pages"] if tid == "full" else "OK, 1 page" if r["pages"] == 1 else "WARNING: %d pages" % r["pages"])
        if r["error"] or (tid != "full" and r["pages"] != 1):
            bad = 1
        print("%-16s %s  %s" % (tid, status, r["pdf"] or ""))
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
