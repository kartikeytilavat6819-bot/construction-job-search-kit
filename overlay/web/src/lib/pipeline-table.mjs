/**
 * pipeline-table.mjs — line parsing of `data/pipeline.md` for the web read path.
 *
 * Split out of career-ops.ts for the same reason tracker-table.mjs exists: the
 * web reader of a user data file is exactly the kind of code that needs a
 * regression test running the REAL parser, and `node --test` (see
 * web/package.json) can only import plain .mjs — career-ops.ts pulls in `@/`
 * path aliases and Next-only modules.
 *
 * Everything here is pure: text in, rows out. No fs, no Next.
 */

/**
 * Split a career-ops data file into lines, tolerating CRLF.
 *
 * `data/` is gitignored (see .gitignore), so the repo-wide `eol=lf` policy in
 * .gitattributes does NOT reach the user's own pipeline.md / scan-history.tsv:
 * an editor, a sync client or any non-LF writer on Windows can leave CRLF
 * there. A plain `split("\n")` then leaves a trailing "\r" on every line, which
 * silently defeats any `$`-anchored row regex (JS `.` never matches \r) — the
 * file parses to zero rows and the UI just looks empty. Split on the line
 * break, not on "\n".
 *
 * @param {string} text
 * @returns {string[]}
 */
export function splitLines(text) {
  return text.split(/\r?\n/);
}

/** A pipeline-row segment like `posted: 2026-07-14`, `trust: 62 stale` or
 *  `note: …` — the core appends these LABELED segments after whatever
 *  positional shape a row has (3/4/5 columns), so a naive positional reader
 *  would misread them as location/compensation on short rows. Any
 *  `word:`-prefixed segment is treated as labeled (forward-compatible with
 *  labels the core hasn't invented yet). */
const LABELED_SEGMENT = /^([a-z][a-z_-]*):\s*(.*)$/i;

/** Parse data/pipeline.md — `- [ ] URL | Company | Role [| Location [| Compensation]] [| label: …]*`.
 *  Positional split for the first columns (the optional 4th `location` #1015
 *  and 5th `compensation` #1017 must NOT bleed into `role`); labeled segments
 *  (posted:/trust:/note:/…) are filtered out of positional assignment wherever
 *  they appear and surfaced when useful (posted: → postedAt). Unknown labels
 *  and further trailing columns are ignored gracefully.
 *  @param {string} md - content of data/pipeline.md.
 *  @returns {{url: string, company: string, role: string, location?: string, compensation?: string, done: boolean, postedAt?: string}[]}
 */
export function parseInbox(md) {
  const jobs = [];
  for (const line of splitLines(md)) {
    const m = line.match(/^\s*-\s*\[([ xX])\]\s*(.+)$/);
    if (!m) continue;
    const all = m[2].split("|").map((s) => s.trim());
    const labels = new Map();
    const parts = [];
    for (const [i, seg] of all.entries()) {
      // the URL cell can contain a colon-y value but is always position 0
      const lm = i >= 3 ? seg.match(LABELED_SEGMENT) : null;
      if (lm) labels.set(lm[1].toLowerCase(), lm[2].trim());
      else parts.push(seg);
    }
    if (parts.length < 3 || !parts[0]) continue; // need at least url | company | role
    const posted = labels.get("posted");
    jobs.push({
      done: m[1].toLowerCase() === "x",
      url: parts[0],
      company: parts[1],
      role: parts[2],
      location: parts[3] || undefined, // optional 4th column (#1015)
      compensation: parts[4] || undefined, // optional 5th column (#1017); 6th+ ignored
      // the row's own posting date (scan.mjs `posted:` label) — a more direct
      // freshness signal than the scan-history join, which stays as fallback
      postedAt: posted && /^\d{4}-\d{2}-\d{2}$/.test(posted) ? posted : undefined,
    });
  }
  return jobs;
}

// Local change (2026-10-09): the "EVERY JOB" tab shows every posting in pipeline.md — pending and screened out —
// not only the ones that reached the tracker. Processed rows look like
//   - [x] ~~URL | Company | Role~~ - reason
//   - [x] [N](../reports/…) | URL | Company | Role | …   (evaluated, linked to a report)
/** Bucket a processed row's reason into one outcome label for the filter chips. */
export function outcomeOf(reason) {
  const r = reason.toLowerCase();
  if (r.startsWith("evaluated")) return "Evaluated";
  if (/outside the us|non-us|uk posting|location outside/.test(r)) return "Outside US";
  if (r.includes("sponsorship")) return "No sponsorship";
  if (r.startsWith("parked")) return "Parked";
  if (r.startsWith("rule fail")) return "Rule fail";
  if (r.includes("triage fail")) return "AI triage fail";
  return "Other";
}

/** @param {string} md - content of data/pipeline.md.
 *  @returns {{url: string, company: string, role: string, location?: string, outcome: string, reason: string, report?: string, postedAt?: string}[]} */
export function parseAllPipeline(md) {
  const rows = [];
  for (const line of splitLines(md)) {
    const m = line.match(/^\s*-\s*\[([ xX])\]\s*(.+)$/);
    if (!m) continue;
    const done = m[1].toLowerCase() === "x";
    let body = m[2];
    let reason = "";
    let report;
    const strike = body.match(/^~~(.+?)~~\s*(?:-\s*(.*))?$/);
    if (strike) {
      body = strike[1];
      reason = (strike[2] ?? "").trim();
    }
    const rep = body.match(/^\[(\d+)\]\([^)]*\)\s*\|\s*(.+)$/);
    if (rep) {
      report = rep[1];
      body = rep[2];
      reason = reason || "evaluated - see tracker";
    }
    const all = body.split("|").map((s) => s.trim());
    const labels = new Map();
    const parts = [];
    for (const [i, seg] of all.entries()) {
      const lm = i >= 3 ? seg.match(LABELED_SEGMENT) : null;
      if (lm) labels.set(lm[1].toLowerCase(), lm[2].trim());
      else parts.push(seg);
    }
    if (parts.length < 3 || !/^https?:/.test(parts[0])) continue;
    const posted = labels.get("posted");
    const loc = parts[3] && !/^\d(\.\d)?\/5$/.test(parts[3]) ? parts[3] : undefined; // report rows put the score in col 4
    rows.push({
      url: parts[0],
      company: parts[1],
      role: parts[2],
      location: loc,
      outcome: done ? outcomeOf(reason) : "Pending",
      reason: reason.length > 220 ? `${reason.slice(0, 220)}…` : reason,
      report,
      postedAt: posted && /^\d{4}-\d{2}-\d{2}$/.test(posted) ? posted : undefined,
    });
  }
  return rows;
}
