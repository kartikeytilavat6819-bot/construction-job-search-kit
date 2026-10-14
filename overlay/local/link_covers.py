"""Make every tracker row's tailored cover letter reachable by the web app and the Chrome autofill helper.

The web app (/api/cover-pdf?application=N, web/src/lib/apply/cover.ts) only accepts a cover PDF whose
filename carries the token "cover", the row's full company slug and its role slug. Evaluation covers are often
named by short slugs (cover-<name>-<short-company>-...), so nothing resolved. For each Evaluated/Applied row:
  1. find its cover: the report's **Cover letter:** line, else the CV name from **PDF:** with cv- -> cover-;
  2. compile the .tex if the PDF is missing or older (node generate-latex.mjs <tex> --compile-only);
  3. write a COPY named cover-<candidate-slug>-<company-slug>-<role-slug>.pdf (originals untouched; the candidate
     slug comes from candidate.full_name in config/profile.yml);
  4. add a **Cover letter:** header line to the report when it has none (docs_server.py reads it).
Idempotent; safe to re-run after new evaluations.   python local/link_covers.py
"""
import os, re, shutil, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")


def slug(s):
    return "-".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def candidate_slug():
    try:
        txt = open(os.path.join(ROOT, "config", "profile.yml"), encoding="utf-8").read()
    except OSError:
        return "candidate"
    m = re.search(r"^\s*full_name:\s*[\"']?([^\"'#\n]+)", txt, re.M)
    return slug(m.group(1)) if m and slug(m.group(1)) else "candidate"


def rows():
    p = os.path.join(ROOT, "data", "applications.md")
    if not os.path.exists(p):
        return
    for l in open(p, encoding="utf-8"):
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(c) >= 9 and c[0].isdigit():
            yield c


def compile_tex(tex):
    env = dict(os.environ)
    env["PATH"] = os.environ.get("PATH", "")
    p = subprocess.run(["node", "generate-latex.mjs", tex, "--compile-only"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=180, shell=os.name == "nt")
    return p.returncode == 0


def main():
    linked, compiled, added_line, missing = 0, 0, 0, []
    who = candidate_slug()
    for c in rows():
        n, company, role, status, rep = c[0], c[2], c[3], c[5].lower(), c[7]
        if status not in ("evaluated", "applied", "interview", "responded"):
            continue
        m = re.search(r"\((?:\.\./)?(reports/[^)]+)\)", rep)
        if not m:
            continue
        rpath = os.path.join(ROOT, m.group(1))
        txt = open(rpath, encoding="utf-8").read()
        cov = re.search(r"^\*\*Cover letter:\*\*\s*`?([^\s`]+)", txt, re.M)
        cvm = re.search(r"^\*\*PDF:\*\*\s*`?([^\s`]+)", txt, re.M)
        name = None
        if cov:
            name = os.path.basename(cov.group(1))
        elif cvm:
            name = os.path.basename(cvm.group(1)).replace("cv-", "cover-", 1)
        if not name:
            missing.append((n, company, "no PDF/Cover line in report"))
            continue
        pdf = os.path.join(OUT, re.sub(r"\.tex$", ".pdf", name))
        tex = re.sub(r"\.pdf$", ".tex", pdf)
        if os.path.exists(tex) and (not os.path.exists(pdf) or os.path.getmtime(pdf) < os.path.getmtime(tex)):
            if compile_tex(tex):
                compiled += 1
        if not os.path.exists(pdf):
            missing.append((n, company, f"no cover file {os.path.basename(pdf)}"))
            continue
        alias = os.path.join(OUT, f"cover-{who}-{slug(company)}-{slug(role)}.pdf")
        if os.path.abspath(alias) != os.path.abspath(pdf) and (
                not os.path.exists(alias) or os.path.getmtime(alias) < os.path.getmtime(pdf)):
            shutil.copy2(pdf, alias)
        linked += 1
        if not cov and cvm:
            keep = os.path.join(OUT, "old-versions", "before-cover-links", "reports")
            os.makedirs(keep, exist_ok=True)
            if not os.path.exists(os.path.join(keep, os.path.basename(rpath))):
                shutil.copy2(rpath, keep)  # always keep the old version
            line = f"**Cover letter:** output/{os.path.basename(pdf)}"
            txt = txt.replace(cvm.group(0), cvm.group(0) + "\n" + line, 1)
            open(rpath, "w", encoding="utf-8", newline="\n").write(txt)
            added_line += 1
    print(f"linked {linked} covers for the web app; compiled {compiled}; added the Cover letter line to {added_line} reports")
    for x in missing:
        print("  missing:", x)
    sync_pdf_index()


def sync_pdf_index():
    """/api/cv-pdf finds a row's CV through data/pdf-index.tsv. When CVs are rebuilt (e.g. the v2 format) the index
    still names the moved files, so the web app 404s. Point each report's cv/cover rows at the files its
    **PDF:** / **Cover letter:** header lines name (when those files exist)."""
    idx = os.path.join(ROOT, "data", "pdf-index.tsv")
    if not os.path.exists(idx):
        return
    lines = open(idx, encoding="utf-8").read().splitlines()
    header = [l for l in lines if l.startswith("#")]
    rows = [l.split("\t") for l in lines if l and not l.startswith("#")]
    want = {}
    for f in (os.listdir(os.path.join(ROOT, "reports")) if os.path.isdir(os.path.join(ROOT, "reports")) else []):
        m = re.match(r"^(\d{3})-.*\.md$", f)
        if not m:
            continue
        head = open(os.path.join(ROOT, "reports", f), encoding="utf-8", errors="replace").read(8000)
        for kind, pat in (("cv", r"^\*\*PDF:\*\*\s*`?([^\s`]+\.pdf)"), ("cover", r"^\*\*Cover letter:\*\*\s*`?([^\s`]+\.pdf)")):
            mm = re.search(pat, head, re.M)
            if mm:
                p = mm.group(1).replace("\\", "/")
                p = p if p.startswith("output/") else "output/" + os.path.basename(p)
                if os.path.exists(os.path.join(ROOT, p)):
                    want[(m.group(1), kind)] = p
    if not want:
        return
    shutil.copy2(idx, idx + ".bak")
    kept = [r for r in rows if not (len(r) >= 6 and (r[0], r[5]) in want)]
    import datetime
    today = datetime.date.today().isoformat()
    added = [[rep, p, "", "letter", today, kind] for (rep, kind), p in sorted(want.items())]
    with open(idx, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(header + ["\t".join(r) for r in kept + added]) + "\n")
    print(f"pdf-index synced: {len(added)} cv/cover entries point at the files named in report headers (backup pdf-index.tsv.bak)")


if __name__ == "__main__":
    main()
