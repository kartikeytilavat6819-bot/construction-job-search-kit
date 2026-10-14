"""career-ops local parser for ApplicantPro / isolved Talent Acquisition boards (format: jobs-json-v1).

<sub>.applicantpro.com/jobs/ renders its list client-side (Vue JobListings component) from
GET https://<sub>.applicantpro.com/core/jobs/<domainId>?getParams=<json>. The board page embeds
domainId and the getParams object, so this reads them from the page and calls that endpoint:
two requests per run. Each job carries jobLocation ("Chelsea, MA, United States") and a
startDateRef ("Oct 06, 2026") posting date.

  python local/applicantpro_jobs.py https://mwra.applicantpro.com/jobs/
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import datetime as dt, json, re, sys
from urllib.parse import urlparse
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def embedded_json(text, key):
    m = re.search(rf"\b{key}\s*:\s*(?=[{{\d\"])", text)
    if not m:
        return None
    return json.JSONDecoder().raw_decode(text, m.end())[0]


def location(job):
    loc = (job.get("jobLocation") or "").strip()
    if not loc:
        loc = ", ".join(p for p in (job.get("city"), job.get("abbreviation")) if p)
    loc = re.sub(r",\s*United States(,\s*[\d-]+)?$", "", loc)  # "..., MA, United States, 01745"
    wt = (job.get("workplaceType") or "").strip()
    if wt and "remote" in wt.lower():
        loc = f"{loc} ({wt})" if loc else wt
    return loc


def main():
    board = sys.argv[1]
    host = urlparse(board).netloc
    s = requests.Session()
    s.headers.update(UA)
    r = s.get(f"https://{host}/jobs/", timeout=10)
    r.raise_for_status()
    domain_id = embedded_json(r.text, "domainId")
    if domain_id is None:
        m = re.search(r'"domain_id"\s*:\s*"(\d+)"', r.text)
        domain_id = m and m.group(1)
    if not domain_id:
        raise SystemExit("applicantpro: domainId not found on board page")
    params = embedded_json(r.text, "getParams") or {}
    params["isInternal"] = 0
    api = s.get(f"https://{host}/core/jobs/{domain_id}", params={"getParams": json.dumps(params)},
                headers={"Accept": "application/json"}, timeout=10)
    api.raise_for_status()
    payload = api.json()
    if not payload.get("success"):
        raise SystemExit(f"applicantpro: API error: {payload.get('message')}")
    out = []
    for job in (payload.get("data") or {}).get("jobs") or []:
        if not job.get("title"):
            continue
        row = {"title": job["title"].strip(),
               "url": job.get("jobUrl") or f"https://{host}/jobs/{job['id']}",
               "location": location(job)}
        try:
            row["postedAt"] = dt.datetime.strptime(job.get("startDateRef") or "", "%b %d, %Y").date().isoformat()
        except ValueError:
            pass
        out.append(row)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
