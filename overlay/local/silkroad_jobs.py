"""career-ops local parser for SilkRoad Recruiting boards (jobs.silkroad.com) (format: jobs-json-v1).

A SilkRoad board (jobs.silkroad.com/<Tenant>/Careers) is server-rendered, 10 postings per page,
and shows only a posting's first office ("Harrisburg, PA (+4 more locations)"). Its own location
filter (SelectedLocations=US|US-MA) does match every office, so, like directemployers_jobs.py, this
runs one filtered search per New England state found in the board's location list (pages fetched
in parallel) and appends the searched state to any row whose shown office lies elsewhere.

  python local/silkroad_jobs.py https://jobs.silkroad.com/WhitingTurner/Careers
  python local/silkroad_jobs.py "https://jobs.silkroad.com/WhitingTurner/Careers?SelectedLocations=US|US-NY"   # custom filter
Prints: [{"title", "url", "location"}, ...]
"""
import html, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
NEW_ENGLAND = {"MA": "Massachusetts", "CT": "Connecticut", "RI": "Rhode Island", "NH": "New Hampshire",
               "VT": "Vermont", "ME": "Maine"}
MAX_PAGES = 30
CARD = re.compile(r'<a id="Jobs_PagedJobList_Job-(\d+)"[^>]*>.*?JobTitle-\1">\s*(.*?)\s*</div>'
                  r'(?:.*?<span class="sr-panel__meta">\s*([^<]*?)\s*</span>)?.*?</a>', re.S)


def get(board, params, page=1):
    r = requests.get(board, params={"embedded": "true", **params, "page": page}, headers=UA, timeout=15)
    r.raise_for_status()
    return r.text


def cards(text):
    return [(jid, html.unescape(re.sub(r"\s+", " ", title)), html.unescape(loc or "").strip())
            for jid, title, loc in CARD.findall(text)]


def search(board, params):
    first = get(board, params)
    rows = cards(first)
    m = re.search(r"Page \d+ of (\d+)", first)
    last = min(int(m.group(1)), MAX_PAGES) if m else 1
    if last > 1:
        with ThreadPoolExecutor(8) as ex:
            for text in ex.map(lambda n: get(board, params, n), range(2, last + 1)):
                rows.extend(cards(text))
    return rows, first


def main():
    u = urlparse(sys.argv[1])
    board = f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"
    board = re.sub(r"/jobs$", "", board)
    custom = parse_qs(u.query).get("SelectedLocations")
    out, by_id = [], {}

    def add(rows, label=None):
        for jid, title, loc in rows:
            if jid in by_id:
                if label and label not in by_id[jid]["location"]:
                    by_id[jid]["location"] += f"; {label}"
                continue
            if label:  # shown office is in another state: name the searched one too
                st = next(k for k, v in NEW_ENGLAND.items() if v == label)
                if not re.search(rf",\s*{st}\b", loc):
                    loc = f"{loc}; {label}" if loc else label
            by_id[jid] = {"title": title, "url": f"{board}/jobs/{jid}", "location": loc}
            out.append(by_id[jid])

    if custom:
        add(search(board, {"SelectedLocations": custom[0]})[0])
    else:
        home = get(board, {})
        sel = home[home.find('name="SelectedLocations"'):]
        sel = sel[:sel.find("</select>")]
        states = [v for v in re.findall(r'<option[^>]*value="([^"]+)"', sel)
                  if re.fullmatch(r"US\|US-(MA|CT|RI|NH|VT|ME)", v)]
        with ThreadPoolExecutor(max(1, len(states))) as ex:
            for st, (rows, _) in zip(states, ex.map(lambda v: search(board, {"SelectedLocations": v}), states)):
                add(rows, NEW_ENGLAND[st[-2:]])
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
