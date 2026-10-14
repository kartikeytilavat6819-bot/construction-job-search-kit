"""career-ops local parser for Dayforce (Ceridian) candidate portals (format: jobs-json-v1).

jobs.dayforcehcm.com/<locale>/<clientNamespace>/<jobBoardCode> is a Next.js app that loads its
postings client-side from POST /api/geo/<clientNamespace>/jobposting/search (25 per page). Like the
page itself, this first loads the board, takes the site's own CSRF token from /api/auth/csrf, and
sends it as X-CSRF-TOKEN; pages after the first are fetched in parallel.

  python local/dayforce_jobs.py https://jobs.dayforcehcm.com/en-US/balfourbeatty/CANDIDATEPORTALBUILDINGCIVILS
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
ORIGIN = "https://jobs.dayforcehcm.com"
PAGE = 25
MAX_PAGES = 40


def location(post):
    locs = []
    for loc in post.get("postingLocations") or []:
        text = (loc.get("formattedAddress") or loc.get("locationName") or "").strip()
        text = re.sub(r",\s*USA$", "", text)
        if text and text not in locs:
            locs.append(text)
    if post.get("hasVirtualLocation"):
        locs.append("Remote")
    return "; ".join(locs)


def main():
    m = re.match(r"https?://jobs\.dayforcehcm\.com/(?:([a-z]{2}-[A-Za-z]{2,4})/)?([^/?#]+)/([^/?#]+)", sys.argv[1])
    if not m:
        raise SystemExit("dayforce: expected https://jobs.dayforcehcm.com/<locale>/<client>/<board>")
    locale, ns, board = m.group(1) or "en-US", m.group(2), m.group(3)
    page_url = f"{ORIGIN}/{locale}/{ns}/{board}"
    s = requests.Session()
    s.headers.update(UA)
    s.get(page_url, timeout=15).raise_for_status()
    token = s.get(f"{ORIGIN}/api/auth/csrf", timeout=15).json()["csrfToken"]
    headers = {"X-CSRF-TOKEN": token, "Origin": ORIGIN, "Referer": page_url, "Accept": "application/json"}

    def search(start):
        body = {"clientNamespace": ns, "jobBoardCode": board, "cultureCode": locale,
                "distanceUnit": 0, "paginationStart": start}
        r = s.post(f"{ORIGIN}/api/geo/{ns}/jobposting/search", json=body, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()

    first = search(0)
    posts = list(first.get("jobPostings") or [])
    total = min(int(first.get("maxCount") or 0), PAGE * MAX_PAGES)
    with ThreadPoolExecutor(8) as ex:
        for data in ex.map(search, range(PAGE, total, PAGE)):
            posts.extend(data.get("jobPostings") or [])
    out, seen = [], set()
    for p in posts:
        pid = p.get("jobPostingId")
        if not pid or not p.get("jobTitle") or pid in seen:
            continue
        seen.add(pid)
        row = {"title": p["jobTitle"].strip(), "url": f"{page_url}/jobs/{pid}", "location": location(p)}
        if p.get("postingStartTimestampUTC"):
            row["postedAt"] = p["postingStartTimestampUTC"]
        out.append(row)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
