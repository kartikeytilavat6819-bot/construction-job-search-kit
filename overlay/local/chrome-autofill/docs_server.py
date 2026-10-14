"""Read-only helper for the career-ops Autofill Chrome extension. Serves http://127.0.0.1:3001 (this computer only).

  GET /jobs                       tracker rows + the exact tailored resume/cover PDF each report names
  GET /file?n=15&kind=resume      that PDF (kind = resume | cover)
  GET /answers?n=15               the report's drafted answers ("H) Draft Application Answers") + cover letter text
  GET /profile                    profile.json (your form answers), read fresh on every request
  GET /version                    fingerprint of manifest.json + background.js; the popup offers "Update ready" when it changes
  python docs_server.py --sync-index   add those PDFs to data/pdf-index.tsv (then exit)

The PDF for an application comes from its report's header lines, e.g.
  **PDF:** output/cv-jane-smith-acme-builders-2026-10-06.pdf
  **Cover letter:** output/cover-jane-smith-acme-builders-2026-10-06.pdf
(a .tex path there means the .pdf next to it). With no Cover letter line, cv-X.pdf pairs with
cover-X.pdf. Started at logon by local/start-website.ps1 (if set up), or by "Start autofill helper.cmd".

All paths come from this file's location: the career-ops folder is two levels up (career-ops/local/chrome-autofill/).

LaTeX builds never reach data/pdf-index.tsv (only generate-pdf.mjs writes it), so the career-ops
website's "Apply" button and "View tailored CV" link found no resume for most jobs. The server
adds the missing rows every 2 minutes (or once, with --sync-index); rows already there are kept.
"""
import base64, hashlib, json, os, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))  # the extension folder
ROOT = os.path.dirname(os.path.dirname(HERE))  # career-ops/
OUTPUT = os.path.join(ROOT, "output")
PORT = 3001


def extension_origin():
    """chrome-extension://<id> of this extension. Chrome derives the id from manifest.json's "key"
    (sha256 of the key, first 32 hex digits written with the letters a-p), so it is the same on every
    computer. Without a key the id depends on the folder, so any extension origin is accepted then."""
    try:
        with open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as f:
            key = json.load(f).get("key")
        digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
        return "chrome-extension://" + "".join(chr(ord("a") + int(c, 16)) for c in digest)
    except (OSError, ValueError, TypeError):
        return None


EXTENSION_ORIGIN = extension_origin()


def report_doc(report_path, label_re):
    """The PDF a report header line points at, or None."""
    try:
        text = open(report_path, encoding="utf-8").read()
    except OSError:
        return None
    for line in text.splitlines()[:40]:
        if not re.match(label_re, line):
            continue
        m = re.search(r"output/([A-Za-z0-9_.-]+?)\.(pdf|tex)\b", line)
        if not m:
            return None
        pdf = os.path.join(OUTPUT, m.group(1) + ".pdf")
        return pdf if os.path.isfile(pdf) else None
    return None


def extension_version():
    """Fingerprint of the two files Chrome only rereads on a reload. content.js and the popup are read
    from disk every time they load, so they never need one."""
    parts = []
    for name in ("manifest.json", "background.js"):
        st = os.stat(os.path.join(HERE, name))
        parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


NOTE_RE = re.compile(r"\s*\((adjust|confirm|edit|replace|only|if |add |check|verify|update)[^)]*\)\s*$", re.I)


