r"""One-time Gmail connection for career-ops' gmail plugin (and the google-calendar plugin).

  python local/gmail_connect.py [path\to\client_secret.json]
  or double-click "Connect Gmail.cmd" in the career-ops folder (it also tests the connection).

1. Uses the OAuth "Desktop app" client JSON you downloaded from Google Cloud (default: the newest
   client_secret*.json in your Downloads folder).
2. Opens Google's own sign-in page in your browser - you sign in and click Allow. No password is
   ever typed or stored by this script.
3. Saves GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN into career-ops/.env
   (other lines in .env are kept). Secrets are never printed.
4. Creates the Gmail label "Job Leads" and a filter that files job-alert emails into it.

Scopes: gmail.readonly (read leads), gmail.labels (create the label), gmail.settings.basic
(create the filter), calendar.readonly (google-calendar plugin: spot interview events; needs the
Google Calendar API enabled in the same Cloud project), gmail.compose (optional outreach tools may create
DRAFTS only - nothing in career-ops ever sends mail). Revoke any time at
https://myaccount.google.com/permissions
"""
import glob, os, sys
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, ".env")
LABEL = "Job Leads"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.labels",
          "https://www.googleapis.com/auth/gmail.settings.basic",
          "https://www.googleapis.com/auth/calendar.readonly",  # google-calendar plugin: interview events
          "https://www.googleapis.com/auth/gmail.compose"]  # outreach drafts (never sent by career-ops)
ALERT_SENDERS = ["jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com", "alert@indeed.com",
                 "noreply@glassdoor.com", "noreply@handshake.com", "notifications@joinhandshake.com",
                 "ziprecruiter.com", "noreply@governmentjobs.com"]


def client_file():
    if len(sys.argv) > 1:
        return sys.argv[1]
    home = os.path.expanduser("~")
    # Downloads / Desktop, plus the same folders inside a cloud-synced home folder (e.g. a synced Desktop)
    folders = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop"),
               *glob.glob(os.path.join(home, "*", "Downloads")), *glob.glob(os.path.join(home, "*", "Desktop"))]
    hits = [h for d in folders for h in glob.glob(os.path.join(d, "client_secret*.json"))]
    if not hits:
        sys.exit("No client_secret*.json found in Downloads or Desktop.\n"
                 "In Google Cloud: Clients -> Create client -> Desktop app -> Create -> Download JSON, then run this again.")
    return max(hits, key=os.path.getmtime)


def save_env(values):
    lines = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
    lines = [l for l in lines if l.split("=", 1)[0].strip() not in values]
    lines += [f"{k}={v}" for k, v in values.items()]
    with open(ENV, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def ensure_label(svc):
    for lab in svc.users().labels().list(userId="me").execute().get("labels", []):
        if lab["name"] == LABEL:
            return lab["id"], False
    lab = svc.users().labels().create(userId="me", body={
        "name": LABEL, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()
    return lab["id"], True


def ensure_filter(svc, label_id):
    query = " OR ".join(ALERT_SENDERS)
    for f in svc.users().settings().filters().list(userId="me").execute().get("filter", []):
        if label_id in (f.get("action", {}).get("addLabelIds") or []):
            return False
    svc.users().settings().filters().create(userId="me", body={
        "criteria": {"from": query}, "action": {"addLabelIds": [label_id]}}).execute()
    return True


def main():
    path = client_file()
    print("Using OAuth client file:", os.path.basename(path))
    print("Your browser will open Google's sign-in page. Sign in and click Allow.")
    flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", open_browser=True)
    if not creds.refresh_token:
        sys.exit("Google returned no refresh token. Remove career-ops at myaccount.google.com/permissions and run again.")
    # One consent covers both plugins, so the calendar keys are the same client + refresh token.
    save_env({"GMAIL_CLIENT_ID": creds.client_id, "GMAIL_CLIENT_SECRET": creds.client_secret,
              "GMAIL_REFRESH_TOKEN": creds.refresh_token,
              "GOOGLE_CALENDAR_CLIENT_ID": creds.client_id, "GOOGLE_CALENDAR_CLIENT_SECRET": creds.client_secret,
              "GOOGLE_CALENDAR_REFRESH_TOKEN": creds.refresh_token})
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    email = svc.users().getProfile(userId="me").execute().get("emailAddress")
    label_id, made_label = ensure_label(svc)
    made_filter = ensure_filter(svc, label_id)
    print(f"Connected Gmail account: {email}")
    print(f"Saved keys to {ENV} (not shown).")
    print(f'Label "{LABEL}": {"created" if made_label else "already existed"}; '
          f'job-alert filter: {"created" if made_filter else "already existed"}.')
    print("Done. Set gmail (and google-calendar / linkedin-alerts) to enabled: true in config/plugins.yml,")
    print("then test with:  node plugins.mjs run gmail")


if __name__ == "__main__":
    main()
