# Construction Job Search Kit notes (local to this computer)

This career-ops copy was set up with the Construction Job Search Kit (based on career-ops) for a **construction management** job search
(entry-level, needs H-1B sponsorship, Boston first, then New England, then anywhere in the US).

- When she asks to "set me up", or `node doctor.mjs --json` shows `unpersonalized` files: follow `local/START-HERE.md`.
- The kit's own tools live in `local/` (map: `local/README-local.md`). They are not part of upstream career-ops,
  and `update-system.mjs` never touches them.
- **Never submit an application or send a message for her.** Never invent facts; resumes come only from `cv.md` / `master-resume.json`.
- The website (http://127.0.0.1:3000) starts at logon; the job scan runs at 7 AM and 5 PM
  (Task Scheduler: `career-ops website`, `career-ops daily scan`). Logs: `data/logs/`.
- After editing anything under `web/src`, run `npm run build` in `web/` and restart the website task:
  `Stop-ScheduledTask 'career-ops website'; Start-ScheduledTask 'career-ops website'`.
- No GPU on this laptop: the sieve runs its rule stages only (plus free OpenRouter models if `local/secrets/openrouter.key` exists).