def report_section(text, title_re):
    m = re.search(r"^## " + title_re + r".*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    end = re.search(r"^(## |---\s*$)", rest, re.M)
    return rest[: end.start()] if end else rest


def drafted_answers(report_path):
    """'- **Why Acme?** answer' lines from the report's "H) Draft Application Answers" section.
    A trailing note to you like "(adjust to the actual referral)" is dropped and flagged."""
    try:
        text = open(report_path, encoding="utf-8").read()
    except (OSError, TypeError):
        return []
    out = []
    for line in report_section(text, r"H\)").splitlines():
        m = re.match(r"\s*(?:[-*]|\d+\.)\s+\*\*(.+?)\*\*:?\s*(.+)", line)
        if not m:
            continue
        q, a = m.group(1).strip().rstrip(":"), m.group(2).strip()
        note = bool(NOTE_RE.search(a))
        a = NOTE_RE.sub("", a).strip()
        if len(a) > 1 and a[0] in "\"“" and a[-1] in "\"”":
            a = a[1:-1].strip()
        if a:
            out.append({"q": q, "a": a, "check": note})
    return out


def salary_max(report_path):
    """Top of the pay range the posting advertises (the report's advertised_comp line), or None.
    Notes in parentheses ("Master's 2027 grad: $83,928") are ignored: you asked for the range's max."""
    try:
        text = open(report_path, encoding="utf-8").read()
    except (OSError, TypeError):
        return None
    m = re.search(r'^advertised_comp:\s*"?(.*?)"?\s*$', text, re.M)
    if not m or m.group(1).lower() in ("", "null", "none"):
        return None
    comp = re.sub(r"\([^)]*\)", " ", m.group(1))
    amounts = []
    for num, k in re.findall(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*([kK])?\b", comp):
        v = float(num.replace(",", "")) * (1000 if k else 1)
        if v >= 10:  # skip stray small numbers
            amounts.append(v)
    if not amounts:
        return None
    top = max(amounts)
    return {"amount": int(round(top)), "period": "hour" if top < 500 else "year"}


MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_date(s):
    """'July 2026' -> {'month': 7, 'year': 2026}; 'Present' -> None."""
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s or "")
    if m and m.group(1).lower() in MONTHS:
        return {"month": MONTHS[m.group(1).lower()], "year": int(m.group(2))}
    m = re.search(r"\b(\d{4})\b", s or "")
    return {"month": None, "year": int(m.group(1))} if m else None


def resume_history():
    """Work history and education from career-ops cv.md (your source of truth), newest first."""
    try:
        text = open(os.path.join(ROOT, "cv.md"), encoding="utf-8").read()
    except OSError:
        return {"work_history": [], "education": []}
    work, edu = [], []
    for title, rows in (("Experience", work), ("Education", edu)):
        body = report_section(text, re.escape(title) + r"\s*$")
        for block in re.split(r"^### ", body, flags=re.M)[1:]:
            lines = [l.strip() for l in block.strip().splitlines()]
            head, meta = lines[0], (lines[1] if len(lines) > 1 else "")
            where, _, when = meta.partition(" · ")
            if title == "Experience":
                org, _, role = head.partition(" · ")
                start, _, end = when.partition("–")
                bullets = [l[2:] for l in lines[2:] if l.startswith("- ")]
                rows.append({"company": org.replace(" — ", " - ").strip(), "title": role.strip(), "location": where.strip(),
                             "start": parse_date(start), "end": parse_date(end), "current": "present" in end.lower(),
                             "description": "\n".join("- " + b for b in bullets)})
            else:
                school, _, degree = head.partition(" — ")
                m = re.match(r"(M\.S\.|B\.E\.|B\.S\.|M\.Eng\.|Ph\.D\.|[A-Z][\w.]*)\s+(.*)", degree.strip())
                level = {"M.S.": "Master of Science", "B.E.": "Bachelor of Engineering", "B.S.": "Bachelor of Science"}.get(m.group(1), m.group(1)) if m else degree
                rows.append({"school": school.strip(), "degree": level, "discipline": (m.group(2) if m else "").strip(),
                             "location": where.strip(), "end": parse_date(when), "expected": "expected" in when.lower()})
    summary = " ".join(l.strip() for l in report_section(text, r"Summary\s*$").splitlines() if l.strip())
    return {"work_history": work, "education": edu, "summary": summary or None}


def cover_letter_text(cover_pdf):
    """Plain text of the tailored cover letter (from its .tex), for forms with a cover-letter text box."""
    if not cover_pdf:
        return None
    try:
        tex = open(cover_pdf[:-4] + ".tex", encoding="utf-8").read()
    except OSError:
        return None
    start = re.search(r"^Dear .*$", tex, re.M)
    end = tex.find("\\end{document}")
    if not start or end < 0:
        return None
    body = tex[start.start():end]
    body = re.sub(r"\\begin\{itemize\}|\\end\{itemize\}", "", body)
    body = re.sub(r"\\item\s*", "- ", body)
    body = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\(textbf|textit|emph|underline)\{([^}]*)\}", r"\2", body)
    body = body.replace("\\\\", "\n").replace("~", " ").replace("--", "–").replace("\\&", "&").replace("\\%", "%").replace("\\$", "$")
    body = re.sub(r"\\[a-zA-Z]+(\[[^\]]*\])?(\{[^}]*\})?", "", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n[ \t]+", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


ID_QUERY_KEYS = re.compile(r"job|req|opportun|posting|vacanc|^id$", re.I)


def job_ids(url, notes):
    """Tokens that identify this posting on any page of its application: the ATS job number from the
    link (Workday R-31631, iCIMS /jobs/6323/, Taleo job=196244, Cornerstone requisition/20955, Lever and
    Pinpoint UUIDs...) and req / job-id numbers from the tracker notes. The extension looks for them in
    the address and text of whatever page you are on."""
    ids = set()
    u = urlparse(url or "")
    path = u.path
    ids.update(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path.lower()))
    ids.update(m.lower() for m in re.findall(r"(?<![A-Za-z0-9])J?R-?\d{5,}(?:-\d+)?", path))
    ids.update(m.lower() for m in re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16,}(?![0-9A-Fa-f])", path) if not re.fullmatch(r"\d+", m))
    nums = re.findall(r"(?<!\d)\d{4,}(?!\d)", re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", " ", path.lower()))
    for k, vals in parse_qs(u.query).items():
        if ID_QUERY_KEYS.search(k) and not re.fullmatch(r"c|cid|ccid|lang|source", k, re.I):
            nums += [v for v in vals if re.fullmatch(r"[A-Za-z0-9-]{4,}", v)]
    for n in re.findall(r"(?i)\b(?:req(?:uisition)?|job ?(?:id|#|no\.?))\b\.?\s*[:#]?\s*([A-Za-z0-9-]*\d[A-Za-z0-9-]*)", notes or ""):
        nums.append(n)
        if re.fullmatch(r"20\d\d-\d{3,}", n):
            nums.append(n.split("-", 1)[1])  # "2026-6323" -> iCIMS shows 6323
    nums += re.findall(r"(?<![A-Za-z0-9])J?R-?\d{5,}(?:-\d+)?", notes or "")
    for n in nums:
        n = n.lower()
        if len(n) >= 4 and re.search(r"\d", n) and not re.fullmatch(r"(19|20)\d\d", n):
            ids.add(n)
    return sorted(ids)


def jobs():
    out = []
    try:
        lines = open(os.path.join(ROOT, "data", "applications.md"), encoding="utf-8").read().splitlines()
    except OSError:
        return out
    header = None
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if set(line) <= set("|-: "):
            continue
        row = dict(zip(header, cells))
        if not row.get("#", "").isdigit():
            continue
        m = re.search(r"\[(\d+)\]\(\.\./(reports/[^)]+)\)", row.get("report", ""))
        report = os.path.join(ROOT, m.group(2)) if m else None
        resume = report_doc(report, r"\*\*PDF:?\*\*") if report else None
        cover = report_doc(report, r"\*\*Cover letter[^*]*\*\*") if report else None
        if resume and not cover:  # reports without a Cover letter line: cv-X.pdf pairs with cover-X.pdf
            twin = os.path.join(OUTPUT, "cover-" + os.path.basename(resume)[3:])
            cover = twin if os.path.basename(resume).startswith("cv-") and os.path.isfile(twin) else None
        out.append({
            "n": row["#"], "company": row.get("company", ""), "role": row.get("role", ""),
            "status": row.get("status", ""), "url": row.get("url", ""),
            "resume": os.path.basename(resume) if resume else None,
            "cover": os.path.basename(cover) if cover else None,
            "drafts": len(drafted_answers(report)) if report else 0,
            "ids": job_ids(row.get("url", ""), row.get("notes", "")),
            "_paths": {"resume": resume, "cover": cover, "report": report},
            "_report": m.group(1) if m else None,
        })
    # an id found on two different postings is a company/portal code (UltiPro board, Paycom portal), not a job's
    owners = {}
    for j in out:
        for i in j["ids"]:
            owners.setdefault(i, set()).add(j["url"].split("?")[0].rstrip("/").lower())
    for j in out:
        j["ids"] = [i for i in j["ids"] if len(owners[i]) == 1]
    return out


def sync_pdf_index():
    """Add a cv/cover row to data/pdf-index.tsv for every report that has none. Returns rows added."""
    index = os.path.join(ROOT, "data", "pdf-index.tsv")
    header = "# report\tpdf\thtml\tformat\tdate\tkind - written by generate-pdf.mjs, do not edit"
    try:
        lines = [l for l in open(index, encoding="utf-8").read().splitlines() if l.strip()]
    except OSError:
        lines = []
    rows = [l for l in lines if not l.startswith("#")]
    have = set()
    for l in rows:
        c = l.split("\t")
        if c[0].strip().isdigit():
            have.add((int(c[0]), "cover" if len(c) > 5 and c[5].strip() == "cover" else "cv"))
    added = []
    for j in jobs():
        if not j["_report"]:
            continue
        for kind, path in (("cv", j["_paths"]["resume"]), ("cover", j["_paths"]["cover"])):
            if path and (int(j["_report"]), kind) not in have:
                have.add((int(j["_report"]), kind))
                date = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
                added.append("\t".join([j["_report"], "output/" + os.path.basename(path), "", "letter", date, kind]))
    if added:
        with open(index + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join([header] + rows + added) + "\n")
        os.replace(index + ".tmp", index)
    return len(added)


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        origin = self.headers.get("Origin")
        allowed = origin == EXTENSION_ORIGIN if EXTENSION_ORIGIN else (origin or "").startswith("chrome-extension://")
        if origin and not allowed:  # web pages may not read your files
            return self.send(403, b'{"error":"forbidden origin"}')
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/jobs":
            rows = [{k: v for k, v in j.items() if not k.startswith("_")} for j in jobs()]
            return self.send(200, json.dumps(rows, ensure_ascii=False).encode("utf-8"))
        if url.path == "/file":
            job = next((j for j in jobs() if j["n"] == q.get("n")), None)
            path = job and job["_paths"].get(q.get("kind"))
            if not path:
                return self.send(404, b'{"error":"no tailored PDF for this application"}')
            with open(path, "rb") as f:
                return self.send(200, f.read(), "application/pdf")
        if url.path == "/answers":
            job = next((j for j in jobs() if j["n"] == q.get("n")), None)
            if not job:
                return self.send(404, b'{"error":"no such application"}')
            co = re.sub(r"\W+", " ", job["company"].lower()).strip()
            applied = any(j["n"] != job["n"] and re.sub(r"\W+", " ", j["company"].lower()).strip() == co
                          and re.search(r"applied|interview|offer|rejected|responded|ghost|withdrawn", j["status"], re.I) for j in jobs())
            body = {"answers": drafted_answers(job["_paths"]["report"]), "cover_text": cover_letter_text(job["_paths"]["cover"]),
                    "salary_max": salary_max(job["_paths"]["report"]), "applied_before": "Yes" if applied else "No"}
            return self.send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"))
        if url.path == "/profile":  # read fresh each time, so edits apply without reloading the extension
            try:
                with open(os.path.join(HERE, "profile.json"), encoding="utf-8") as f:
                    profile = json.load(f)
            except (OSError, ValueError):  # not created yet, or a typo in it: fill only what cv.md gives
                profile = {}
            profile = {k: v for k, v in profile.items() if not k.startswith("_")}  # drop the _help notes
            profile.update(resume_history())  # work history + education from cv.md
            return self.send(200, json.dumps(profile, ensure_ascii=False).encode("utf-8"))
        if url.path == "/version":
            return self.send(200, json.dumps({"version": extension_version()}).encode())
        return self.send(404, b'{"error":"not found"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if "--sync-index" in sys.argv:
        print(f"pdf-index: added {sync_pdf_index()} row(s)")
        sys.exit(0)
    for attempt in range(8):  # a copy restarting after an edit may need a moment for the port to free up
        try:
            server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError:
            time.sleep(0.5)
    else:
        sys.exit(0)  # another copy is running
    def keep_index_synced():  # new evaluations (scan or by hand) show up within 2 minutes
        while True:
            try:
                sync_pdf_index()
            except OSError:
                pass  # e.g. the tracker is mid-write; try again next round
            time.sleep(120)

    me = os.path.abspath(__file__)
    started = os.path.getmtime(me)

    def watch_for_edits():  # a changed docs_server.py takes over without anyone restarting it
        while True:
            time.sleep(10)
            try:
                if os.path.getmtime(me) != started:
                    server.shutdown()  # serve_forever() below returns; the main thread relaunches
                    return
            except OSError:
                pass

    threading.Thread(target=keep_index_synced, daemon=True).start()
    threading.Thread(target=watch_for_edits, daemon=True).start()
    server.serve_forever()
    server.server_close()  # free the port before the new copy binds it
    subprocess.Popen([sys.executable, me], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
