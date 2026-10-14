"""career-ops local parser for Paycom career portals (format: jobs-json-v1).

A Paycom board (www.paycomonline.net/v4/ats/web.php/jobs?clientkey=<KEY>, which redirects to
/v4/ats/web.php/portal/<KEY>/career-page) is a JavaScript app. The page HTML carries a public,
anonymous session JWT (configsFromHost.sessionJWT) and the API host; the app then POSTs
api/ats/job-posting-previews/search with that token as Authorization. This does the same: one page
fetch plus one or two search calls.

  python local/paycom_jobs.py "https://www.paycomonline.net/v4/ats/web.php/jobs?clientkey=C6D898A81CCCD1B20AB2D2325FE90D89"
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import json, re, sys
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
TAKE = 200
MAX_PAGES = 10
FILTERS = {"distanceFrom": 0, "workEnvironments": [], "positionTypes": [], "educationLevels": [], "categories": [],
           "travelTypes": [], "shiftTypes": [], "otherFilters": [], "keywordSearchText": "", "location": "",
           "sortOption": ""}


def main():
    m = re.search(r"(?:clientkey=|/portal/)([0-9A-Fa-f]{32})", sys.argv[1])
    if not m:
        raise SystemExit("paycom: no 32-hex client key in URL")
    key = m.group(1).upper()
    portal = f"https://www.paycomonline.net/v4/ats/web.php/portal/{key}"
    r = requests.get(f"{portal}/career-page", headers=UA, timeout=15)
    r.raise_for_status()
    jwt = re.search(r'"sessionJWT"\s*:\s*"([^"]+)"', r.text)
    if not jwt:
        raise SystemExit("paycom: sessionJWT not found on career page")
    svc = re.search(r'atsPortalMantleServiceUrl\\*"\s*:\s*\\*"(https:[^"]+?)\\*"', r.text)
    service = (svc.group(1).replace("\\/", "/").replace("\\", "") if svc
               else "https://portal-applicant-tracking.us-cent.paycomonline.net/").rstrip("/")
    headers = {**UA, "Authorization": jwt.group(1), "Locale": "en-US", "Accept": "application/json"}
    posts = []
    for page in range(MAX_PAGES):
        resp = requests.post(f"{service}/api/ats/job-posting-previews/search", headers=headers, timeout=15,
                             json={"skip": page * TAKE, "take": TAKE, "filtersForQuery": FILTERS})
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("jobPostingPreviews") or []
        posts.extend(batch)
        if not batch or len(posts) >= int(data.get("jobPostingPreviewsCount") or 0):
            break
    out, seen = [], set()
    for p in posts:
        jid = p.get("jobId")
        if not jid or not p.get("jobTitle") or jid in seen:
            continue
        seen.add(jid)
        # "East Hartford, CT 06108; Providence, RI 02903" -> drop the ZIPs
        loc = "; ".join(re.sub(r"\s+\d{5}(?:-\d{4})?$", "", x.strip()).replace(" ,", ",")
                        for x in (p.get("locations") or "").split(";") if x.strip())
        if p.get("remoteType"):
            loc = f"{loc} ({p['remoteType']})" if loc else p["remoteType"]
        row = {"title": p["jobTitle"].strip(), "url": f"{portal}/jobs/{jid}", "location": loc}
        if p.get("postedOn"):
            row["postedAt"] = p["postedOn"]
        out.append(row)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
