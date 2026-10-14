"""Move already-decided rows out of data/pipeline.md Pending (zero-token), so the Inbox shows only open work.

Moves to Processed: rows already in the tracker, and rows that FAILED a check (free rules, local model, Claude triage).
Keeps Pending: PASS / MARGINAL / SKIP (unreadable) / ERROR / never checked.  Backup: data/pipeline.backup-before-clean.md
  python local/clean_pending.py [--dry-run]
"""
import csv, glob, os, shutil, sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(R, "data", "triage")
PIPE = os.path.join(R, "data", "pipeline.md")


def load(patterns):
    d = {}
    for p in patterns:
        for f in glob.glob(os.path.join(T, p)):
            for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
                if r.get("url"):
                    d[r["url"]] = (r.get("verdict", ""), (r.get("reason") or "")[:90])
    return d


def main():
    claude = load(["result-*.tsv", "ne-result-*.tsv", "lp-result-*.tsv", "ma-result-*.tsv"])
    rule = load(["rule-result-*.tsv"])
    local = load(["local-result-*.tsv"])
    if not os.path.exists(PIPE):
        print("no data/pipeline.md yet")
        return
    ap = os.path.join(R, "data", "applications.md")
    apps = open(ap, encoding="utf-8").read() if os.path.exists(ap) else ""
    # Claude-PASS rows that were never queued for full evaluation (repeats, deferred, or below 3.7)
    queued = set()
    for f in glob.glob(os.path.join(R, "data", "eval-queue-*.tsv")):
        queued |= {r.get("url", "") for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t")}
    parked_urls = {u for u, (v, _) in claude.items() if v == "PASS" and u not in queued}
    repost_urls = set()
    rp = os.path.join(T, "lp-reposts.tsv")
    if os.path.exists(rp):
        for l in open(rp, encoding="utf-8"):
            c = l.rstrip("\n").split("\t")
            if len(c) > 3:
                repost_urls.add(c[3])
    # local-PASS rows collapsed as multi-city reposts when the Claude queues were built (same company + title)
    import re as _re
    seen_keys = set()
    for f in sorted(glob.glob(os.path.join(T, "lp-queue-*.tsv"))):
        for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
            seen_keys.add((r["company"].lower(), _re.sub(r"[^a-z0-9]+", " ", r["title"].lower()).strip()))
    for f in glob.glob(os.path.join(T, "local-result-*.tsv")):
        for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
            k = (r["company"].lower(), _re.sub(r"[^a-z0-9]+", " ", r["title"].lower()).strip())
            if r["verdict"] == "PASS" and r["url"] not in claude and k in seen_keys:
                repost_urls.add(r["url"])
    lines = open(PIPE, encoding="utf-8").read().split("\n")
    keep, moved = [], []
    for l in lines:
        if l.startswith("- [ ] "):
            p = l[6:].split(" | ")
            url = p[0].strip()
            why = None
            if url in apps:
                why = "evaluated - see tracker"
            elif claude.get(url, ("",))[0] == "FAIL":
                why = "Claude triage FAIL: " + claude[url][1]
            elif url in rule:
                why = "rule FAIL: " + rule[url][1].replace("Hard DQ (rule): ", "")
            elif local.get(url, ("",))[0] == "FAIL" and url not in claude:
                why = "local triage FAIL: " + local[url][1]
            # the web pages should only count jobs worth applying -> park MARGINAL / SKIP rows too.
            elif claude.get(url, ("",))[0] in ("MARGINAL", "SKIP"):
                why = f"parked (Claude triage {claude[url][0]}): " + claude[url][1]
            elif claude.get(url, ("",))[0] == "PASS" and url in parked_urls:
                why = "parked: multi-city repeat or below the 3.7 evaluation cut-off"
            elif url not in claude and local.get(url, ("",))[0] in ("MARGINAL", "SKIP", "ERROR"):
                why = f"parked (local triage {local[url][0]}): " + local[url][1]
            elif url not in claude and local.get(url, ("",))[0] == "PASS" and url in repost_urls:
                why = "parked: repeat of a job already evaluated/queued"
            if why:
                title = " | ".join(x.strip() for x in p[1:3])
                moved.append(f"- [x] ~~{url} | {title}~~ - {why.replace('|', '/')}")
                continue
        keep.append(l)
    left = sum(1 for l in keep if l.startswith("- [ ] "))
    print(f"moving {len(moved)} decided rows to Processed; {left} stay pending")
    if "--dry-run" in sys.argv or not moved:
        return
    shutil.copy2(PIPE, PIPE.replace(".md", ".backup-before-clean.md"))
    i = next((k for k, l in enumerate(keep) if l.strip().lower().startswith("## processed")), None)
    if i is None:
        keep += ["", "## Processed"]
        i = len(keep) - 1
    keep[i + 1:i + 1] = moved
    open(PIPE, "w", encoding="utf-8", newline="\n").write("\n".join(keep))


if __name__ == "__main__":
    main()
