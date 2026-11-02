"""Upload a rendered travel plan PDF to the owner's Google Drive and share it with the traveller.

Usage:
    python tools/upload_to_drive.py .tmp/<trip_slug>
    python tools/upload_to_drive.py --check-credentials

Uploads outputs/<trip_slug>_travel_plan.pdf into a "Travel Plans" folder in OWNER_EMAIL's Drive,
replacing the file if this trip was uploaded before, then shares it (view only) with the request's
traveler_email. Google emails the traveller a "shared with you" link; they don't sign in to anything.

Sign-in is handled by google_auth.py (one-time device sign-in for the owner).
"""

import json
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from google_auth import ROOT, confirm_owner, get_credentials, load_client, request_device_code

FOLDER_NAME = "Travel Plans"
FOLDER_MIME = "application/vnd.google-apps.folder"


def find_one(service, query):
    files = service.files().list(q=query, spaces="drive", fields="files(id, name, webViewLink)").execute()["files"]
    return files[0] if files else None


def get_folder(service):
    folder = find_one(service, f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false")
    if folder:
        return folder["id"]
    return service.files().create(body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME}, fields="id").execute()["id"]


def upload(service, pdf_path, folder_id):
    media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=True)
    existing = find_one(service, f"name = '{pdf_path.name}' and '{folder_id}' in parents and trashed = false")
    if existing:
        f = service.files().update(fileId=existing["id"], media_body=media, fields="id, webViewLink").execute()
        return f, "replaced"
    f = service.files().create(body={"name": pdf_path.name, "parents": [folder_id]}, media_body=media,
                               fields="id, webViewLink").execute()
    return f, "uploaded"


def share(service, file_id, req):
    """Give the traveller view access; Google sends them the notification email."""
    message = (f"Hi {req['traveler_name']}, here is your personalized travel plan for "
               f"{req['destination']} ({req['start_date']} to {req['end_date']}). Have a great trip!")
    service.permissions().create(
        fileId=file_id,
        body={"type": "user", "role": "reader", "emailAddress": req["traveler_email"]},
        sendNotificationEmail=True, emailMessage=message, fields="id",
    ).execute()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--check-credentials":
        code = request_device_code(load_client())
        print(f"OK: credentials.json works with device sign-in (test code {code['user_code']} issued and left unused).")
        return

    folder = Path(sys.argv[1])
    req = json.loads((folder / "request.normalized.json").read_text(encoding="utf-8"))
    pdf_path = ROOT / "outputs" / f"{req['trip_slug']}_travel_plan.pdf"
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}. Run render_trip_pdf.py first.")

    try:
        service = build("drive", "v3", credentials=get_credentials(), cache_discovery=False)
        confirm_owner(service)
        f, action = upload(service, pdf_path, get_folder(service))
    except HttpError as e:
        sys.exit(f"Drive API error: {e}")
    print(f"OK: {action} {pdf_path.name} in Drive/{FOLDER_NAME}")

    email = req.get("traveler_email")
    if not email:
        print("NOTE: no traveler_email, so the plan was not shared. Send this link yourself:")
    else:
        try:
            share(service, f["id"], req)
            print(f"OK: shared with {email} (Google has emailed them the link)")
        except HttpError as e:
            # e.g. an address with no Google account behind it
            print(f"WARNING: could not share with {email} ({e.reason}). Send this link yourself, "
                  "after setting it to 'Anyone with the link' in Drive:")
    print(f["webViewLink"])


if __name__ == "__main__":
    main()
