"""Zero-token sponsorship pre-screen for the top-ranked pending jobs (run after local/rank_pipeline.py).

For each of the first N "- [ ]" rows in data/pipeline.md (already in rank order) it:
  1. fetches the full JD text with career-ops' headless reader (node browser-extract.mjs --mode jd);
     iCIMS postings use their static ?in_iframe=1 page,
  2. saves it to jds/screen-<slug>.md (reused by the evaluations so they never hit "JD unavailable"),
  3. classifies sponsorship: REFUSES (no sponsorship / citizens only / clearance) | SPONSORS | SILENT | NO_JD.
Writes data/sponsor-screen.json + data/sponsor-screen.md. No AI calls.

  python local/sponsor_screen.py [--top 60] [--workers 4]
"""
import argparse, hashlib, json, os, re, subprocess
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.md")
JDS = os.path.join(ROOT, "jds")
OUT_JSON = os.path.join(ROOT, "data", "sponsor-screen.json")
OUT_MD = os.path.join(ROOT, "data", "sponsor-screen.md")

REFUSE = re.compile(
    r"(not|unable to|cannot|can't|won't|will not|does not|do not)\s+(be\s+)?(able\s+to\s+)?(offer|provide|support|sponsor)\w*[^.]{0,60}sponsor"
    r"|sponsorship\s+(is\s+)?(not|un)\s*(be\s+)?(available|offered|provided|possible)"
    r"|no\s+(visa\s+|immigration\s+|h-?1b\s+)?sponsorship"
    r"|without\s+(the\s+need\s+for\s+)?(current\s+or\s+future\s+|future\s+)?(visa\s+|employer\s+|employment\s+)?sponsorship"
    r"|(now\s+or\s+in\s+the\s+future)[^.]{0,80}sponsor|sponsor[^.]{0,80}(now\s+or\s+in\s+the\s+future)"
    r"|u\.?s\.?\s+citizens?\s+(only|required)|must\s+be\s+a\s+u\.?s\.?\s+citizen|united\s+states\s+citizenship\s+(is\s+)?required"
    r"|permanent\s+residents?\s+only|green\s+card\s+holders?\s+only"
    r"|sponsorship\s+available\s*[:\-?]?\s*(no\b|none\b|n/a\b)"   # CDM Smith / B&V form field "Visa Sponsorship Available: No"
    r"|(will\s+not|won't|cannot|can\s*not|unable\s+to|does\s+not|do\s+not|not\s+able\s+to)\s+sponsor\b"   # Dewberry: "will not sponsor a new applicant"
    r"|u\.?s\.?\s+citizens?\s+(and|or|&)\s+(lawful\s+)?permanent\s+residents?"                           # Skanska: "U.S. citizens and permanent residents only"
    r"|(us|u\.s\.)\s+citizenship\s+(is\s+)?required|requires?\s+(u\.?s\.?\s+)?citizenship"
    r"|(security|secret|public\s+trust)\s+clearance\s+(is\s+)?(required|needed)|(active|current)\s+(secret|ts/sci|top\s+secret)",
    re.I)
SPONSOR = re.compile(r"(will|can|does|may)\s+(provide|offer|consider|support)\s+(visa\s+|h-?1b\s+)?sponsorship"
                     r"|sponsorship\s+(is\s+)?available(?!\s*[:\-?]?\s*(no|none|n/a)\b)"   # not the "Available: No" form field
                     r"|h-?1b\s+(transfer|sponsorship)\s+(available|considered|supported)", re.I)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def jd_url(url):
    if ".icims.com/jobs/" in url and "in_iframe=1" not in url:
        return url + ("&" if "?" in url else "?") + "in_iframe=1"
    return url


