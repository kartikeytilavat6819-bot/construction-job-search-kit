"""Zero-token pre-filter: apply the rule-based hard DQs (local/ollama_triage.py rule_dq, driven by
config/targeting.yml: title rules, too many years, PE required, sponsorship refusal) to a triage queue. No AI.

  python local/rule_prefilter.py --queue data/triage/untriaged-us.tsv [--fetch] [--batch 25 --prefix us]

Writes data/triage/rule-result-<prefix>.tsv (FAIL rows, same columns as the Claude triage results so
untriaged_queue.py treats them as done) and splits the survivors into data/triage/<prefix>-queue-NN.tsv
for Claude triage. --fetch downloads JDs that aren't saved yet (headless reader, no AI).
"""
import argparse, csv, os, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ollama_triage as o  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--prefix", default="us")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.queue, encoding="utf-8"), delimiter="\t"))
    idx = o.jd_index()

    def one(r):
        jd = o.load_jd(r, idx, a.fetch)
        if not jd.strip():
            return r, "", None
        rel = os.path.relpath(idx.get(r["url"], ""), o.ROOT) if r["url"] in idx else r.get("jd_file", "")
        return r, rel, o.rule_dq(r, jd)

    with ThreadPoolExecutor(a.workers if a.fetch else 1) as ex:
        res = list(ex.map(one, rows))
    fails = [(r, dq) for r, _, dq in res if dq]
    keep = [(r, jd) for r, jd, dq in res if not dq]
    os.makedirs(o.TRI, exist_ok=True)
    out = os.path.join(o.TRI, f"rule-result-{a.prefix}.tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("url\tcompany\ttitle\tscore\tverdict\treason\n")
        for r, dq in fails:
            f.write("\t".join([r["url"], r["company"], r["title"], "2.0", "FAIL", f"Hard DQ (rule): {dq}"]).replace("\n", " ") + "\n")
    hdr = "url\tcompany\ttitle\twhere\tjd_file\n"
    n = 0
    for i in range(0, len(keep), a.batch):
        n += 1
        with open(os.path.join(o.TRI, f"{a.prefix}-queue-{n:02d}.tsv"), "w", encoding="utf-8", newline="\n") as f:
            f.write(hdr + "".join("\t".join([r["url"], r["company"], r["title"], r.get("where", ""), jd]) + "\n" for r, jd in keep[i:i + a.batch]))
    nojd = sum(1 for r, jd in keep if not jd)
    print(f"{len(rows)} jobs: {len(fails)} rule FAILs -> {out}; {len(keep)} left for triage ({nojd} without a readable JD) "
          f"in {n} queue files data/triage/{a.prefix}-queue-NN.tsv")


if __name__ == "__main__":
    main()
