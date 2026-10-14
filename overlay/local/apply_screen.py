"""Apply local/sponsor_screen.py results + junk rules to the queue (no AI calls):
  * REFUSES (no sponsorship / citizens only / clearance) and UK-titled rows leave Pending -> Processed with the reason,
  * each is logged to data/discard.log,
  * their data/scan-history.tsv rows become skipped_* so the web Today page stops showing them.

  python local/apply_screen.py
"""
import datetime as dt, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.md")
HIST = os.path.join(ROOT, "data", "scan-history.tsv")
SCREEN = os.path.join(ROOT, "data", "sponsor-screen.json")
DISCARD = os.path.join(ROOT, "data", "discard.log")
UK = re.compile(r"\b(UK|U\.K\.|United Kingdom)\b")
# Foreign postings that slip past the location filter (city-only or country-code locations).
FOREIGN_LOC = re.compile(
    r"(^|[\s;·])(GB|CA|IN|AU|IE|NZ|PH|DE|NL|FR|ES|PL|MX|BR|AE|SA|QA|SG|HK)\.[A-Z]{2,}"   # AtkinsRealis GB.Derby / CA.QC.Montreal
    r"|\b(London|Manchester|Birmingham|Bristol|Leeds|Glasgow|Edinburgh|Cardiff|Belfast|Sheffield|Newcastle|"
    r"Nottingham|Liverpool|Croydon|Cambridge|Oxford|Southampton|Brighton|Aberdeen|Warrington|Milton Keynes|"
    r"Guildford|Leicester|Coventry|Swindon|Exeter|Plymouth|Norwich|Derby|Epsom|Whitehaven|Peterborough|"
    r"Stockton-on-Tees|Reading|Bath|Bangalore|Bengaluru|Toronto|Vancouver|Calgary|Montr[eé]al|Ottawa|Qu[eé]bec)\b", re.I)
US_MARKER = re.compile(r"\bUS[.\- ]|United States|\bUSA\b|,\s*[A-Z]{2}\b|-[A-Z]{2}-|\b(Massachusetts|New Hampshire|Connecticut|"
                       r"Rhode Island|Maine|Vermont|New York|New Jersey|Pennsylvania|Alabama|Maryland|Virginia|Texas|"
                       r"California|Florida|Ohio|Illinois|Georgia|North Carolina|South Carolina)\b")
FRENCH_TITLE = re.compile(r"ing[ée]nieur|charg[ée]\(e\)|g[ée]nie civil|\(e\)", re.I)


def is_foreign(title, location):
    if UK.search(title) or FRENCH_TITLE.search(title):
        return True
    return bool(FOREIGN_LOC.search(location)) and not US_MARKER.search(location)


def main():
    reasons = {}
    if os.path.exists(SCREEN):
        for r in json.load(open(SCREEN, encoding="utf-8")):
            if r["verdict"] == "REFUSES":
                reasons[r["url"]] = ("skipped_sponsorship", f"refuses sponsorship (pre-screen): {r['evidence'][:140]}")
    if not os.path.exists(PIPE):
        print("no data/pipeline.md yet")
        return
    lines = open(PIPE, encoding="utf-8").read().split("\n")
    keep, moved = [], []
    for l in lines:
        if l.startswith("- [ ]"):
            parts = [p.strip() for p in l[6:].split("|")]
            url, company, title = parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""
            location = parts[3] if len(parts) > 3 and not parts[3].startswith("posted:") else ""
            if url not in reasons and is_foreign(title, location):
                reasons[url] = ("skipped_location", f"outside the US ({location[:60] or title[:60]})")
            if url in reasons:
                moved.append((url, company, title, reasons[url]))
                continue
        keep.append(l)
    if not moved:
        print("nothing to move")
        return
    try:
        p = next(i for i, l in enumerate(keep) if l.strip().lower().startswith("## processed"))
    except StopIteration:
        keep += ["", "## Processed"]
        p = len(keep) - 1
    keep[p + 1:p + 1] = [f"- [x] ~~{u} | {c} | {t}~~ - {why[1].replace('|', '/')}" for u, c, t, why in moved]
    open(PIPE, "w", encoding="utf-8", newline="\n").write("\n".join(keep))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(DISCARD, "a", encoding="utf-8") as f:
        for u, c, t, why in moved:
            f.write(f"{now}\t{u}\t{why[1]}\n")
    rows = open(HIST, encoding="utf-8").read().split("\n") if os.path.exists(HIST) else [""]
    status = {u: why[0] for u, c, t, why in moved}
    n = 0
    for i, r in enumerate(rows[1:], 1):
        c = r.split("\t")
        if len(c) > 5 and c[0] in status and c[5] == "added":
            c[5] = status[c[0]]
            rows[i] = "\t".join(c)
            n += 1
    open(HIST, "w", encoding="utf-8", newline="\n").write("\n".join(rows))
    by = {}
    for *_, why in moved:
        by[why[0]] = by.get(why[0], 0) + 1
    print(f"moved {len(moved)} rows out of Pending ({', '.join(f'{k} {v}' for k, v in by.items())}); history rows updated: {n}")


if __name__ == "__main__":
    main()
