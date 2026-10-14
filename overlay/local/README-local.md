# local/ : the custom scripts in this kit

Everything here runs on your own laptop. No GPU is needed and nothing here spends Claude usage.
What counts as a good job for you is set in **`config/targeting.yml`** (titles, home area, skills, score
cut-offs). Edit that file, not the scripts. Check it with `python local/targeting.py`.
First-time setup steps are in `START-HERE.md`; this page is only a map.

## Runs by itself

**`daily-scan.ps1`** runs at 7 AM and 5 PM (Windows Task Scheduler). It runs these steps in order:
1. `icims_jobs.py` / `workday_us_jobs.py` prefetch: reads the big iCIMS / Workday boards listed in `portals.yml` ahead of time.
2. `node scan.mjs`: scans every company board (career-ops itself).
3. `prune-location.mjs`: drops postings outside the US that the scan missed.
4. `rank_pipeline.py`: puts new jobs in order, home area and entry-level titles first, and writes `data/pipeline-ranked.md`.
5. `sponsor_screen.py`: reads the top 60 postings, saves their text in `jds/`, and drops the ones that refuse visa sponsorship.
6. `apply_screen.py`: moves the refusals and foreign postings out of the inbox.
7. `sieve.py`: runs the job sieve (below) on everything.
8. `sieve_clean_pending.py` and `clean_pending.py`: tick off the jobs that were rejected or already decided.
9. `link_covers.py` and `build_locations.py`: small fixes so the website can find cover letters and filter by state.
10. The Gmail, LinkedIn-alert and Google Calendar plugins, but only the ones switched on in `config/plugins.yml`.

At the end you get a Windows notification with the number of new jobs. Logs are in `data/logs/`.

**`start-website.ps1`** runs at logon. It starts the website (http://127.0.0.1:3000), the Resume Editor (port 3002)
and the autofill PDF helper (port 3001).

## Run by hand (shortcuts are in the career-ops folder)

| Shortcut / command | What it does |
|---|---|
| `Run job sieve.cmd` (`sieve-run.ps1`) | Runs the sieve and downloads missing job descriptions first. Results show on the website's EVERY JOB tab. |
| `Watch sieve progress.cmd` (`sieve-progress.ps1`) | Opens a live progress window for the sieve. |
| `Connect Gmail.cmd` (`gmail_connect.py`) | Connects Gmail and Google Calendar. You only do this once (see below). |
| `python local/sieve.py --retier` | Re-scores every job in seconds after you edit `config/targeting.yml`. |
| `python local/sieve_eval_queue.py --top 10` | Lists the best GOLD jobs to give Claude for full evaluations. |
| `python local/targeting.py "Assistant Project Manager"` | Shows how a job title is judged. |

## The job sieve (`sieve.py`)

The sieve sorts every job into one of these:
- **GOLD:** evaluate it.
- **SILVER:** take a look.
- **REJECT:** hidden. The reason is shown on the EVERY JOB tab.
- **NO_JD:** the posting text hasn't been saved yet.

It works in stages:
- **S1–S4 are free rules.** They check:
  - US location;
  - title (too senior, off-target, technician level);
  - sponsorship refusal, too many years required, PE license required;
  - a score built from your skills, entry-level wording, H-1B history and location.
- **Rules only.** With no AI model set up, that score decides the tier. The cut-offs are under `scoring:` in `targeting.yml`.
- **Optional AI stages S5–S7.** To add them for free, put an OpenRouter API key in `local/secrets/openrouter.key`. Only free models are used.

## Other scripts

- **Company board readers** (called from `portals.yml` with `scan_method: local_parser`):
  - `icims_jobs.py`, `workday_us_jobs.py`, `jacobs_avature_jobs.py`, `jaycashman_jobs.py`
  - `applicantpro_jobs.py`, `birddoghr_jobs.py`, `dayforce_jobs.py`, `directemployers_jobs.py`
  - `eightfold_pcsx_jobs.py`, `paycom_jobs.py`, `paycor_jobs.py`, `paylocity_jobs.py`
  - `selectminds_jobs.py`, `silkroad_jobs.py`

  Some of these only look at New England offices; the note at the top of each file says which.
- **Free filters and queues:**
  - `rule_prefilter.py`: rule checks for a triage queue.
  - `untriaged_queue.py`: builds triage queues.
  - `make_batch_input.py`: the batch-runner input.
  - `merge_websearch.py`: adds web-search results. It skips firms known to refuse sponsorship.
  - `recheck-title.mjs` and `recheck-location.mjs`: bring back jobs skipped before you widened a filter.
- **For Claude:** `eval-agent-brief.md`, `eval-agent-brief-lean.md` and `triage-agent-brief.md` are the instructions helper agents follow. `check_linebreaks.py` repairs LaTeX files before they are compiled.
- **Optional, needs Ollama (a local AI model, ideally on a GPU):**
  - `ollama_triage.py`, which `progress.ps1` tracks.
  - `second_opinion.py`, which also works with an OpenRouter key.

  Without a model, these scripts stop with a short message.

## Connecting Gmail (optional)

1. **Create a Google Cloud project.** At console.cloud.google.com:
   - Create a project.
   - Enable the Gmail API, plus the Google Calendar API if you want interview events.
   - Set up the OAuth consent screen: External, Testing, and add yourself as a test user.
2. **Get the client file.** Go to Clients → Create client → **Desktop app** → Download JSON. Leave the file in Downloads.
3. **Connect.** Double-click **`Connect Gmail.cmd`**, sign in to Google, and click Allow. This creates:
   - your keys in `.env`;
   - a "Job Leads" Gmail label;
   - a filter for job-alert emails.
4. **Switch the plugins on.** In `config/plugins.yml`, set `enabled: true` for `gmail`, and for `linkedin-alerts` and `google-calendar` if you want them.

In Testing mode, Google's connection expires after about a week. When it does, the daily scan shows a
"reconnect Gmail" notification. Double-click `Connect Gmail.cmd` again to reconnect.

## Python packages

`requests`, `beautifulsoup4` and `pyyaml` (see the kit's `requirements.txt`). `playwright` is only needed for
`jacobs_avature_jobs.py`, and `google-auth-oauthlib` and `google-api-python-client` only for `gmail_connect.py`.
