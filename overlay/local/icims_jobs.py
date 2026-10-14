"""career-ops local parser for iCIMS boards (format: jobs-json-v1).

career-ops's built-in iCIMS provider returns no location for some tenants, which defeats the
New England location filter. iCIMS's embeddable list (in_iframe=1) is server-rendered HTML that
does carry location and posted date, so this reads that instead.

  python local/icims_jobs.py https://careers-vhb.icims.com/jobs/search
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import datetime as dt, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
BATCH = 24  # pages fetched in parallel; career-ops kills a parser after 20 s (Kimley-Horn has ~28 pages)
MAX_PAGES = 80


def page(host, n):
    """Jobs on page n; [] past the last page; None if the page failed (slow/blocked) - skipped, not the end."""
    try:
        r = requests.get(f"https://{host}/jobs/search?ss=1&in_iframe=1&pr={n}", headers=UA, timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        return None
    jobs = []
    for card in BeautifulSoup(r.text, "html.parser").select("li.iCIMS_JobCardItem"):
        a = card.select_one("a.iCIMS_Anchor")
        if not a:
            continue
        loc = "; ".join(sp.get_text(" ", strip=True) for sp in card.select(".header.left > span:not(.sr-only)"))
        if not loc:  # some tenants (e.g. Dewberry) put it in a "Job Locations" header field instead
            for tag in card.select("div.iCIMS_JobHeaderTag"):
                dt_el, dd = tag.select_one("dt"), tag.select_one("dd")
                if dt_el and dd and "location" in dt_el.get_text(" ", strip=True).lower():
                    loc = dd.get_text(" ", strip=True)
                    break
        job = {"title": (a.select_one("h3") or a).get_text(" ", strip=True),
               "url": re.sub(r"[?&]in_iframe=1", "", a["href"]).replace("?&", "?"),
               "location": loc.replace(" | ", "; ")}
        posted = card.select_one(".header.right span[title]")
        if posted:
            try:
                job["postedAt"] = dt.datetime.strptime(posted["title"], "%m/%d/%Y %I:%M %p").isoformat()
            except ValueError:
                pass
        jobs.append(job)
    return jobs


DEADLINE_S = 10  # career-ops kills a parser at 20 s; during a full scan several iCIMS tenants run at once and slow down


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_MAX_AGE_S = 12 * 3600


def cache_path(host):
    return os.path.join(CACHE_DIR, f"icims-{host}.json")


def fetch(host, deadline_s):
    out, seen = [], set()
    t0 = time.monotonic()
    with ThreadPoolExecutor(BATCH) as ex:
        for start in range(0, MAX_PAGES, BATCH):
            if deadline_s and time.monotonic() - t0 > deadline_s:  # newest jobs come first, so stopping early keeps the freshest
                print(f"icims_jobs: {host} stopped at {deadline_s}s after {start} pages", file=sys.stderr)
                break
            results = list(ex.map(lambda n: page(host, n), range(start, start + BATCH)))
            for jobs in results:
                for j in jobs or []:
                    if j["url"] not in seen:
                        seen.add(j["url"])
                        out.append(j)
            if any(jobs == [] for jobs in results):  # ran past the last page
                break
            if all(jobs is None for jobs in results):  # the whole batch failed: board unreachable, stop
                break
    return out


def host_of(url):
    return re.match(r"https?://([^/]+)", url).group(1)


def save_cache(host, jobs):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = cache_path(host) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs, f)
    os.replace(tmp, cache_path(host))


def main():
    # --prefetch URL...: run by local\daily-scan.ps1 BEFORE scan.mjs, one board at a time with no
    # deadline, so the scan itself (which kills a parser at 20 s) can answer instantly from the cache.
    if sys.argv[1] == "--prefetch":
        for url in sys.argv[2:]:
            host = host_of(url)
            t0 = time.monotonic()
            jobs = fetch(host, deadline_s=None)
            if jobs:
                save_cache(host, jobs)
            print(f"prefetch {host}: {len(jobs)} jobs in {time.monotonic() - t0:.1f}s", file=sys.stderr)
        return
    host = host_of(sys.argv[1])
    path = cache_path(host)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE_S:
        with open(path, encoding="utf-8") as f:
            sys.stdout.write(f.read())
        return
    jobs = fetch(host, deadline_s=DEADLINE_S)  # no fresh cache: live fetch, cut short if the board is slow
    if jobs:
        save_cache(host, jobs)
    json.dump(jobs, sys.stdout)


if __name__ == "__main__":
    main()
