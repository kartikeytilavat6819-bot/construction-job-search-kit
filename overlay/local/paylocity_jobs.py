"""career-ops local parser for Paylocity recruiting boards (format: jobs-json-v1).

A Paylocity board (recruiting.paylocity.com/recruiting/jobs/All/<guid>/<name>, or the older
/jobs/List/<moduleId>/<name> form, which redirects) is a single server-rendered page whose
window.pageData object already holds every posting with its location and publish date, so one
request is enough.

  python local/paylocity_jobs.py https://recruiting.paylocity.com/recruiting/jobs/All/<guid>/BETA-GROUP-INC
Prints: [{"title", "url", "location", "postedAt"?}, ...]
"""
import json, re, sys
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
DETAILS = "https://recruiting.paylocity.com/Recruiting/Jobs/Details/"


def location(job):
    loc = job.get("JobLocation") or {}
    city, state = (loc.get("City") or "").strip(), (loc.get("State") or "").strip()
    # LocationName is a free-text label ("Norwood - MA", but also bare "Silver Spring"), so
    # prefer the structured city/state, then Metro ("Gaithersburg, MD"), then the label.
    if city:
        text = f"{city}, {state}" if state else city
    else:
        text = (loc.get("Metro") or job.get("LocationName") or loc.get("Name") or state or "").strip()
    if job.get("IsRemote"):
        text = f"{text} (Remote)" if text else "Remote"
    return text


def main():
    r = requests.get(sys.argv[1], headers=UA, timeout=15)
    r.raise_for_status()
    m = re.search(r"window\.pageData\s*=\s*(\{.*?\});\s*\n", r.text, re.S)
    if not m:
        raise SystemExit("paylocity: window.pageData not found")
    out = []
    for job in json.loads(m.group(1)).get("Jobs") or []:
        if job.get("IsInternal") or not job.get("JobId") or not job.get("JobTitle"):
            continue
        row = {"title": job["JobTitle"].strip(),
               "url": f"{DETAILS}{job['JobId']}",
               "location": location(job)}
        if job.get("PublishedDate"):
            row["postedAt"] = job["PublishedDate"]
        out.append(row)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
