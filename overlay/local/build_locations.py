"""Write data/locations.tsv (tracker row -> job location) so the web app can filter by state.

The tracker has no location column; each row's report carries the posting URL (**URL:**), and data/scan-history.tsv
(plus data/pipeline.md) record the scanner's location for that URL. Fallback: a "City, ST" found in the row's role
or the first note segment.   python local/build_locations.py
"""
import csv, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
ST = r"(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)"


def norm(u):
    return (u or "").strip().rstrip("/").split("#")[0]


def main():
    if not os.path.exists(os.path.join(D, "applications.md")):
        print("locations.tsv: no tracker (data/applications.md) yet")
        return
    loc = {}
    if os.path.exists(os.path.join(D, "scan-history.tsv")):
        with open(os.path.join(D, "scan-history.tsv"), encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("location"):
                    loc[norm(r["url"])] = r["location"]
    for l in (open(os.path.join(D, "pipeline.md"), encoding="utf-8") if os.path.exists(os.path.join(D, "pipeline.md")) else []):
        m = re.match(r"^- \[[ x]\] ~?~?(\S+) \| [^|]* \| [^|]* \| ([^|~]+)", l)
        if m and not m.group(2).strip().startswith("posted:"):
            loc.setdefault(norm(m.group(1)), m.group(2).strip())
    out, hit = [], 0
    for l in open(os.path.join(D, "applications.md"), encoding="utf-8"):
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(c) < 8 or not c[0].isdigit():
            continue
        n, role, notes, rep = c[0], c[3], (c[8] if len(c) > 8 else ""), c[7]
        where = ""
        m = re.search(r"\((?:\.\./)?(reports/[^)]+)\)", rep)
        if m and os.path.exists(os.path.join(ROOT, m.group(1))):
            head = open(os.path.join(ROOT, m.group(1)), encoding="utf-8", errors="replace").read(4000)
            u = re.search(r"^\*\*URL:\*\*\s*<?(\S+?)>?\s*$", head, re.M)
            if u:
                where = loc.get(norm(u.group(1)), "")
        if not where:
            mm = re.search(r"([A-Z][A-Za-z .'-]+),\s*" + ST + r"\b", f"{role}; {notes.split(';')[0]}")
            where = mm.group(0) if mm else ""
        hit += bool(where)
        out.append((n, where.replace("\t", " ")))
    with open(os.path.join(D, "locations.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("n\tlocation\n" + "".join(f"{n}\t{w}\n" for n, w in out))
    print(f"locations.tsv: {hit}/{len(out)} tracker rows have a location")


if __name__ == "__main__":
    main()
