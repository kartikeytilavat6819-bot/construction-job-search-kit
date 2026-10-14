"""career-ops local parser for Jacobs' Avature board, careers.jacobs.com (format: jobs-json-v1).

careers.jacobs.com sits behind AWS WAF, which answers plain scripts with an empty HTTP 202 and a
JavaScript check. A normal (non-stealth) headless Edge simply loads the public search page the way
any browser does, so this renders the board's own filtered search-results page in Edge and reads
the next result pages with that same browser session. Nothing here solves, spoofs or bypasses the
check: if the page does not load normally for the browser, the script fails (non-zero exit).

Why it is filtered: the board shows 10 jobs per page, its RSS feed ignores paging (always the same
20 jobs), and the server answers one request per session at a time (~2 s each), so the ~190 jobs
matching New England cannot be read inside career-ops' 20 s limit. The search therefore uses the
board's own filters -- Country = United States, State/province = MA/CT/RI/NH/VT/ME, Capability =
"Civil and Structural" + "Environmental" (water/wastewater sits under Environmental) -- sorted by
newest job ID first, ~25-30 jobs, 3 pages, ~10-12 s. A deadline stops paging early if the site is
slow, keeping the newest jobs.

  python local/jacobs_avature_jobs.py https://careers.jacobs.com/en_US/careers/SearchJobs
Prints: [{"title", "url", "location", "reqId"}, ...]  (the list carries no posting date)

A "multiple locations" posting lists only its first location (often outside New England); since it
matched the New England state filter, "multiple locations incl. New England" is appended.
"""
import json, re, sys, time
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

COUNTRY_US = 76515
NE_STATES = [1010520, 1010653, 1010617, 1010548, 1010549, 1010656]  # MA, CT, RI, NH, VT, ME
CAPABILITIES = [6770, 6773]  # Civil and Structural, Environmental
PER_PAGE = 10                # the board ignores larger jobRecordsPerPage values
MAX_PAGES = 8
DEADLINE_S = 14              # stop requesting new pages after this (career-ops kills at 20 s)
NE_RE = re.compile(r"Massachusetts|Connecticut|Rhode Island|New Hampshire|Vermont|Maine")


def ids(values):
    return quote(json.dumps(values, separators=(",", ":")))


def query(offset):
    return (f"?4182={ids([COUNTRY_US])}&4182_format=4422&4185={ids(NE_STATES)}&4185_format=4425"
            f"&575={ids(CAPABILITIES)}&listFilterMode=1&jobRecordsPerPage={PER_PAGE}&jobOffset={offset}"
            "&jobSort=jobId&jobSortDirection=DESC")


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    total = re.search(r"of\s+([\d,]+)\s", soup.get_text(" "))
    jobs = []
    for art in soup.select("article.article--result"):
        a = art.select_one(".article__header__text__title a[href]")
        if not a:
            continue
        loc_el, req = art.select_one(".list-item-location"), art.select_one(".list-item-jobId")
        loc = loc_el.get_text(" ", strip=True) if loc_el else ""
        if art.select_one(".list-item-multipleLocations") and not NE_RE.search(loc):
            loc = f"{loc}; multiple locations incl. New England" if loc else "Multiple locations incl. New England"
        job = {"title": re.sub(r"\s*\(\d+\)$", "", a.get_text(" ", strip=True)), "url": a["href"], "location": loc}
        if req:
            job["reqId"] = req.get_text(strip=True)
        jobs.append(job)
    return jobs, int(total.group(1).replace(",", "")) if total else None


def main():
    t0 = time.time()
    u = urlparse(sys.argv[1])
    base = f"https://{u.netloc}/en_US/careers/SearchJobs/"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        try:
            ctx = browser.new_context()
            page = ctx.new_page()
            # images/fonts are not needed to read the list
            page.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "font", "media") else r.continue_())
            page.goto(base + query(0), wait_until="domcontentloaded", timeout=15000)
            page.wait_for_selector("#tpt_jobSortableForm", timeout=12000)  # the real page has loaded
            jobs, total = parse(page.content())
            n = 1
            while total and n * PER_PAGE < total and n < MAX_PAGES and time.time() - t0 < DEADLINE_S:
                r = ctx.request.get(base + query(n * PER_PAGE), timeout=8000)
                if not r.ok:
                    break
                more, _ = parse(r.text())
                if not more:
                    break
                jobs += more
                n += 1
        finally:
            browser.close()
    out, seen = [], set()
    for j in jobs:
        if j["url"] not in seen:
            seen.add(j["url"])
            out.append(j)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
