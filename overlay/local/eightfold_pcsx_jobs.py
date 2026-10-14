"""career-ops local parser for Eightfold "PCSX" career sites, e.g. Arcadis (format: jobs-json-v1).

careers.arcadis.com links to arcadis.eightfold.ai. That tenant has moved to Eightfold's newer PCSX
careers site, so the old /api/apply/v2/jobs endpoint answers 403 "Not authorized for PCSX"; the
site's own search endpoint is /api/pcsx/search (allowed in its robots.txt), plain JSON, no auth.
It returns 10 jobs per request and ~370 for the whole US, so this runs one location search per New
England state (the site's own location box), ~10 requests 4 at a time, ~2-3 s.

  python local/eightfold_pcsx_jobs.py https://careers.arcadis.com/
  python local/eightfold_pcsx_jobs.py "https://<tenant>.eightfold.ai/careers?domain=<tenant>.com"
(A non-eightfold.ai careers URL is mapped from its domain name: careers.arcadis.com ->
arcadis.eightfold.ai with domain=arcadis.com. Listing Arcadis under careers.arcadis.com rather than its eightfold.ai
URL keeps career-ops' built-in Eightfold provider, which gets the 403, from claiming the entry.)
Prints: [{"title", "url", "location", "postedAt", "department"?, "reqId"?}, ...]

`location` lists every location on the posting ("; "-joined). The site's state search also returns
some remote-eligible US postings based elsewhere ("workLocation": "remote_local"); their location
is left as the posting states it, so career-ops' location filter decides. Only a fully remote
posting gets "Remote" appended.
"""
import datetime as dt, json, sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
NEW_ENGLAND = ["Massachusetts", "Connecticut", "Rhode Island", "New Hampshire", "Vermont", "Maine"]
PAGE = 10        # fixed by the API
MAX_PAGES = 6    # per state
WORKERS = 4


def search(host, domain, location, start):
    r = requests.get(f"https://{host}/api/pcsx/search", headers=UA, timeout=12,
                     params={"domain": domain, "query": "", "location": location, "start": start})
    r.raise_for_status()
    data = r.json().get("data") or {}
    return data.get("positions") or [], int(data.get("count") or 0)


def to_job(host, domain, p):
    locs = [l for l in (p.get("locations") or []) if l]
    work = (p.get("workLocationOption") or "").lower()  # onsite / hybrid / remote_local / remote ...
    if work in ("remote", "remote_global", "fully_remote"):
        locs.append("Remote")
    job = {"title": (p.get("name") or "").strip(),
           "url": f"https://{host}{p.get('positionUrl') or '/careers/job/' + str(p['id'])}?domain={domain}",
           "location": "; ".join(locs)}
    if p.get("postedTs"):
        job["postedAt"] = dt.datetime.fromtimestamp(p["postedTs"], dt.timezone.utc).isoformat()
    if work:
        job["workLocation"] = work
    if p.get("department"):
        job["department"] = p["department"]
    if p.get("displayJobId"):
        job["reqId"] = p["displayJobId"]
    return job


def main():
    u = urlparse(sys.argv[1])
    if u.netloc.endswith(".eightfold.ai"):
        host = u.netloc
        tenant = host.split(".")[0]
    else:  # company careers site, e.g. careers.arcadis.com -> arcadis.eightfold.ai
        tenant = u.netloc.split(".")[-2]
        host = f"{tenant}.eightfold.ai"
    domain = (parse_qs(u.query).get("domain") or [tenant + ".com"])[0]

    def state(location):
        positions, count = search(host, domain, location, 0)
        for start in range(PAGE, min(count, PAGE * MAX_PAGES), PAGE):
            positions += search(host, domain, location, start)[0]
        return positions

    out, seen = [], set()
    with ThreadPoolExecutor(WORKERS) as ex:
        for positions in ex.map(state, NEW_ENGLAND):
            for p in positions:
                if p.get("id") in seen or not p.get("name"):
                    continue
                seen.add(p.get("id"))
                out.append(to_job(host, domain, p))
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
