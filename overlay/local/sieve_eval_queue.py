"""Build the Claude evaluation queue from the job sieve: GOLD jobs not yet in the tracker, home area first
(home metro / state / region from config/targeting.yml).

  python local/sieve_eval_queue.py [--tiers GOLD] [--top 20] [--out data/eval-queue-sieve.tsv]

Columns match local/eval-agent-brief-lean.md: group, company, title, url, jd_file, triage_score (one job per group),
plus prep_file (an optional AI "prep pack" from local/prep_pack.py; that script is not part of this kit, so the
column is normally empty).
Same-company postings with the same title are collapsed (the eval helper reuses the earlier tailoring anyway).
Jobs a Claude helper claimed in the last 3 hours (data/eval-claims.tsv: url <TAB> ISO time) are left out.
"""
import argparse, csv, datetime, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sieve as s  # noqa: E402
import targeting as T  # noqa: E402

try:
    from prep_pack import pack_path  # noqa: E402  (optional, not included in the kit)
except ImportError:
    def pack_path(url):
        return ""


def recent_claims(hours=3):
    claimed = set()
    cf = os.path.join(ROOT, "data", "eval-claims.tsv")
    if os.path.exists(cf):
        cut = datetime.datetime.now() - datetime.timedelta(hours=hours)
        for line in open(cf, encoding="utf-8"):
            c = line.rstrip("\n").split("\t")
            try:
                if len(c) > 2 and c[2].strip().startswith("done"):  # closed without a report (duplicate, closed...)
                    claimed.add(c[0])
                    continue
                if len(c) > 1:
                    t = datetime.datetime.fromisoformat(c[1].strip())
                    if t.tzinfo is not None:  # claims may carry a UTC offset (date -Iseconds)
                        t = t.astimezone().replace(tzinfo=None)
                    if t > cut:
                        claimed.add(c[0])
            except ValueError:
                pass
    return claimed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="GOLD", help="comma list, e.g. GOLD,SILVER")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--out", default=os.path.join("data", "eval-queue-sieve.tsv"))
    a = ap.parse_args()
    tiers = set(a.tiers.upper().split(","))

    if not os.path.exists(s.RESULTS):
        raise SystemExit("No sieve results yet: run python local/sieve.py first.")
    apps = s.read_text(os.path.join(ROOT, "data", "applications.md"))
    tracked = set(re.findall(r"https?://[^\s|]+", apps))
    # same company + same title already evaluated (another city of the same posting): the eval would only copy that
    # report's tailoring, so leave it out of the Claude queue
    done_titles, trilon_titles = set(), set()
    # Trilon's one board lists every brand under "Trilon Group", while the tracker names the brand (DRMP, HMB, ...),
    # so brand reports never matched and city clones kept reaching Claude
    trilon = re.compile(r"trilon|fuss|drmp|\bhmb\b|fehr graham|artheon|\bcph\b|horrocks|mannik|waggoner", re.I)
    for line in apps.splitlines():
        c = [x.strip() for x in line.split("|")]
        if len(c) > 5 and re.match(r"^\d", c[1] or ""):
            t = re.sub(r"\W+", " ", re.sub(r"\(.*?\)|-.*$|,.*$", "", c[4]).lower()).strip()
            done_titles.add((s.norm_co(c[3]), t))
            if trilon.search(c[3]):
                trilon_titles.add(t)
    claimed = recent_claims()
    jobs = {j["url"]: j for j in s.pipeline_jobs()}
    idx = s.jd_index()
    rows, seen = [], set()
    for r in csv.DictReader(open(s.RESULTS, encoding="utf-8"), delimiter="\t"):
        j = jobs.get(r["url"])
        if not j or r["tier"] not in tiers or r["url"] in tracked or r["url"] in claimed or j["evaluated"]:
            continue
        if "linkedin.com" in r["url"]:  # never open LinkedIn pages: alert rows aren't employer postings
            continue
        dup = (s.norm_co(j["company"]), re.sub(r"\W+", " ", re.sub(r"\(.*?\)|-.*$|,.*$", "", j["role"]).lower()).strip())
        if dup in seen or dup in done_titles or (trilon.search(j["company"]) and dup[1] in trilon_titles):
            continue
        seen.add(dup)
        jd = idx.get(r["url"], "")
        rows.append((T.loc_rank(r["loc_tier"]), r["tier"] != "GOLD", -float(r["score"] or 0), j, os.path.relpath(jd, ROOT) if jd else "", r["score"]))
    rows.sort(key=lambda x: x[:3])
    if a.top:
        rows = rows[: a.top]
    out = os.path.join(ROOT, a.out)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("group\tcompany\ttitle\turl\tjd_file\ttriage_score\tprep_file\n")
        for g, (_, _, _, j, jd, sc) in enumerate(rows, 1):
            pp = pack_path(j["url"])
            prep = os.path.relpath(pp, ROOT) if pp and os.path.exists(pp) else ""
            fh.write("\t".join(str(x).replace("\t", " ") for x in (g, j["company"], j["role"], j["url"], jd, sc, prep)) + "\n")
    print(f"{len(rows)} jobs -> {out}")
    for g, (_, _, _, j, _, sc) in enumerate(rows[:15], 1):
        print(f"  {g:3} {sc}  {j['company'][:28]:28} {j['role'][:55]}  [{j['location'][:25]}]")


if __name__ == "__main__":
    main()