def fetch_jd(url):
    try:
        p = subprocess.run(["node", "browser-extract.mjs", jd_url(url), "--mode", "jd", "--max-chars", "20000", "--timeout", "45000"],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        data = json.loads(p.stdout or "{}")
        return (data.get("text") or "").strip(), data.get("title") or ""
    except Exception as e:  # timeouts, bot walls, bad JSON
        return "", f"error: {e}"[:80]


def fetch_static(url):
    """Plain HTTP fallback: some iCIMS tenants' in_iframe page is static HTML the headless reader trims away."""
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(jd_url(url), headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"}, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            t.decompose()
        main = soup.select_one(".iCIMS_JobContent, .iCIMS_InfoMsg_Job, #jobDescriptionText, main, article") or soup.body or soup
        return re.sub(r"\s+\n", "\n", main.get_text("\n", strip=True))
    except Exception:
        return ""


BOT_WALL = re.compile(r"verify (that )?you are (a )?human|are you a robot|captcha|access denied|enable javascript|checking your browser", re.I)
JD_SIGNAL = re.compile(r"responsibilit|qualification|requirement|experience|degree|you will|duties|skills", re.I)


def looks_like_jd(text):
    """Real posting text, not a bot wall or bare site chrome (headers/footers can exceed 80 words)."""
    return len(text.split()) >= 80 and not BOT_WALL.search(text[:2000]) and len(JD_SIGNAL.findall(text)) >= 3


def screen(row):
    url, company, title, line = row
    if ".icims.com/jobs/" in url:  # iCIMS: the static in_iframe page gets through where the headless reader hits a bot wall
        text, page_title = fetch_static(url), ""
        if not looks_like_jd(text):
            text, page_title = fetch_jd(url)
    else:
        text, page_title = fetch_jd(url)
        if not looks_like_jd(text):
            static = fetch_static(url)
            if looks_like_jd(static):
                text = static
    words = len(text.split())
    if not looks_like_jd(text):
        verdict, evidence = "NO_JD", page_title or "description not readable"
    else:
        m = REFUSE.search(text)
        s = SPONSOR.search(text)
        if m:
            verdict, evidence = "REFUSES", text[max(0, m.start() - 60): m.end() + 60].replace("\n", " ")
        elif s:
            verdict, evidence = "SPONSORS", text[max(0, s.start() - 60): s.end() + 60].replace("\n", " ")
        else:
            verdict, evidence = "SILENT", "no sponsorship wording in the JD"
    jd_file = None
    if verdict != "NO_JD":
        os.makedirs(JDS, exist_ok=True)
        # url hash in the name: the same title is often posted for several offices (HNTB, Clark...)
        jd_file = os.path.join("jds", f"screen-{slug(company)}-{slug(title)[:40]}-{hashlib.sha1(url.encode()).hexdigest()[:8]}.md")
        with open(os.path.join(ROOT, jd_file), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# {company} - {title}\n\nSource URL: {url}\n\n{text}\n")
    return dict(url=url, company=company, title=title, verdict=verdict, evidence=evidence.strip()[:240],
                words=words, jd_file=jd_file, line=line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    rows = []
    for l in open(PIPE, encoding="utf-8").read().splitlines():
        if l.startswith("- [ ]"):
            parts = [p.strip() for p in l[6:].split("|")]
            rows.append((parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "", l))
            if len(rows) >= a.top:
                break
    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(screen, rows))
    json.dump(results, open(OUT_JSON, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    order = {"SPONSORS": 0, "SILENT": 1, "NO_JD": 2, "REFUSES": 3}
    md = ["# Sponsorship pre-screen (zero-token)", "",
          "REFUSES = the JD says no sponsorship / citizens only / clearance. SILENT = no wording either way "
          "(apply, ask the recruiter). NO_JD = description not readable automatically.", "",
          "| Verdict | Company | Title | Evidence |", "|---|---|---|---|"]
    md += [f"| {r['verdict']} | {r['company']} | [{r['title']}]({r['url']}) | {r['evidence'].replace('|', '/')} |"
           for r in sorted(results, key=lambda r: order[r["verdict"]])]
    open(OUT_MD, "w", encoding="utf-8", newline="\n").write("\n".join(md) + "\n")
    counts = {k: sum(r["verdict"] == k for r in results) for k in order}
    print("screened", len(results), "jobs:", ", ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
