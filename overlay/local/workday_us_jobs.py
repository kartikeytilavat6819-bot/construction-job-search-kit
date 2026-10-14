"""career-ops local parser for a Workday board restricted by one Workday facet (format: jobs-json-v1).

Global boards like AtkinsRealis (slihrms) mix UK/Canada/India postings with US ones and write locations
as "GB.Derby..." / "CA.QC.Montreal..." / "3 Locations", which defeats the location filter. Workday's
own search API accepts the same facet filter as the site's "Country" checkbox, so ask it for US jobs only.

  python local/workday_us_jobs.py https://slihrms.wd3.myworkdayjobs.com/Careers Location_Country=bc33aa3152ec42d4995f4791a106ed09
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import datetime as dt, hashlib, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "application/json", "Content-Type": "application/json"}
PAGE = 20
MULTI = re.compile(r"^\d+ Locations$", re.I)


def parse(url):
    m = re.match(r"https?://([^.]+)\.wd(\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)", url)
    if not m:
        sys.exit(f"not a Workday board URL: {url}")
    tenant, wd, site = m.groups()
    base = f"https://{tenant}.wd{wd}.myworkdayjobs.com"
    return base, f"{base}/wday/cxs/{tenant}/{site}", site


def age_to_iso(text):
    t = (text or "").lower()
    days = 0 if "today" in t else 1 if "yesterday" in t else None
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        days = int(m.group(1))
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date().isoformat() if days is not None else None


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_MAX_AGE_S = 12 * 3600


def cache_path(args):
    return os.path.join(CACHE_DIR, "workday-" + hashlib.sha1(" ".join(args).encode()).hexdigest()[:16] + ".json")


def main():
    # --prefetch <url> <facet>...: run by local\daily-scan.ps1 before scan.mjs (no time limit, ~1-2 min for
    # AtkinsRealis); the scan itself then answers from the cache instantly instead of hitting the 20 s cap.
    prefetch = sys.argv[1] == "--prefetch"
    args = sys.argv[2:] if prefetch else sys.argv[1:]
    path = cache_path(args)
    if not prefetch and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE_S:
        sys.stdout.write(open(path, encoding="utf-8").read())
        return
    sys.argv = [sys.argv[0]] + args
    base, api, site = parse(sys.argv[1])
    facets = {}
    for arg in sys.argv[2:]:
        k, _, v = arg.partition("=")
        facets.setdefault(k, []).append(v)

    def page(offset):
        r = requests.post(api + "/jobs", json={"appliedFacets": facets, "limit": PAGE, "offset": offset, "searchText": ""},
                          headers=H, timeout=15)
        r.raise_for_status()
        return r.json()

    first = page(0)
    total = min(int(first.get("total") or 0), 2000)
    posts = list(first.get("jobPostings", []))
    with ThreadPoolExecutor(8) as ex:
        for d in ex.map(page, range(PAGE, total, PAGE)):
            posts += d.get("jobPostings", [])

    def to_job(p):
        path = p.get("externalPath", "")
        loc = p.get("locationsText", "") or ""
        if MULTI.match(loc):  # "3 Locations": ask the detail endpoint for the real offices
            try:
                info = requests.get(api + path, headers=H, timeout=10).json().get("jobPostingInfo", {})
                loc = "; ".join([info.get("location", "")] + list(info.get("additionalLocations") or []))
            except Exception:
                pass
        job = {"title": p.get("title", ""), "url": f"{base}/{site}{path}", "location": loc}
        posted = age_to_iso(p.get("postedOn"))
        if posted:
            job["postedAt"] = posted
        return job

    seen, out = set(), []
    with ThreadPoolExecutor(8) as ex:
        for j in ex.map(to_job, posts):
            if j["url"] not in seen:
                seen.add(j["url"])
                out.append(j)
    if out:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(path + ".tmp", path)
    if prefetch:
        print(f"prefetch {base}: {len(out)} jobs", file=sys.stderr)
    else:
        json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
