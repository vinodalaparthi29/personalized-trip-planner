"""Shared Google sign-in for the planner's tools (Drive upload, form intake).

Everything runs as the planner's owner (OWNER_EMAIL in .env): plans live in the owner's Drive and
are shared with each traveller, so travellers never sign in. The first run uses Google's device
sign-in (a URL plus a short code); the token is then saved in tokens/owner.json.

Scope is drive.file: the app only sees files it created (the plans, the folder, the request sheet).
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "tokens" / "owner.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

load_dotenv(ROOT / ".env")


def owner_email():
    email = os.getenv("OWNER_EMAIL", "").strip().lower()
    if not email:
        sys.exit("Set OWNER_EMAIL in .env to the Google account whose Drive holds the plans.")
    return email


def load_client():
    if not CREDENTIALS_FILE.exists():
        sys.exit("credentials.json not found in the project root (see README: Google setup).")
    data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    client = data.get("installed") or data.get("web")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        sys.exit("credentials.json is missing client_id/client_secret.")
    return client


def request_device_code(client):
    resp = requests.post(DEVICE_CODE_URL, data={"client_id": client["client_id"], "scope": " ".join(SCOPES)}, timeout=30)
    body = resp.json()
    if resp.status_code != 200:
        hint = ""
        if body.get("error") in ("invalid_client", "unauthorized_client"):
            hint = ("\nThe OAuth client must be of type 'TVs and Limited Input devices'. "
                    "Create one under APIs & Services > Credentials and replace credentials.json.")
        sys.exit(f"Device sign-in request failed: {body.get('error')}: {body.get('error_description', '')}{hint}")
    return body


def device_sign_in(client, email):
    """Run the device flow and return Credentials once the owner approves."""
    code = request_device_code(client)
    print("\n=== GOOGLE SIGN-IN NEEDED (one time) ===")
    print(f"Open:            {code['verification_url']}")
    print(f"and enter code:  {code['user_code']}")
    print(f"(Sign in as {email}. The code expires in {code['expires_in'] // 60} minutes.)")
    print("Waiting for approval...", flush=True)

    interval = code.get("interval", 5)
    deadline = time.time() + code["expires_in"]
    while time.time() < deadline:
        time.sleep(interval)
        resp = requests.post(TOKEN_URL, data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "device_code": code["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }, timeout=30)
        body = resp.json()
        error = body.get("error")
        if not error:
            return Credentials(token=body["access_token"], refresh_token=body.get("refresh_token"),
                               token_uri=TOKEN_URL, client_id=client["client_id"],
                               client_secret=client["client_secret"], scopes=SCOPES)
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            sys.exit("Sign-in was declined. Nothing was changed.")
        sys.exit(f"Sign-in failed: {error}: {body.get('error_description', '')}")
    sys.exit("The sign-in code expired before it was approved. Run the command again for a new code.")


def get_credentials():
    """Return the owner's saved credentials, signing in first if needed."""
    email = owner_email()
    client = load_client()
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.valid:
            return creds
        if creds.refresh_token:
            try:
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                return creds
            except Exception as e:  # revoked or expired refresh token
                print(f"Saved sign-in no longer works ({e}); asking again.")
    creds = device_sign_in(client, email)
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def confirm_owner(drive):
    """Make sure the signed-in account is OWNER_EMAIL, so plans never land in the wrong Drive."""
    email = owner_email()
    actual = drive.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    if actual.lower() != email:
        TOKEN_FILE.unlink(missing_ok=True)
        sys.exit(f"Signed in as {actual}, but OWNER_EMAIL is {email}. "
                 "Token discarded; run again and sign in with the right account.")
