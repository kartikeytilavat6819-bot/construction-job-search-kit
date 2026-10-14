"""Zero-token pre-ranking of data/pipeline.md "Pending" rows (no AI calls, no network).

Score = 2 x location + title seniority + target title + H-1B history, with every list taken from
config/targeting.yml (home metro towns, home state, region, entry-level and target titles, public agencies). Then:
  * rewrites the Pending section of data/pipeline.md in score order (home-metro entry-level jobs first),
  * writes data/pipeline-ranked.md (readable table) and prints the top N.

  python local/rank_pipeline.py [--top 25] [--dry-run]
"""
import argparse, csv, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import targeting as T  # noqa: E402

PIPE = os.path.join(ROOT, "data", "pipeline.md")
H1B = os.path.join(ROOT, "data", "h1b-tracker.csv")
OUT = os.path.join(ROOT, "data", "pipeline-ranked.md")

REMOTE = re.compile(r"remote", re.I)
# Home-metro town names that also exist elsewhere (Everett WA, Lexington KY, Medford OR, Quincy IL, Newton IA...):
# a town hit only counts when the location names no other state.
_OTHER_CODES = [c for c in T.STATE_CODES if c != T.STATE_CODE]
_OTHER_NAMES = [T.STATE_NAMES[c].lower() for c in _OTHER_CODES if c != "DC"]
OTHER_STATE = re.compile(r",\s*(" + "|".join(_OTHER_CODES) + r")\b|-(" + "|".join(_OTHER_CODES) + r")-|\.("
                         + "|".join(_OTHER_CODES) + r")\.|\b(" + "|".join(_OTHER_NAMES) + r")\b", re.I)


def near_home(location):
    if not T.METRO.search(location):
        return False
    return bool(T.STATE_I.search(location)) or not OTHER_STATE.search(location.replace("Washington St", ""))


TIER_POINTS = {"strong": 1.0, "moderate": 0.5, "weak": 0.0, "staffing-shop": 0.0, "none": -0.5, "unknown": 0.0}


def h1b_tiers():
    tiers = {}
    try:
        for row in csv.DictReader(open(H1B, encoding="utf-8-sig")):
            name = (row.get("company") or "").strip().lower()
            if name and not name.startswith("↳") and name not in tiers:
                tiers[name] = (row.get("tier") or "unknown").strip().lower()
    except FileNotFoundError:
        pass
    return tiers


def tier_for(company, tiers):
    c = company.lower()
    for name, tier in tiers.items():
        if name and (name in c or c in name):
            return tier
    return "unknown"


def score(company, title, location, tiers):
    S = T.LOC_SCORES
    if near_home(location):
        loc_label = T.METRO_LABEL
    elif T.STATE_I.search(location):
        loc_label = T.STATE_LABEL
    elif T.REGION_I.search(location):
        loc_label = T.REGION_LABEL
    elif REMOTE.search(location):
        loc_label = "Remote"
    elif location.strip() in ("", "N/A"):
        loc_label = "Unknown"
    else:
        loc_label = "Other US"
    s = S[loc_label] * 2  # location weighs double: home area first
    s += 1.5 if T.TITLE_ENTRY.search(title) else (-0.5 if T.TITLE_STRETCH.search(title) else 0)
    s += 1.0 if T.TITLE_TARGET.search(title) else 0
    tier = "public agency" if T.PUBLIC_AGENCY.search(company) else tier_for(company, tiers)
    s += -0.5 if tier == "public agency" else TIER_POINTS.get(tier, 0)
    return round(s, 2), loc_label, tier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(PIPE):
        raise SystemExit("data/pipeline.md not found: run a scan first (node scan.mjs)")
    lines = open(PIPE, encoding="utf-8").read().split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip().lower().startswith("## pending")) + 1
    except StopIteration:
        raise SystemExit("no '## Pending' section in data/pipeline.md")
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    pending = [l for l in lines[start:end] if l.startswith("- [ ]")]
    other = [l for l in lines[start:end] if l.strip() and not l.startswith("- [ ]")]
    tiers = h1b_tiers()
    ranked = []
    for l in pending:
        parts = [p.strip() for p in l[6:].split("|")]
        url, company, title = parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""
        location = parts[3] if len(parts) > 3 and not parts[3].startswith("posted:") else ""
        s, loc_label, tier = score(company, title, location, tiers)
        ranked.append((s, loc_label, tier, company, title, url, l))
    ranked.sort(key=lambda r: -r[0])

    S = T.LOC_SCORES
    table = ["# Pipeline ranking (zero-token pre-score)", "",
             f"{len(ranked)} pending jobs. Score = 2x location ({T.METRO_LABEL} {S[T.METRO_LABEL]}, {T.STATE_LABEL} "
             f"{S[T.STATE_LABEL]}, {T.REGION_LABEL} {S[T.REGION_LABEL]}, other US {S['Other US']}, remote {S['Remote']}) "
             "+ entry-level title 1.5 + target title 1 + H-1B tier (strong 1, moderate 0.5, public agency -0.5).", "",
             "| # | Score | Where | H-1B | Company | Title |", "|---|---|---|---|---|---|"]
    table += [f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} | [{r[4]}]({r[5]}) |" for i, r in enumerate(ranked, 1)]
    open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(table) + "\n")
    if not a.dry_run:
        new = lines[:start] + [""] + [r[6] for r in ranked] + other + [""] + lines[end:]
        open(PIPE, "w", encoding="utf-8", newline="\n").write("\n".join(new).replace("\n\n\n", "\n\n"))
    print(f"ranked {len(ranked)} pending jobs -> {os.path.relpath(OUT, ROOT)}" + (" (dry run)" if a.dry_run else ""))
    for i, r in enumerate(ranked[:a.top], 1):
        print(f"{i:>2}. {r[0]:>5}  {r[1]:<13} {r[2]:<13} {r[3]} | {r[4]}")


if __name__ == "__main__":
    main()
