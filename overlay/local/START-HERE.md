# START HERE: first-time setup with Claude

> **For Claude.** The user just ran the Construction Job Search Kit's SETUP.cmd and typed something like "set me up".
> Follow these steps in order, one at a time, in plain language (she is a construction management
> student, not a programmer). Ask before moving on. AGENTS.md onboarding rules still apply; this
> file adds the kit's specifics on top.

## Kit rules (always)
- **Never submit an application or send an email/message for her.** Autofill stops at review; Gmail only makes drafts.
- **Only real facts.** Every resume / cover letter line must come from `cv.md` or `master-resume.json`. Never invent
  tools, numbers, dates, titles or certifications. If something is unclear, ask her.
- **One page.** Every resume and cover letter must compile to exactly one page.
- **Her files are hers.** `cv.md`, `config/*.yml`, `modes/_profile.md`, `modes/_brief.md`, `portals.yml`,
  `master-resume.json`, `data/`, `local/chrome-autofill/profile.json` are the user layer; edit them freely for her,
  never overwrite them with templates.
- She **needs H-1B sponsorship** (F-1 OPT). Postings that refuse sponsorship or require US citizenship / clearance
  are skipped by the scan filters and must be scored down in evaluations.

## Step 1: Health check
Run `node doctor.mjs --json`. The starter templates (construction management) are already in place, so
`unpersonalized` will list them: that's expected, the next steps fill them in.

## Step 2: Her CV (cv.md)
Look in `documents/` for her resume (PDF/DOCX). If it's empty, ask her to drop it there or paste it.
Rewrite `cv.md` from it, keeping the template's section structure. Delete template lines that don't apply
(e.g. software she hasn't used). Then ask her about anything a CM recruiter cares about that's missing:
site/field experience, internships, OSHA 10/30, LEED GA, Procore/Bluebeam/MS Project/P6 use, estimating or
scheduling work, class projects with real numbers (cost, SF, schedule).

## Step 3: Profile and targeting
Fill `config/profile.yml` (name, email, phone, LinkedIn, location, graduation date, visa, salary TODO).
Review with her and adjust:
- `modes/_profile.md` and `modes/_brief.md`: what scores high/low for her.
- `config/targeting.yml`: the title keywords and home-area towns that the free filters (sieve, ranking) use.
- `portals.yml`: the companies scanned. Ask if there are firms she wants added or removed.
Then run `node doctor.mjs --json` again; `unpersonalized` should now be empty.

## Step 4: Master resume + resume editor
Build `master-resume.json` from `cv.md`: every bullet tagged with one or more tracks (`project-engineer`,
`field`, `estimating`, or whatever fits her) and a status (`ok` / `confirm` / `never`). Then build the PDFs:
`python local/resume-builder/build_resume.py`. Check each PDF is one page. Show her the Resume Editor
(`Resume editor.cmd`, http://127.0.0.1:3002), where she can change wording herself.

## Step 5: Autofill (Chrome extension)
Fill `local/chrome-autofill/profile.json` from her profile (leave `null` anything she hasn't confirmed:
`null` means "never fill"). Walk her through installing the extension: `local/chrome-autofill/README.md`.

## Step 6: First scan
Run `node scan.mjs` (or have her double-click `Scan for jobs.cmd`), then `python local/sieve.py --fetch --limit 100`.
The sieve runs free rule-based checks (no GPU needed); results show on the website's EVERY JOB tab.
Open http://127.0.0.1:3000 in Chrome and show her the Today page, Pipeline and EVERY JOB.

## Step 7: First evaluations
Pick the top 3-5 GOLD/SILVER jobs and evaluate them with `/career-ops` (paste the job URL). Each evaluation writes
a report plus a tailored resume and cover letter. Ask her whether the scores feel right; if not, update
`modes/_profile.md` so future scores learn from it.

## Step 8: Optional extras (only if she wants them)
- **Gmail / LinkedIn job alerts / Google Calendar:** needs a Google Cloud OAuth "Desktop app" client.
  See `local/README-local.md` and run `python local/gmail_connect.py`; then set those plugins to
  `enabled: true` in `config/plugins.yml`.
- **Better free sieve:** a free OpenRouter key in `local/secrets/openrouter.key` adds the AI stages to the sieve
  (only free models are ever used).

## Daily routine (tell her this at the end)
1. Scans run by themselves at 7 AM and 5 PM; a Windows notification says how many new jobs came in.
2. Open http://127.0.0.1:3000, look at the new jobs, then in VS Code ask Claude: "evaluate the new GOLD jobs".
3. For a job she likes: "apply to #<number>". Claude tailors the resume and cover letter; she reviews,
   opens the posting in Chrome, clicks the autofill extension, checks every field, and clicks Submit herself.
4. "What should I follow up on?" shows applications that are due a follow-up.
