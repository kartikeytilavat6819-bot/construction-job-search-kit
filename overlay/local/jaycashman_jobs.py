"""career-ops local parser for Jay Cashman, Inc. / Cashman Dredging & Marine (format: jobs-json-v1).

jaycashman.com/careers/ is a server-rendered page listing every open position, grouped by company
(Cashman Dredging & Marine, IPC Lydon, ...), each as an <a href="/careers/<id>/"> card with a title
and city. No ATS behind it, so one request is enough.

  python local/jaycashman_jobs.py https://www.jaycashman.com/careers/
Prints: [{"title", "url", "location"}, ...]
"""
import json, sys
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.jaycashman.com/careers/"
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    out, seen = [], set()
    for card in BeautifulSoup(r.text, "html.parser").select("div.open-position"):
        a = card.find_parent("a", href=True)
        title = card.select_one(".open-position-title")
        if not a or not title:
            continue
        href = urljoin(r.url, a["href"])
        if href in seen:
            continue
        seen.add(href)
        city = card.select_one(".open-position-city")
        out.append({"title": title.get_text(" ", strip=True), "url": href,
                    "location": city.get_text(" ", strip=True) if city else ""})
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
