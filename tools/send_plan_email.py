"""Email a rendered travel plan PDF to the traveller from the owner's Gmail.

Usage:
    python tools/send_plan_email.py .tmp/<trip_slug>               # send to the request's traveler_email
    python tools/send_plan_email.py .tmp/<trip_slug> --to <addr>   # send somewhere else (testing)

Sends outputs/<trip_slug>_travel_plan.pdf as an attachment through Gmail SMTP, logged in as OWNER_EMAIL
with GMAIL_APP_PASSWORD from .env, and BCCs the owner so they see every plan that goes out.
SMTP is used because the device sign-in in google_auth.py can't grant Gmail scopes.
"""

import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

from google_auth import ROOT, owner_email

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def app_password():
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not password:
        sys.exit("Set GMAIL_APP_PASSWORD in .env (see README: Emailing plans).")
    return password


def send(msg):
    """Send an EmailMessage from the owner's Gmail."""
    sender = owner_email()
    msg["From"] = sender
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
            smtp.login(sender, app_password())
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        sys.exit("Gmail rejected the login: GMAIL_APP_PASSWORD is wrong or was revoked. Create a new App Password.")
    except (smtplib.SMTPException, OSError) as e:
        sys.exit(f"Email failed: {e}")


def notify_owner(subject, body):
    """Send a plain note to the owner (used by auto_plan.py for failures)."""
    msg = EmailMessage()
    msg["To"] = owner_email()
    msg["Subject"] = subject
    msg.set_content(body)
    send(msg)


def plan_message(req, pdf_path, to):
    msg = EmailMessage()
    msg["To"] = to
    if to.lower() != owner_email():
        msg["Bcc"] = owner_email()
    msg["Subject"] = f"Your travel plan for {req['destination']}"
    msg.set_content(
        f"Hi {req['traveler_name']},\n\n"
        f"Here is your personalized travel plan for {req['destination']} "
        f"({req['start_date']} to {req['end_date']}). It's attached as a PDF.\n\n"
        "Have a great trip!\n"
    )
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
    return msg


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    to = None
    if "--to" in args:
        i = args.index("--to")
        if i + 1 >= len(args):
            sys.exit("Usage: send_plan_email.py .tmp/<trip_slug> --to <addr>")
        to = args[i + 1]
        del args[i:i + 2]

    folder = Path(args[0])
    req = json.loads((folder / "request.normalized.json").read_text(encoding="utf-8"))
    pdf_path = ROOT / "outputs" / f"{req['trip_slug']}_travel_plan.pdf"
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}. Run render_trip_pdf.py first.")
    to = to or req.get("traveler_email")
    if not to:
        sys.exit("No traveler_email in the request; pass --to <addr>.")

    send(plan_message(req, pdf_path, to))
    print(f"OK: emailed {pdf_path.name} to {to}")


if __name__ == "__main__":
    main()
