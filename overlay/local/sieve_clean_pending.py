"""Keep the website INBOX (pending rows of data/pipeline.md) down to jobs that still need a look.

Ticks off (- [x] ~~row~~ - reason, same format clean_pending.py uses) every pending row that is:
  - a LinkedIn alert/search/settings link (not a job posting)
  - a job the sieve REJECTED (reason copied from data/sieve/results.tsv)
  - already evaluated (its URL is in data/applications.md)
Leaves GOLD / SILVER / NO_JD / not-yet-sieved rows pending. Backs up pipeline.md first.

  python local/sieve_clean_pending.py [--dry-run]
Run it after a sieve pass (local/sieve-run.ps1 does this automatically).
"""
import csv, os, re, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.md")


def main():
    dry = "--dry-run" in sys.argv
    res = {}
    p = os.path.join(ROOT, "data", "sieve", "results.tsv")
    if os.path.exists(p):
        res = {r["url"]: r for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="\t")}
    if not os.path.exists(PIPE):
        print("no data/pipeline.md yet")
        return
    ap = os.path.join(ROOT, "data", "applications.md")
    tracked = set(re.findall(r"https?://[^\s|]+", open(ap, encoding="utf-8").read())) if os.path.exists(ap) else set()
    raw = open(PIPE, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    out, counts = [], {}
    for line in raw.split(nl):
        m = re.match(r"^(\s*-\s*)\[ \]\s*(.+)$", line)
        if not m:
            out.append(line)
            continue
        body = m.group(2).strip()
        url = body.split("|")[0].strip()
        why = None
        if "linkedin.com" in url and "/jobs/view/" not in url:
            why = "parked: LinkedIn alert/search link (not a job posting)"
        elif url in tracked:
            why = "evaluated - see tracker"
        else:
            r = res.get(url)
            if r and r["tier"] == "REJECT":
                why = f"parked (sieve REJECT {r['stage']}): {r['reason'][:150]}"
        if why:
            counts[why.split(":")[0]] = counts.get(why.split(":")[0], 0) + 1
            out.append(f"{m.group(1)}[x] ~~{body}~~ - {why}")
        else:
            out.append(line)
    total = sum(counts.values())
    print(f"{total} pending rows ticked off: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if dry or not total:
        return
    bak = PIPE + time.strftime(".backup-before-sieve-clean-%Y%m%d-%H%M")
    shutil.copy2(PIPE, bak)
    with open(PIPE, "w", encoding="utf-8", newline="") as fh:
        fh.write(nl.join(out))
    print(f"backup: {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
