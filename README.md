# Construction Job Search Kit

A ready-to-go job search setup **based on [career-ops](https://github.com/career-ops-hq/career-ops)**, the open-source
AI job-search agent. It finds entry-level construction management jobs, filters out the ones that refuse visa
sponsorship, scores the rest against your profile, writes a tailored one-page resume and cover letter for each,
and fills in application forms in Chrome. **You always review and click Submit yourself.**

Tuned for: entry-level CM roles (Project Engineer, Assistant PM, Field Engineer, Estimator, Scheduler, Project
Coordinator, Owner's Rep...), F-1 OPT needing H-1B sponsorship, Boston first, then New England, then the rest of the US.

## What you need
- A Windows 10/11 laptop (no special graphics card needed)
- A **Claude Pro** (or Max) subscription: https://claude.ai
- About 30 minutes for setup, then 30-45 minutes with Claude to fill in your profile

## Setup (one time)
1. On this GitHub page click **Code > Download ZIP**, then unzip it (for example to your Desktop).
2. Double-click **`SETUP.cmd`** in the unzipped folder. If Windows asks "Do you want to allow this app...", click Yes.
   It installs everything it needs (Git, Node.js, Python, VS Code, Chrome, LaTeX), downloads career-ops into
   `C:\Users\<you>\career-ops`, builds the website and schedules the daily job scan. It takes 15-25 minutes.
   - If it stops and says to open a new window, close it and double-click `SETUP.cmd` again. It picks up where it left off.
3. When it finishes, VS Code opens the career-ops folder. Click the **Claude** icon in the sidebar and sign in.
4. Copy your current resume (PDF or Word) into the `documents` folder inside career-ops.
5. Type to Claude: **`Read local/START-HERE.md and set me up`**

Claude reads your resume, fills in your profile, builds your master resume and runs your first job scan.

## Every day
| What | How |
|---|---|
| New jobs | Found automatically at **7 AM and 5 PM**. A Windows notification tells you how many. |
| See them | Open **http://127.0.0.1:3000** in Chrome (Today, Pipeline and EVERY JOB tabs). |
| Score them | In VS Code ask Claude: *"evaluate the new GOLD jobs"* |
| Apply | Ask Claude: *"apply to #12"*. You get a tailored resume and cover letter. Open the job in Chrome, click the autofill extension, check every field, then Submit yourself. |
| Follow up | Ask Claude: *"what should I follow up on?"* |
| Edit your resume | Double-click **`Resume editor.cmd`** (http://127.0.0.1:3002) |

Shortcuts inside the career-ops folder: `Start career-ops.cmd` (if the website isn't loading), `Scan for jobs.cmd`
(scan right now), `Resume editor.cmd`, `Run job sieve.cmd`.

## Your data stays on your laptop
Your resume, profile, job tracker and applications live only in `C:\Users\<you>\career-ops`. Nothing is uploaded
except what you send to Claude while you chat. The website runs only on your own computer (127.0.0.1).

## What's in this kit
| Folder | What it is |
|---|---|
| `setup.ps1`, `SETUP.cmd` | The installer |
| `overlay/` | Extra tools copied on top of career-ops: `local/` scripts (job-board readers, sponsorship screen, job sieve, resume builder, Chrome autofill), website improvements, shortcuts |
| `templates/` | Starter personal files for construction management. They're copied only if you don't have them yet, so running setup again never erases your work. |
| `patches/` | The career-ops version this kit was tested with |

## Troubleshooting
- **Website doesn't load:** double-click `Start career-ops.cmd`.
- **Did the scan run?** See `career-ops\data\logs\daily-scan-*.log`, or ask Claude "check the last scan log".
- **Turn off the automatic scan:** Start menu > Task Scheduler > `career-ops daily scan` > Disable.
- **Anything else:** ask Claude in VS Code. It can read the logs and fix things.

## Credits and license
Based on [career-ops](https://github.com/career-ops-hq/career-ops) by Santiago Fernández de Valderrama (MIT License).
This kit is an independent project and is not affiliated with or endorsed by career-ops. The files under
`overlay/web/` are modified copies of career-ops files. See [LICENSE](LICENSE).
