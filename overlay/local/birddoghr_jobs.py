"""career-ops local parser for BirdDogHR career-page widgets (jobs.ourcareerpages.com) (format: jobs-json-v1).

Employers embed BirdDogHR's listing widget (bdhr.generateListing({CCPCode: "..."})) on their own
careers page, so the page HTML has no jobs in it. The widget loads
jobs.ourcareerpages.com/WebServices/ccp_jobs.aspx?CCPCode=<code>, a JavaScript response that assigns
one JSON object holding every posting (title, city/state, last-update date). This reads that.

  python local/birddoghr_jobs.py https://middlesexco.com/careers/        # CCPCode read from the page
  python local/birddoghr_jobs.py "https://jobs.ourcareerpages.com/?CCPCode=MiddlesexCorporation110723"
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import datetime as dt, json, re, sys
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
SERVER = "https://jobs.ourcareerpages.com"


def ccp_code(url):
    m = re.search(r"[?&]CCPCode=([\w-]+)", url, re.I)
    if m:
        return m.group(1)
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    m = re.search(r"""CCPCode\s*:\s*["']([\w-]+)["']""", r.text)
    if not m:
        raise SystemExit("birddoghr: no CCPCode on page")
    return m.group(1)


def main():
    code = ccp_code(sys.argv[1])
    r = requests.get(f"{SERVER}/WebServices/ccp_jobs.aspx",
                     params={"AutoGenerate": "yes", "GroupBy": "", "CCPCode": code, "InAccountID": 0,
                             "ElementID": "BDHRJobListings", "JobOrderBy": ""},
                     headers=UA, timeout=15)
    r.raise_for_status()
    m = re.search(r"=\s*\{\s*ccpInfo\s*:\s*(\{.*\})\s*\}\s*;", r.text, re.S)
    if not m:
        raise SystemExit("birddoghr: ccpInfo not found")
    info = json.loads(m.group(1))
    out, seen = [], set()
    for cat in info.get("CategoryList") or []:
        for job in cat.get("JobList") or []:
            if not job.get("ID") or not job.get("JobTitle") or job["ID"] in seen:
                continue
            seen.add(job["ID"])
            loc = job.get("Location") or ", ".join(x for x in (job.get("City"), job.get("StateAbbrev")) if x)
            row = {"title": job["JobTitle"].strip(), "url": f"{SERVER}/job/{job['ID']}?source={code}",
                   "location": (loc or "").strip()}
            ms = re.search(r"Date\((\d+)", job.get("LastUpdateDate") or "")
            if ms:
                row["postedAt"] = dt.datetime.fromtimestamp(int(ms.group(1)) / 1000, dt.timezone.utc).isoformat()
            out.append(row)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
