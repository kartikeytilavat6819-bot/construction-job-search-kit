"""career-ops local parser for DirectEmployers ".jobs" sites, e.g. Stantec (format: jobs-json-v1).

stantec.jobs is a JavaScript (Nuxt) site, so the page HTML has no jobs in it. Its job feeds live under
/*feed/, which robots.txt disallows, so this reads the DirectEmployers search API the page itself
calls, with the same `location`/`q` filters as the search page: one paged search per New England
state (6 searches in parallel, ~2 s total).

  python local/directemployers_jobs.py https://stantec.jobs/
  python local/directemployers_jobs.py "https://stantec.jobs/jobs/?location=New+York"   # custom filter

If the careers URL carries its own `location` and/or `q` query parameters, that single search is
used instead of the New England default. A requisition posted at several offices appears once, with
all its offices in `location` (joined by "; ").
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
NEW_ENGLAND = ["Massachusetts", "Connecticut", "Rhode Island", "New Hampshire", "Vermont", "Maine"]
NUM_ITEMS = 500  # per feed request; a single New England state is well under this


SEARCH_API = "https://prod-search-api.jobsyn.org/api/v1/solr/search"
MAX_PAGES = 10  # 50 jobs/page; one New England state is ~2 pages


def feed(host, params):
    # The site's robots.txt disallows /*feed/, so read the same search API the site's own job
    # page calls (it identifies the tenant by the x-origin header, as the page does).
    headers = {**UA, "Accept": "application/json", "x-origin": host}
    jobs = []
    for page in range(1, MAX_PAGES + 1):
        r = requests.get(SEARCH_API, params={**params, "page": page}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        for it in data.get("jobs", []):
            title = it.get("title_exact")
            if not title or not it.get("guid"):
                continue
            job = {"title": title.strip(), "url": f"https://{host}/{it['guid']}/job/",
                   "location": it.get("location_exact") or ", ".join(x for x in (it.get("city_exact"), it.get("state_short")) if x)}
            if it.get("reqid"):
                job["reqId"] = it["reqid"]
            if it.get("date_new"):
                job["postedAt"] = it["date_new"]
            jobs.append(job)
        if not (data.get("pagination") or {}).get("has_more_pages"):
            break
    return jobs


def main():
    u = urlparse(sys.argv[1])
    qs = {k: v[0] for k, v in parse_qs(u.query).items() if k in ("location", "q") and v and v[0]}
    searches = [qs] if qs else [{"location": st} for st in NEW_ENGLAND]
    # DirectEmployers lists a multi-office requisition once per office (same reqId, separate URLs);
    # fold those into one row whose location names every office.
    out, by_key = [], {}
    with ThreadPoolExecutor(len(searches)) as ex:
        for jobs in ex.map(lambda p: feed(u.netloc, p), searches):
            for j in jobs:
                key = (j.get("reqId") or j["url"], j["title"].lower())
                if key not in by_key:
                    by_key[key] = j
                    out.append(j)
                elif j["location"] and j["location"] not in by_key[key]["location"].split("; "):
                    by_key[key]["location"] += "; " + j["location"]
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
