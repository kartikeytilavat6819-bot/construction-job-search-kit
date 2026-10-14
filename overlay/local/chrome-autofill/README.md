# career-ops Autofill (Chrome extension)

Fills job applications in your normal Chrome **while you watch**, and attaches the tailored
resume and cover letter career-ops made for that application.
**It never clicks Next, Submit or Save.** You always review and submit yourself.

## 1. Fill in your answers (once)
Your answers live in **`profile.json` in this folder** (`<your career-ops folder>\local\chrome-autofill\profile.json`).
If it isn't there yet, copy it from the kit's `templates\local\chrome-autofill\profile.json`.

- Open it in Notepad (right-click, Open with, Notepad) and replace each `null` with your answer in quotes,
  e.g. `"first_name": "Jane",`. Keep the commas and quotes exactly as they are.
- `null` (no quotes) means "never fill this in, I'll answer it myself". That is the safe choice for
  anything you aren't sure about.
- The `"_help_..."` lines are notes for you. The extension ignores them.
- The work-authorization answers are pre-filled for an F-1 student on OPT who will need H-1B
  sponsorship. **Read them and change them if your situation is different.**
- Edits apply on the next page you open. There's nothing to reload.

Your work history and education are **not** typed into profile.json: the extension reads them from
career-ops' `cv.md`, so keep that file up to date.

## 2. Install the extension in Chrome (once)
1. Open `chrome://extensions` in Chrome and turn on **Developer mode** (top right).
2. Click **Load unpacked** and pick this folder (`<your career-ops folder>\local\chrome-autofill`,
   for example `C:\Users\<you>\career-ops\local\chrome-autofill`).
3. Pin it: click the puzzle-piece icon in the toolbar, then the pin next to **career-ops Autofill**.

You don't need to come back here after that. Chrome rereads the fill code (`content.js`) and the popup
every time they load. If `background.js` or `manifest.json` ever change, the popup shows a blue
**Update ready** button, and one click applies the update.

## 3. Start the helper
The extension gets your files and answers from a small helper program on your own computer
(`docs_server.py`, at http://127.0.0.1:3001; nothing is sent anywhere else). If the career-ops setup
made it start at logon, it's already running. If not, double-click **`Start autofill helper.cmd`** in this folder.
If the popup says "Can't reach the autofill helper", the helper isn't running.

## Use
1. Open the application form in Chrome. Log in or create the account first if the site needs one.
2. Click the extension icon. It shows **"This page: #15 Company – Role"**. It recognizes the job by its job
   number in the address or on the page (Workday R-12345, iCIMS, Taleo, Lever and similar IDs), or by the
   posting you opened in that tab, or else by company and title. If it can't tell, it shows the list, and
   "Not this job?" opens it at any time. Check the resume and cover letter files it lists.
3. Pick a typing speed and click **Start filling**. Amber means it's working on a field, green means filled,
   blue means a file was uploaded and purple means a drafted answer for you to read. Hover over a field to see
   which profile key it came from. The panel at the bottom right lists what was filled and what still
   **Needs you** (required fields first).
4. Click Next yourself. Each new page (and embedded frame) is filled as it appears, until you click **Stop**.
   It pauses while you type or click, so it never fights you.
5. Answer the rest, review everything and submit it yourself.

## What it fills
- Contact details, address, LinkedIn and website from `profile.json`.
- Yes/No screening questions from `profile.json`: work authorization, sponsorship, relocation, 18+,
  driver's license, "worked here before", relatives at the company, non-compete and similar. A question
  that asks whether you can work *without* sponsorship is never guessed. It's flagged for you instead.
- Essay questions ("Why our company?", "Describe a relevant project") get the answer career-ops drafted in
  that job's report (section "H) Draft Application Answers"), outlined in **purple**. Read and edit these
  before you submit. A cover-letter text box gets the text of your tailored cover letter. If there's no draft,
  the box stays empty: it never makes an answer up.
- Expected pay gets the top of the range the posting advertises (the report's `advertised_comp`). If the posting
  has no range, `salary_expectation` from profile.json is used, and if that's `null` the field is left for you.
- Work Experience and Education entries from career-ops `cv.md`, newest first: title, company, location,
  From/To dates, the job's bullets in a description box, school, degree, field and graduation date. It only fills
  entries the form already shows. It never clicks "Add another", so do that yourself or use the site's
  "autofill from resume". The GPA in profile.json goes only on the first (most recent) education entry.
- EEO / self-identification dropdowns from `profile.json` (gender, race, Hispanic/Latino, veteran, disability).
  Leave them `null` if you'd rather choose each time.
- Uploads: the tailored resume and cover letter that the job's report names. They're renamed
  `First_Last_Resume.pdf` / `First_Last_Cover_Letter.pdf` from your name in profile.json.

## What it never does
- Click Next, Submit, Save or any button that moves the form on.
- Fill passwords, tick consent or terms checkboxes, or fill date pickers.
- Overwrite something that's already filled.
- Put your details into someone else's fields (references, emergency contact, employer or school address,
  "Company Phone").

Note that `previously_employed_here` is one answer for every company. If you apply back to a past
employer, answer that question yourself. The panel shows what it filled.

Systems it knows: Workday, iCIMS, Taleo, Oracle, SuccessFactors, ADP, UKG, Paylocity, Paycom, Cornerstone,
SmartRecruiters, Greenhouse, Pinpoint, Lever and Workable, plus ordinary web forms.

## Files
- `profile.json`: your answers. It's private, so don't share it. `null` means never auto-filled.
- `docs_server.py`: the read-only helper on http://127.0.0.1:3001. It only answers this extension, never other
  websites. It serves the tracker, each report's `**PDF:**` / `**Cover letter:**` files, your answers and the
  extension's update fingerprint, and keeps `data/pdf-index.tsv` in sync for the career-ops website. It finds
  the career-ops folder from its own location (two folders up), so it works wherever career-ops is installed.
- `Start autofill helper.cmd`: starts the helper if it isn't running (needs Python).
- `content.js`, `background.js`, `popup.html`, `popup.js` and `manifest.json` are the extension itself.
