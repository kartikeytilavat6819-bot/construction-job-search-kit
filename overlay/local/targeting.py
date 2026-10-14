"""Job targeting for the local scripts: reads config/targeting.yml and turns it into ready-made regexes.

Every "what kind of job is a fit" decision in local/ (sieve.py, ollama_triage.py, rank_pipeline.py,
rule_prefilter.py, untriaged_queue.py, second_opinion.py, sieve_eval_queue.py ...) comes from here, so the
same scripts work for any field: edit config/targeting.yml, not the Python files.

  python local/targeting.py                 # print what was loaded (a quick sanity check after editing the YAML)
  python local/targeting.py "Assistant Project Manager" "Senior Estimator"   # test how titles are judged

Keyword lists in the YAML are plain words or phrases, matched case-insensitively as whole words:
  "project engineer"  matches "Project Engineer", "project-engineer", "PROJECT  ENGINEER"
  "recruit*"          a trailing * means "any ending": recruit, recruiter, recruiting
  "re:<regex>"        advanced: a raw Python regular expression

Environment overrides (for testing): CAREER_OPS_TARGETING=<path to a targeting.yml>.
PyYAML is used when installed; otherwise a small built-in reader handles the simple YAML this file needs.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.environ.get("CAREER_OPS_TARGETING") or os.path.join(ROOT, "config", "targeting.yml")


# ── tiny YAML reader (fallback when PyYAML is not installed) ─────────────────────────────────────────────────
def _opens_quote(s, i):
    """A quote only starts a quoted string at the start of a value (so "owner's rep" stays plain text)."""
    return s[i] in "\"'" and (i == 0 or s[i - 1] in " \t[{,:-")


def _strip_comment(line):
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif _opens_quote(line, i):
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(s):
    s = s.strip()
    if not s:
        return None
    if s[0] == '"' and s.endswith('"') and len(s) >= 2:
        return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s[1:-1])
    if s[0] == "'" and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s[0] == "[" and s.endswith("]"):
        return [_scalar(x) for x in _split_flow(s[1:-1]) if x.strip()]
    if s[0] == "{" and s.endswith("}"):
        d = {}
        for part in _split_flow(s[1:-1]):
            if part.strip():
                k, v = _split_key(part)
                d[k] = _scalar(v)
        return d
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _split_flow(s):
    parts, cur, q, depth = [], [], None, 0
    for i, ch in enumerate(s):
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if _opens_quote(s, i):
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts


def _split_key(text):
    """'key: value' -> (key, value). Keys may be quoted (and then contain ':' or '|')."""
    t = text.strip()
    if t[:1] in "\"'":
        q = t[0]
        end = t.index(q, 1)
        key, rest = t[1:end], t[end + 1:].lstrip()
        if not rest.startswith(":"):
            raise ValueError(f"expected ':' after the key in: {text.strip()}")
        return key, rest[1:]
    m = re.match(r"^([^:]+?)\s*:(\s|$)(.*)$", t)
    if not m:
        raise ValueError(f"expected 'key: value' in: {text.strip()}")
    return m.group(1).strip(), m.group(3)


def mini_yaml(text):
    lines, pending = [], None
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError(f"line {n}: use spaces, not tabs, to indent")
        line = _strip_comment(raw)
        if pending is not None:  # a [ ... ] list that continues over several lines
            pending = (pending[0], pending[1] + " " + line.strip(), pending[2])
        elif line.strip() and line.strip() != "---":
            pending = (len(line) - len(line.lstrip()), line.strip(), n)
        else:
            continue
        depth = sum(pending[1].count(c) for c in "[{") - sum(pending[1].count(c) for c in "]}")
        if depth <= 0:
            lines.append(pending)
            pending = None
    if pending is not None:
        raise ValueError(f"line {pending[2]}: a [ list ] is never closed with ]")

    def block(i, indent):
        if i >= len(lines):
            return None, i
        if lines[i][1].startswith("- ") or lines[i][1] == "-":
            out = []
            while i < len(lines) and lines[i][0] == indent and (lines[i][1].startswith("- ") or lines[i][1] == "-"):
                item = lines[i][1][1:].strip()
                if not item:
                    val, i = block(i + 1, lines[i + 1][0]) if i + 1 < len(lines) and lines[i + 1][0] > indent else (None, i + 1)
                    out.append(val)
                    continue
                if re.match(r"^(\"[^\"]*\"|'[^']*'|[^\"'\[{][^:]*?)\s*:(\s|$)", item):
                    # "- key: value" starts a mapping inside the list
                    sub = [" " * (indent + 2) + item]
                    j = i + 1
                    while j < len(lines) and lines[j][0] > indent:
                        sub.append(" " * lines[j][0] + lines[j][1])
                        j += 1
                    out.append(mini_yaml("\n".join(sub)))
                    i = j
                    continue
                out.append(_scalar(item))
                i += 1
            return out, i
        out = {}
        while i < len(lines) and lines[i][0] == indent:
            key, rest = _split_key(lines[i][1])
            rest = rest.strip()
            if rest in ("|", ">", "|-", ">-"):
                j, buf = i + 1, []
                while j < len(lines) and lines[j][0] > indent:
                    buf.append(lines[j][1])
                    j += 1
                out[key] = ("\n" if rest.startswith("|") else " ").join(buf)
                i = j
            elif rest:
                out[key] = _scalar(rest)
                i += 1
            elif i + 1 < len(lines) and lines[i + 1][0] > indent:
                out[key], i = block(i + 1, lines[i + 1][0])
            elif i + 1 < len(lines) and lines[i + 1][0] == indent and lines[i + 1][1].startswith("- "):
                out[key], i = block(i + 1, indent)  # list items at the same indent as their key
            else:
                out[key] = None
                i += 1
        if i < len(lines) and lines[i][0] > indent:
            raise ValueError(f"line {lines[i][2]}: unexpected indentation")
        return out, i

    val, i = block(0, lines[0][0]) if lines else ({}, 0)
    if i < len(lines):
        raise ValueError(f"line {lines[i][2]}: could not read this line (check its indentation)")
    return val


def load_yaml(path):
    text = open(path, encoding="utf-8-sig").read()
    try:
        import yaml  # PyYAML, when installed
        return yaml.safe_load(text) or {}
    except ImportError:
        return mini_yaml(text) or {}


# ── keyword lists -> regexes ──────────────────────────────────────────────────────────────────────────────────
NEVER = re.compile(r"(?!x)x")


def _one(word):
    w = str(word).strip()
    if not w:
        return None
    if w.startswith("re:"):
        return w[3:].strip()
    star = w.endswith("*")
    core = w.rstrip("*").strip()
    p = r"[\s\-]+".join(re.escape(t) for t in core.split())
    if star:
        p += r"\w*"
    if re.match(r"\w", core):
        p = r"\b" + p
    if star or re.search(r"\w$", core):
        p += r"\b"
    return p


def kw_pattern(words):
    parts = [p for p in (_one(w) for w in (words or [])) if p]
    return "(?:" + "|".join(parts) + ")" if parts else None


def kw_regex(words, flags=re.I):
    p = kw_pattern(words)
    return re.compile(p, flags) if p else NEVER


def _norm(s):
    return re.sub(r"[\s\-]+", " ", (s or "").strip().lower())


# ── load ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _get(d, path, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur or cur[k] is None:
            return default
        cur = cur[k]
    return cur


def _list(d, path):
    v = _get(d, path, [])
    if isinstance(v, str):
        return [v]
    return [x for x in (v or []) if x is not None and str(x).strip()]


if os.path.exists(CONFIG):
    CFG = load_yaml(CONFIG)
else:
    CFG = {}
    print(f"[targeting] {CONFIG} not found: using empty targeting (copy templates/config/targeting.yml there)",
          file=sys.stderr)

# Field / AI wording
FIELD = _get(CFG, "field", "the candidate's field")
EMPLOYER = _get(CFG, "ai.employer", "a US employer in the candidate's field")
GRADUATION = str(_get(CFG, "candidate.graduation", "") or "")
WORK_AUTH = _get(CFG, "candidate.work_authorization",
                 "on F-1 OPT; will need H-1B sponsorship later")

# Location
STATE_CODES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
               "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
STATE_NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
               "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
               "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
               "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
               "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
               "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
               "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
               "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
               "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
               "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"}

METRO_LABEL = _get(CFG, "location.home_metro.label", "Home metro")
METRO_TOWNS = _list(CFG, "location.home_metro.towns")
METRO = kw_regex(METRO_TOWNS)
STATE_CODE = str(_get(CFG, "location.home_state.code", "") or "").upper().strip()
STATE_NAME = _get(CFG, "location.home_state.name", STATE_NAMES.get(STATE_CODE, "")) or ""
STATE_LABEL = STATE_NAME or "Home state"
if STATE_CODE:
    # the 2-letter code is matched case-sensitively ("ME", "IN", "OR" must never match the words me/in/or)
    STATE = re.compile(rf"\b{STATE_CODE}\b|US-{STATE_CODE}-" + (rf"|(?i:{re.escape(STATE_NAME)})" if STATE_NAME else ""))
    STATE_I = re.compile(rf"{re.escape(STATE_NAME)}|,\s*{STATE_CODE}\b|-{STATE_CODE}-|\.{STATE_CODE}\.|\b{STATE_CODE}\b"
                         if STATE_NAME else rf",\s*{STATE_CODE}\b|-{STATE_CODE}-|\b{STATE_CODE}\b", re.I)
else:
    STATE = STATE_I = NEVER
REGION_LABEL = _get(CFG, "location.region.label", "Region")
REGION_CODES = [str(c).upper().strip() for c in _list(CFG, "location.region.states") if str(c).strip()]
REGION_NAMES = [STATE_NAMES[c] for c in REGION_CODES if c in STATE_NAMES]
if REGION_CODES:
    _codes = "|".join(REGION_CODES)
    _names = "|".join(re.escape(n) for n in REGION_NAMES)
    # case-sensitive codes, case-insensitive names (written as [Mm]aine style via (?i:...))
    REGION = re.compile(rf"\b({_codes})\b" + (rf"|(?i:\b({_names})\b)" if _names else ""))
    REGION_I = re.compile((rf"\b({_names})\b|" if _names else "") + re.escape(REGION_LABEL) +
                          rf"|,\s*({_codes})\b|-({_codes})-|\.({_codes})\.", re.I)
else:
    REGION = REGION_I = NEVER

_S = _get(CFG, "location.scores", {}) or {}
LOC_SCORES = {
    METRO_LABEL: float(_S.get("home_metro", 5.0)),
    STATE_LABEL: float(_S.get("home_state", 4.6)),
    REGION_LABEL: float(_S.get("region", 4.4)),
    "Other US": float(_S.get("other_us", 4.0)),
    "Unknown": float(_S.get("unknown", 3.8)),
    "Remote": float(_S.get("remote", 3.0)),
    "Outside US": 1.0,
}
HOME_LABELS = {METRO_LABEL, STATE_LABEL, REGION_LABEL}


def loc_rank(label):
    """Queue order for a location tier: home metro / home state first, then the region, other US, remote."""
    return {METRO_LABEL: 0, STATE_LABEL: 0, REGION_LABEL: 1, "Other US": 2, "Unknown": 3, "Remote": 4}.get(label, 3)


# Companies
PRIORITY_COMPANIES = _list(CFG, "priority_companies")
PRIORITY = kw_regex(PRIORITY_COMPANIES)
PUBLIC_AGENCY = kw_regex(_list(CFG, "public_agency_words") or ["commonwealth of", "city of", "town of", "county of"])

# Titles
TITLE_ENTRY = kw_regex(_list(CFG, "titles.entry_signals"))
TITLE_TARGET = kw_regex(_list(CFG, "titles.target"))
TITLE_STRETCH = kw_regex(_list(CFG, "titles.stretch"))
_senior = _list(CFG, "titles.too_senior")
TITLE_LEVEL_2PLUS = bool(_get(CFG, "titles.reject_level_2_plus", True))
_LEVEL = (r"\b(?:ii|iii|iv)\b(?=\s*(?:$|[-,(/|–]))|\blevel\s+(?:ii|iii|iv|2|3|4)\b|"
          r"\b(?:engineer|estimator|scheduler|coordinator|inspector|superintendent|manager|specialist|analyst)\s+(?:2|3|4)\b")
TITLE_SENIOR = re.compile("|".join(p for p in (kw_pattern(_senior), _LEVEL if TITLE_LEVEL_2PLUS else None) if p) or NEVER.pattern, re.I)
TITLE_SENIOR_FORGIVEN = kw_regex(_list(CFG, "titles.senior_ok_with_entry_signal"))
TITLE_OFF_DISCIPLINE = kw_regex(_list(CFG, "titles.off_discipline"))
TITLE_EXCLUDE = kw_regex(_list(CFG, "titles.exclude"))
TITLE_EXCLUDE_RESCUE = kw_regex(_list(CFG, "titles.exclude_unless"))
TITLE_TOO_JUNIOR = kw_regex(_list(CFG, "titles.too_junior"))
TITLE_TOO_JUNIOR_KEEP = kw_regex(_list(CFG, "titles.too_junior_keep_if"))
TITLE_TOO_JUNIOR_NEVER = kw_regex(_list(CFG, "titles.too_junior_never_keep"))


def title_dq(title):
    """Seniority / off-discipline words in the title (the hard 'title says X' rule). Returns a reason or None."""
    t = title or ""
    m = TITLE_OFF_DISCIPLINE.search(t)
    if m:
        return f"title says '{m.group(0)}'"
    entry = bool(TITLE_ENTRY.search(t))
    for m in TITLE_SENIOR.finditer(t):
        if entry and TITLE_SENIOR_FORGIVEN.fullmatch(m.group(0).strip()):
            continue  # "Assistant Project Manager": "project manager" is forgiven because "assistant" is there
        return f"title says '{m.group(0).strip()}'"
    return None


def title_reject(title):
    """Every title-only rule the sieve applies at S1. Returns a reason or None."""
    t = title or ""
    why = title_dq(t)
    if why:
        return why
    m = TITLE_TOO_JUNIOR.search(t)
    if m and not (TITLE_TOO_JUNIOR_KEEP.search(t) and not TITLE_TOO_JUNIOR_NEVER.search(t)):
        return f"technician / support-level title ('{m.group(0)}')"
    m = TITLE_EXCLUDE.search(t)
    if m and not TITLE_EXCLUDE_RESCUE.search(t):
        return f"off-target occupation in the title ('{m.group(0)}')"
    return None


# Posting text (JD) signals
def _skills():
    out = []
    raw = _get(CFG, "skills", {}) or {}
    items = raw.items() if isinstance(raw, dict) else [(x, 1.0) for x in raw]
    for terms, w in items:
        words = [x.strip() for x in re.split(r"[|,]", str(terms)) if x.strip()]
        p = kw_pattern(words)
        if p:
            try:
                out.append((p, float(w if w is not None else 1.0)))
            except (TypeError, ValueError):
                out.append((p, 1.0))
    return out


SKILLS = _skills()  # [(regex pattern, weight)]
JD_ON_TARGET = kw_regex(_list(CFG, "jd.on_target_terms"))
JD_OFF_TARGET = kw_regex(_list(CFG, "jd.off_target_terms"))
JD_ENTRY_EXTRA = kw_pattern(_list(CFG, "jd.entry_terms"))
JD_PENALTY = kw_regex(_list(CFG, "jd.penalty.terms"))
JD_PENALTY_MIN = int(_get(CFG, "jd.penalty.min_hits", 2))
JD_PENALTY_POINTS = float(_get(CFG, "jd.penalty.points", 0.8))
JD_PENALTY_NOTE = _get(CFG, "jd.penalty.note", "off-target work in the posting")
DEGREE_FIELDS = _list(CFG, "jd.degree_fields") or ["engineering"]

# Hard rules
MAX_YEARS = int(_get(CFG, "rules.max_years_required", 2))
PE_BLOCKER = bool(_get(CFG, "rules.pe_license_required_is_blocker", True))

# Model categories ("disciplines") for the optional AI stages S5-S7
DISC_TARGET = [str(x) for x in _list(CFG, "disciplines.target")] or ["target_work"]
DISC_NEUTRAL = [str(x) for x in _list(CFG, "disciplines.neutral")]
DISC_OFF = [str(x) for x in _list(CFG, "disciplines.off_target")]
DISCIPLINES = list(dict.fromkeys(DISC_TARGET + DISC_NEUTRAL + DISC_OFF + ["other"]))

# Sieve thresholds
GOLD_AT = float(_get(CFG, "scoring.gold_at", 4.0))
SILVER_AT = float(_get(CFG, "scoring.silver_at", 3.3))
RULES_GOLD_AT = float(_get(CFG, "scoring.rules_only_gold_at", 3.9))
RULES_SILVER_AT = float(_get(CFG, "scoring.rules_only_silver_at", 3.0))

# AI prompt wording
AI_ENTRY_TITLES = _get(CFG, "ai.entry_level_titles", ", ".join(_list(CFG, "titles.target")[:8]))
AI_OFF_TARGET_WORK = _get(CFG, "ai.off_target_work", "a different field or occupation")
AI_DISCIPLINE_HINTS = _get(CFG, "ai.discipline_hints", "")
AI_DEGREE_NOTE = _get(CFG, "ai.degree_note", "the candidate's degree counts for any closely related field")
AI_LEARNABLE_SOFTWARE = ", ".join(str(x) for x in _list(CFG, "ai.learnable_software")) or "industry software"
AI_OBTAINABLE_CERTS = ", ".join(str(x) for x in _list(CFG, "ai.obtainable_certifications")) or "certifications"
AI_RED_FLAGS = _get(CFG, "ai.red_flags", "level II or 2+ years preferred; a must-have skill the candidate lacks")


def summary():
    print(f"targeting file : {CONFIG}{'' if os.path.exists(CONFIG) else '  (MISSING)'}")
    print(f"field          : {FIELD}")
    print(f"home metro     : {METRO_LABEL} ({len(METRO_TOWNS)} towns)   home state: {STATE_CODE} {STATE_NAME}")
    print(f"region         : {REGION_LABEL} {REGION_CODES}")
    print(f"location scores: {LOC_SCORES}")
    print(f"priority firms : {PRIORITY_COMPANIES}")
    print(f"skills         : {len(SKILLS)} groups   disciplines: target {DISC_TARGET}")
    print(f"                 off-target {DISC_OFF}")
    print(f"max years req. : {MAX_YEARS}   PE blocker: {PE_BLOCKER}")
    print(f"sieve tiers    : GOLD >= {GOLD_AT}, SILVER >= {SILVER_AT}   rules-only: GOLD >= {RULES_GOLD_AT}, SILVER >= {RULES_SILVER_AT}")


if __name__ == "__main__":
    summary()
    for t in sys.argv[1:]:
        print(f"  {t!r:50} -> {title_reject(t) or 'OK (passes the title rules)'}"
              f"{'  [entry signal]' if TITLE_ENTRY.search(t) else ''}{'  [target title]' if TITLE_TARGET.search(t) else ''}")
