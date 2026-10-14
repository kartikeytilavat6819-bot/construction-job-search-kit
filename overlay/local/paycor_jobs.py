"""career-ops local parser for Paycor Recruiting (Newton) boards (format: jobs-json-v1).

recruitingbypaycor.com/career/CareerHome.action?clientId=<id> is server-rendered: every opening
is a .gnewtonCareerGroupRowClass row (title link + location line) under a group header, all on
one page, so one request is enough. The board shows no posting date.

  python local/paycor_jobs.py "https://recruitingbypaycor.com/career/CareerHome.action?clientId=<id>"
Prints: [{"title", "url", "location"}, ...]
"""
import json, re, sys
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def main():
    url = sys.argv[1]
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out, seen, header = [], set(), ""
    # Walk headers and rows in document order so a row can fall back to its group header.
    for el in soup.select(".gnewtonCareerGroupHeaderClass, .gnewtonCareerGroupRowClass"):
        if "gnewtonCareerGroupHeaderClass" in el.get("class", []):
            header = el.get_text(" ", strip=True)
            continue
        a = el.select_one(".gnewtonCareerGroupJobTitleClass a[href]")
        if not a:
            continue
        link = re.sub(r"&source=(?=&|$)", "", urljoin(r.url, a["href"]))
        if link in seen:
            continue
        seen.add(link)
        desc = el.select_one(".gnewtonCareerGroupJobDescriptionClass")
        loc = re.sub(r"\s+", " ", desc.get_text(" ", strip=True)) if desc else ""
        # The group header is normally the department; it is only a location when the row line is
        # blank (a tenant grouping by location), so fall back to it only then.
        out.append({"title": a.get_text(" ", strip=True), "url": link, "location": loc or header})
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
