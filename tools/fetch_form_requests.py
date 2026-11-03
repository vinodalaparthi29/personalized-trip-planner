"""Pull trip requests from the Google Form's response sheet into inputs/trip_request.json.

Usage:
    python tools/fetch_form_requests.py --create-sheet   # one time: make the sheet the Form writes to
    python tools/fetch_form_requests.py --list           # show requests not planned yet
    python tools/fetch_form_requests.py                  # write the oldest pending one to inputs/trip_request.json
    python tools/fetch_form_requests.py --id <id>        # write that pending one instead (auto_plan.py uses this)
    python tools/fetch_form_requests.py --done <id>      # mark a request planned (after delivery)

The sheet must be created by this tool: the app's drive.file scope can only read files it created.
Link the Form to it with Responses > Link to Sheets > Select existing spreadsheet, and put its ID in
.env as FORM_SHEET_ID. Processed requests are tracked in inputs/processed_responses.json.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_auth import ROOT, get_credentials

OUT_FILE = ROOT / "inputs" / "trip_request.json"
DONE_FILE = ROOT / "inputs" / "processed_responses.json"
SHEET_TITLE = "Trip Planner Requests"
SERIAL_EPOCH = datetime(1899, 12, 30)  # Sheets date serial 0

# Request field -> phrase its Form question title must contain (case-insensitive). See README.
QUESTIONS = {
    "traveler_name": "your name",
    "traveler_email": "mail",  # "Email", "Gmail address", ...
    "destination": "destination",
    "origin_city": "travelling from",
    "start_date": "start date",
    "num_days": "number of days",
    "what_they_like": "things you like",
    "why_visiting": "why are you visiting",
    "trip_goals": "get out of this trip",
    "budget_level": "budget",
    "group_type": "who is travelling",
    "pace": "pace",
    "special_needs": "special needs",
}
OPTIONAL = {"special_needs"}


def sheets_service():
    return build("sheets", "v4", credentials=get_credentials(), cache_discovery=False)


def create_sheet():
    sheet = sheets_service().spreadsheets().create(body={"properties": {"title": SHEET_TITLE}},
                                                   fields="spreadsheetId,spreadsheetUrl").execute()
    print(f"OK: created '{SHEET_TITLE}'")
    print(f"1. Add this line to .env:   FORM_SHEET_ID={sheet['spreadsheetId']}")
    print("2. In your Google Form: Responses > Link to Sheets > Select existing spreadsheet > pick this sheet.")
    print(sheet["spreadsheetUrl"])


def read_responses():
    """Return the response rows as dicts keyed by request field, oldest first."""
    sheet_id = os.getenv("FORM_SHEET_ID", "").strip()
    if not sheet_id:
        sys.exit("Set FORM_SHEET_ID in .env (run with --create-sheet first).")
    service = sheets_service()
    meta = service.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets(properties(title))").execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    tabs = service.spreadsheets().values().batchGet(
        spreadsheetId=sheet_id, ranges=[f"'{t}'" for t in titles],
        valueRenderOption="UNFORMATTED_VALUE", dateTimeRenderOption="SERIAL_NUMBER").execute()["valueRanges"]
    rows = next((t.get("values", []) for t in tabs if t.get("values") and t["values"][0][0] == "Timestamp"), None)
    if rows is None:
        sys.exit("No form responses tab found (a tab whose first column is 'Timestamp'). Is the Form linked?")

    header = [str(h).strip().lower() for h in rows[0]]
    columns = {}
    for field, phrase in QUESTIONS.items():
        hits = [i for i, h in enumerate(header) if phrase in h]
        if hits:
            columns[field] = hits[0]
        elif field not in OPTIONAL:
            sys.exit(f"No Form question containing '{phrase}' (needed for {field}). Question titles: {rows[0][1:]}")

    responses = []
    for row in rows[1:]:
        if not row or row[0] == "":
            continue
        cell = lambda i: row[i] if i < len(row) else ""
        resp = {field: cell(i) for field, i in columns.items()}
        resp["response_id"] = (SERIAL_EPOCH + timedelta(days=float(row[0]))).strftime("%Y-%m-%dT%H:%M:%S")
        responses.append(resp)
    return responses


def split_list(value, pattern):
    return [v.strip() for v in re.split(pattern, str(value)) if v.strip()]


def to_request(resp):
    start = resp["start_date"]
    if isinstance(start, (int, float)):
        start = (SERIAL_EPOCH + timedelta(days=start)).date().isoformat()
    days = resp["num_days"]
    return {
        "response_id": resp["response_id"],
        "traveler_name": str(resp["traveler_name"]).strip(),
        "traveler_email": str(resp["traveler_email"]).strip(),
        "destination": str(resp["destination"]).strip(),
        "origin_city": str(resp["origin_city"]).strip(),
        "start_date": str(start).strip(),
        "num_days": int(days) if isinstance(days, (int, float)) else days,
        "what_they_like": split_list(resp["what_they_like"], r"[\n,;]"),  # checkboxes arrive comma-separated
        "why_visiting": str(resp["why_visiting"]).strip(),
        "trip_goals": split_list(resp["trip_goals"], r"\n"),  # goals often contain commas
        "budget_level": str(resp["budget_level"]).strip().lower(),
        "group_type": str(resp["group_type"]).strip(),
        "pace": str(resp["pace"]).strip().lower(),
        "special_needs": str(resp.get("special_needs", "")).strip(),
    }


def load_done():
    return set(json.loads(DONE_FILE.read_text(encoding="utf-8"))) if DONE_FILE.exists() else set()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if arg == "--create-sheet":
            return create_sheet()
        if arg == "--done":
            if len(sys.argv) < 3:
                sys.exit("Usage: fetch_form_requests.py --done <response_id>")
            done = load_done() | {sys.argv[2]}
            DONE_FILE.write_text(json.dumps(sorted(done), indent=2), encoding="utf-8")
            return print(f"OK: marked {sys.argv[2]} as planned.")

        done = load_done()
        pending = [r for r in read_responses() if r["response_id"] not in done]
    except HttpError as e:
        sys.exit(f"Google API error: {e}")

    if not pending:
        return print("No pending trip requests.")
    if arg == "--list":
        for r in map(to_request, pending):
            print(f"{r['response_id']}  {r['traveler_name']}: {r['destination']} from {r['start_date']}")
        return print(f"{len(pending)} pending.")
    if arg == "--id":
        if len(sys.argv) < 3:
            sys.exit("Usage: fetch_form_requests.py --id <response_id>")
        match = [r for r in pending if r["response_id"] == sys.argv[2]]
        if not match:
            sys.exit(f"{sys.argv[2]} is not a pending request (already planned, or no such response).")
        pending = match + [r for r in pending if r is not match[0]]

    req = to_request(pending[0])
    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(req, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {req['traveler_name']}: {req['destination']} from {req['start_date']} ({len(pending) - 1} more pending)")
    print(f"response_id: {req['response_id']}")
    print(OUT_FILE)


if __name__ == "__main__":
    main()
