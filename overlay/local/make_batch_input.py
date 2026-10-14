"""Pick the top-ranked pending jobs (after local/rank_pipeline.py) into batch/batch-input.tsv
for batch/batch-runner.sh: at most --per-company per employer, skipping URLs already evaluated.

  python local/make_batch_input.py [--count 11] [--per-company 2]
"""
import argparse, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.md")
STATE = os.path.join(ROOT, "batch", "batch-state.tsv")
OUT = os.path.join(ROOT, "batch", "batch-input.tsv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=11)
    ap.add_argument("--per-company", type=int, default=2)
    a = ap.parse_args()
    done = set()
    if os.path.exists(STATE):  # anything the runner already processed or is processing
        for line in open(STATE, encoding="utf-8").read().splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) > 1:
                done.add(cols[1].strip())
    pending = [l for l in open(PIPE, encoding="utf-8").read().splitlines() if l.startswith("- [ ]")]
    picked, per = [], {}
    for l in pending:  # pipeline.md Pending is already in rank order
        parts = [p.strip() for p in l[6:].split("|")]
        url, company = parts[0], (parts[1] if len(parts) > 1 else "")
        key = re.sub(r"[^a-z]", "", company.lower())[:12]
        if url in done or per.get(key, 0) >= a.per_company:
            continue
        per[key] = per.get(key, 0) + 1
        title = parts[2] if len(parts) > 2 else ""
        picked.append((url, company, title))
        if len(picked) >= a.count:
            break
    start = 1
    if os.path.exists(OUT):
        ids = [int(c.split("\t")[0]) for c in open(OUT, encoding="utf-8").read().splitlines()[1:] if c.split("\t")[0].isdigit()]
        start = max(ids, default=0) + 1
    rows = ["id\turl\tsource\tnotes"] if not os.path.exists(OUT) else open(OUT, encoding="utf-8").read().rstrip("\n").split("\n")
    for i, (url, company, title) in enumerate(picked, start):
        if ".icims.com/jobs/" in url and "in_iframe=1" not in url:
            # iCIMS renders the JD inside an iframe; the in_iframe=1 page is the same posting as static HTML,
            # which the batch runner's curl prefetch (and the CLI extractor) can actually read.
            url += ("&" if "?" in url else "?") + "in_iframe=1"
        rows.append(f"{i}\t{url}\tcareer-ops scan\t{company} - {title} (pre-ranked: home area/entry-level/H-1B)")
    open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
    print(f"added {len(picked)} jobs to {os.path.relpath(OUT, ROOT)} (ids {start}-{start + len(picked) - 1})")
    for url, company, title in picked:
        print(f"  {company} | {title}")


if __name__ == "__main__":
    main()
