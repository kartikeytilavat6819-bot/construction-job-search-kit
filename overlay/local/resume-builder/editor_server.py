"""Resume Editor - a small local web page for editing master-resume.json and building the PDFs.

  python local/resume-builder/editor_server.py      -> http://127.0.0.1:3002 (this computer only)

Run the line above from the career-ops folder (or double-click a shortcut that does). Every save keeps the
previous master in local/resume-builder/backups/ (created when needed; last 40 kept), so nothing is ever lost.

Tailored resumes: http://127.0.0.1:3002/?report=105 (the "Edit" button on a career-ops report) or ?file=cv-...
opens that job's output/cv-*.tex; edits are written back there (old version kept, see tailored.py).
"""
import datetime, glob, json, os, shutil, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_resume as B  # noqa: E402
import tailored as T  # noqa: E402

PORT = 3002
BACKUPS = os.path.join(HERE, "backups")
LOCK = threading.Lock()  # one save/build at a time
_last_backup = [0.0]


def backup(min_gap=0):
    """Copy the current master to backups/. Autosave passes min_gap so edits don't flood the folder."""
    if time.time() - _last_backup[0] < min_gap:
        return
    _last_backup[0] = time.time()
    os.makedirs(BACKUPS, exist_ok=True)
    if os.path.exists(B.MASTER):
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        shutil.copyfile(B.MASTER, os.path.join(BACKUPS, "master-resume_%s.json" % stamp))
    old = sorted(glob.glob(os.path.join(BACKUPS, "master-resume_*.json")))
    for p in old[:-40]:
        os.remove(p)


def validate(m):
    if not isinstance(m, dict):
        raise ValueError("not a master resume")
    for k in ("contact", "tracks", "experience", "education"):
        if k not in m:
            raise ValueError("missing '%s'" % k)
    B.normalize(m)  # fills optional parts, gives a new track a layout, rejects bad track ids


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            with open(os.path.join(HERE, "editor.html"), encoding="utf-8") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/api/master":
            try:
                return self.send(200, B.load())
            except OSError:
                return self.send(404, {"error": "No master-resume.json in %s yet: copy the template there first." % B.ROOT})
            except ValueError as e:
                return self.send(400, {"error": "master-resume.json has a problem: %s" % e})
        if u.path == "/api/info":  # your name as career-ops writes it in output/cv-<slug>-<company>-<date>
            return self.send(200, {"slug": B.candidate_slug(B.load())})
        if u.path == "/api/doc":  # a tailored resume: ?report=105 (from the career-ops website) or ?file=cv-...
            report = q.get("report", [""])[0]
            name, rep = (T.for_report(report) if report else (T.safe_name(q.get("file", [""])[0]), None))
            if not name:
                return self.send(404, {"error": "No editable tailored resume (.tex) found for report %s." % report
                                       if report else "That tailored resume was not found in output/."})
            with open(os.path.join(T.OUTPUT, name + ".tex"), encoding="utf-8") as f:
                tex = f.read()
            try:
                doc = T.parse(tex)
            except ValueError as e:
                return self.send(422, {"error": "This resume is in an older layout the editor can't read (%s)." % e})
            return self.send(200, {"file": name, "report": rep, "doc": doc})
        if u.path == "/api/docs":  # newest tailored resumes, for the "Open tailored" picker
            files = sorted(glob.glob(os.path.join(T.OUTPUT, "cv-*.tex")), key=os.path.getmtime, reverse=True)
            return self.send(200, [os.path.basename(p)[:-4] for p in files[:150]])
        if u.path == "/pdf" and q.get("file"):
            name = T.safe_name(q["file"][0])
            p = name and os.path.join(T.OUTPUT, name + ".pdf")
            if not p or not os.path.exists(p):
                return self.send(404, {"error": "not built yet"})
            with open(p, "rb") as f:
                return self.send(200, f.read(), "application/pdf")
        if u.path == "/pdf":
            tid = q.get("track", [""])[0]
            name = "master-resume-full" if tid == "full" else "resume-" + tid
            p = os.path.join(B.ROOT, name + ".pdf")
            if not tid.replace("-", "").isalnum() or not os.path.exists(p):
                return self.send(404, {"error": "not built yet"})
            with open(p, "rb") as f:
                return self.send(200, f.read(), "application/pdf")
        if u.path == "/api/tex":
            m = B.load()
            tid = q.get("track", [""])[0]
            return self.send(200, B.full_tex(m) if tid == "full" else B.track_tex(m, tid), "text/plain; charset=utf-8")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # Only accept requests from the editor page itself (blocks other websites posting here).
        origin = self.headers.get("Origin", "")
        if origin and origin not in ("http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT):
            return self.send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0) or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/save":
                validate(data)
                backup()
                B.write(B.MASTER, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                B.build_md(data)
                return self.send(200, {"ok": True})
            if u.path == "/api/save-build":  # autosave from the editor: save, then rebuild the previewed resume
                m, tid = data.get("master"), data.get("track")
                validate(m)
                with LOCK:
                    backup(min_gap=600)
                    B.write(B.MASTER, json.dumps(m, ensure_ascii=False, indent=2) + "\n")
                    B.build_md(m)
                    r = B.build_full(m) if tid == "full" else B.build_track(m, tid)
                return self.send(200, r)
            if u.path == "/api/doc-save":  # save an edited tailored resume back to output/ and rebuild its PDF
                name = T.safe_name(data.get("file"))
                if not name or not isinstance(data.get("doc"), dict):
                    raise ValueError("unknown tailored resume")
                with LOCK:
                    return self.send(200, T.save(name, data["doc"]))
            if u.path == "/api/build":
                m = B.load()
                tid = data.get("track")
                r = B.build_full(m) if tid == "full" else B.build_track(m, tid)
                B.build_md(m)
                return self.send(200, r)
        except Exception as e:  # report to the page instead of crashing the server
            return self.send(400, {"error": str(e)})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        print("Resume Editor is already running: http://127.0.0.1:%d" % PORT)
        sys.exit(0)
    print("Resume Editor: http://127.0.0.1:%d  (Ctrl+C to stop)" % PORT)
    srv.serve_forever()
