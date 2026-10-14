"""Build triage queues from pending jobs that have not been triaged or evaluated yet (no AI calls).

  python local/untriaged_queue.py --region home [--batch 25] [--prefix ne]   # home metro + home state + region
  python local/untriaged_queue.py --region us   [--batch 25] [--prefix us]   # everything else in the US
(home metro / state / region come from config/targeting.yml; "--region ne" is accepted as an alias of "home")
  python local/untriaged_queue.py --region all  --out data/triage/untriaged-all.tsv --batch 0

Reads data/pipeline-ranked.md (rank order), data/triage/*result-*.tsv, data/applications.md and
the JDs saved in jds/screen-*.md (matched by their "Source URL:" line). Writes data/triage/<prefix>-queue-NN.tsv
(url, company, title, where, jd_file) and prints counts.
"""
import argparse, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import targeting as T  # noqa: E402

D = os.path.join(ROOT, "data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=["home", "ne", "us", "all"], default="home")
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    done = set()
    for f in glob.glob(os.path.join(D, "triage", "result-*.tsv")) + glob.glob(os.path.join(D, "triage", "*-result-*.tsv")):
        for l in open(f, encoding="utf-8").read().splitlines()[1:]:
            if l.strip():
                done.add(l.split("\t")[0].strip())
    ap_path = os.path.join(D, "applications.md")
    apps = open(ap_path, encoding="utf-8").read() if os.path.exists(ap_path) else ""
    jd = {}
    # every JD local/sponsor_screen.py ever saved (sponsor-screen.json only holds its latest run)
    for f in glob.glob(os.path.join(ROOT, "jds", "screen-*.md")):
        m = re.search(r"Source URL: (\S+)", open(f, encoding="utf-8", errors="replace").read(600))
        if m:
            jd[m.group(1)] = os.path.relpath(f, ROOT)

    rows = []
    if not os.path.exists(os.path.join(D, "pipeline-ranked.md")):
        raise SystemExit("data/pipeline-ranked.md not found: run python local/rank_pipeline.py first")
    for l in open(os.path.join(D, "pipeline-ranked.md"), encoding="utf-8").read().splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*[\d.]+\s*\|\s*([^|]+?)\s*\|\s*[^|]*\|\s*([^|]+?)\s*\|\s*\[(.+)\]\((\S+)\)\s*\|", l)
        if not m:
            continue
        where, company, title, url = m.groups()
        if url in done or url in apps:
            continue
        home = where in T.HOME_LABELS
        if (a.region in ("home", "ne") and not home) or (a.region == "us" and home):
            continue
        rows.append((url, company, title, where, jd.get(url, "")))

    print(f"{len(rows)} untriaged {a.region} jobs ({sum(1 for r in rows if r[4])} with a saved JD)")
    wheres = {}
    for r in rows:
        wheres[r[3]] = wheres.get(r[3], 0) + 1
    print("by location tier:", wheres)
    os.makedirs(os.path.join(D, "triage"), exist_ok=True)
    hdr ="url\tcompany\ttitle\twhere\tjd_file\n"
    if a.out or a.batch == 0:
        out = a.out or os.path.join(D, "triage", f"untriaged-{a.region}.tsv")
        open(out, "w", encoding="utf-8", newline="\n").write(hdr + "".join("\t".join(r) + "\n" for r in rows))
        print("wrote", out)
        return
    prefix = a.prefix or a.region
    for i in range(0, len(rows), a.batch):
        n = i // a.batch + 1
        out = os.path.join(D, "triage", f"{prefix}-queue-{n:02d}.tsv")
        open(out, "w", encoding="utf-8", newline="\n").write(hdr + "".join("\t".join(r) + "\n" for r in rows[i:i + a.batch]))
    print(f"wrote {(len(rows) + a.batch - 1) // a.batch} queue files: data/triage/{prefix}-queue-NN.tsv")


if __name__ == "__main__":
    main()
