"""career-ops local parser for Oracle SelectMinds (Taleo "referrals") boards, e.g. Tetra Tech
(format: jobs-json-v1).

Tetra Tech's Taleo section redirects to tetratech.referrals.selectminds.com. Its job list is
server-rendered, but only 10 jobs per page out of ~1,100 worldwide, so this runs the site's own
location search -- the same calls its search box makes: POST /ajax/jobs/search/create with a
state-level geo location, then POST /ajax/content/job_results for each 10-job page. That needs the
guest session cookie and the page's CSRF token (`tsstoken`, sent back as the `tss-token` header
exactly as the site's jQuery does), so one plain GET of /jobs/search comes first.
One search per New England state, ~15 requests in all, ~3-5 s.

  python local/selectminds_jobs.py https://tetratech.referrals.selectminds.com/jobs/search
Prints: [{"title", "url", "location"}, ...]  (the list carries no posting date)

A posting with several locations shows only its first one ("Tampa, Florida, United States and 6
additional locations"); the state(s) whose search matched it are appended so the career-ops
location filter can see them.
"""
import json, math, re, sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
# Oracle geo areas, as returned by the site's /ajax/geolocation/auto-suggest (level "region").
COUNTRY_US = "21000001"
STATES = {  # name: (area id, lat, long)
    "Massachusetts": ("21014299", "42.2365", "-70.98108"),
    "Connecticut": ("21014228", "41.56695", "-73.03552"),
    "Rhode Island": ("21014992", "41.47488", "-71.46349"),
    "New Hampshire": ("21014721", "43.15122", "-71.56444"),
    "Vermont": ("21015047", "44.36668", "-72.70599"),
    "Maine": ("21014244", "44.32105", "-69.02417"),
}
MAX_PAGES = 15  # per state, 10 jobs a page


def parse_rows(html):
    jobs = []
    for row in BeautifulSoup(html, "html.parser").select(".job_list_row"):
        a = row.select_one("a.job_link")
        if not a or not a.get("href"):
            continue
        loc = row.select_one(".location")
        jobs.append({"title": a.get_text(" ", strip=True), "url": a["href"],
                     "location": loc.get_text(" ", strip=True) if loc else ""})
    return jobs


def main():
    host = urlparse(sys.argv[1]).netloc
    base = f"https://{host}"
    s = requests.Session()
    s.headers.update(UA)
    r = s.get(base + "/jobs/search", timeout=15)
    r.raise_for_status()
    token = re.search(r'id\s*=\s*"tsstoken"\s+value\s*="([^"]+)"', r.text).group(1)
    site = re.search(r'short_name:\s*"([^"]+)"', r.text)
    xhr = {"X-Requested-With": "XMLHttpRequest", "tss-token": token}

    def results(jsid, page):
        q = f"JobSearch.id={jsid}&page_index={page}&include_site=true" + (f"&site-name={site.group(1)}" if site else "")
        rr = s.post(f"{base}/ajax/content/job_results?{q}", headers=xhr, timeout=15)
        rr.raise_for_status()
        return rr.json()["Result"]

    def state_search(name):
        area, lat, lon = STATES[name]
        rr = s.post(base + "/ajax/jobs/search/create", headers=xhr, timeout=15, data={
            "keywords": "", "geo_location": f"{name}, United States", "geo_lat": lat, "geo_long": lon,
            "geo_level": "region", "geo_area_id": area, "geo_region_area_id": area,
            "geo_country_area_id": COUNTRY_US, "geo_search_radius_km": "40.25", "geo_search_radius_units": "mi"})
        rr.raise_for_status()
        jsid = rr.json()["Result"]["JobSearch.id"]
        first = results(jsid, 1)
        total = int((re.search(r'class="total_results">\s*(\d+)', first) or [0, "0"])[1])
        jobs = parse_rows(first)
        for page in range(2, min(math.ceil(total / 10), MAX_PAGES) + 1):
            jobs += parse_rows(results(jsid, page))
        return name, jobs

    out, by_url = [], {}
    with ThreadPoolExecutor(3) as ex:
        for name, jobs in ex.map(state_search, STATES):
            for j in jobs:
                if j["url"] not in by_url:
                    by_url[j["url"]] = j
                    out.append(j)
                j = by_url[j["url"]]
                if name not in j["location"]:
                    j["location"] += f"; {name}, United States"
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
