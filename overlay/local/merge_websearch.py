"""Merge the parallel web-search results (data/websearch/slice-*.tsv) into data/pipeline.md "## Pending".

Each search helper writes its own TSV (url, company, title, location, note) so 20+ helpers never fight over
pipeline.md. This adds every row whose URL is not already in pipeline.md or applications.md, skipping firms
that state they do not sponsor visas. Backs up pipeline.md first. Safe to re-run.

  python local/merge_websearch.py [--dry-run]
"""
import csv, glob, os, re, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.md")
# firms whose postings (seen in October 2026, mostly engineering / construction firms) said they will not sponsor
# work visas. Factual and worth keeping; add firms you see refuse sponsorship.
NO_SPONSOR = re.compile(r"thomas\s*&\s*hutton|woolpert|tata\s*&\s*howard|pare corp|hoyle tanner|aquarion|mortenson|\bklj\b|morrison[- ]maierle|bohannan huston|cobb fendley|austin bridge|shimmick|\bliro\b|erdman anthony|greenman[- ]pedersen|\bgpi\b|johnson,? mirmiran|\bjmt\b|whitman,? requardt|\bwra\b|french (&|and) parrello|septa|mead (&|and) hunt|passero|galloway|\bbnsf\b|holder construction|^holder$|^seh\b|short elliott|alliant engineering|bolton (&|and) menk|barr engineering|jones edmunds|huitt[- ]zollars|ea engineering|wilson (&|and) company", re.I)


def main():
    dry = "--dry-run" in sys.argv
    raw = open(PIPE, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    seen = set(re.findall(r"https?://[^\s|~]+", raw))
    ap = os.path.join(ROOT, "data", "applications.md")
    if os.path.exists(ap):
        seen |= set(re.findall(r"https?://[^\s|)]+", open(ap, encoding="utf-8").read()))
    new, skipped = [], {"duplicate": 0, "no sponsorship": 0, "bad row": 0}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "websearch", "slice-*.tsv"))):
        for r in csv.DictReader(open(f, encoding="utf-8-sig"), delimiter="\t"):
            url = (r.get("url") or "").strip()
            company = (r.get("company") or "").strip()
            if not url.startswith("http") or not company:
                skipped["bad row"] += 1
                continue
            if url in seen:
                skipped["duplicate"] += 1
                continue
            if NO_SPONSOR.search(company):
                skipped["no sponsorship"] += 1
                continue
            seen.add(url)
            cells = [url, company, (r.get("title") or "").strip(), (r.get("location") or "").strip()]
            new.append("- [ ] " + " | ".join(c.replace("|", "/") for c in cells))
    print(f"{len(new)} new jobs; skipped: " + ", ".join(f"{k} {v}" for k, v in skipped.items()))
    if dry or not new:
        for line in new:
            print("  " + line)
        return
    lines = raw.split(nl)
    at = next(i for i, l in enumerate(lines) if l.strip() == "## Pending") + 1
    while at < len(lines) and not lines[at].strip():
        at += 1
    bak = PIPE + time.strftime(".backup-before-websearch-merge-%Y%m%d-%H%M%S")
    shutil.copy2(PIPE, bak)
    with open(PIPE, "w", encoding="utf-8", newline="") as fh:
        fh.write(nl.join(lines[:at] + new + lines[at:]))
    print(f"backup: {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
