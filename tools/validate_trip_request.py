"""Validate a trip request and write a normalized copy for the planner workflow.

Usage:
    python tools/validate_trip_request.py [inputs/trip_request.json]

Writes .tmp/<trip_slug>/request.normalized.json and prints its path.
Exits with code 1 and a list of problems if the request is invalid.
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "inputs" / "trip_request.json"

REQUIRED_TEXT = ["traveler_name", "destination", "origin_city", "why_visiting"]
REQUIRED_LISTS = ["what_they_like", "trip_goals"]
ENUMS = {
    "budget_level": {"budget", "mid-range", "luxury"},
    "group_type": {"solo", "couple", "family", "friends"},
    "pace": {"relaxed", "balanced", "packed"},
}
MAX_DAYS = 30


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def match_enum(value, allowed):
    """Accept an exact value, or descriptive text naming exactly one allowed value ('family of 4 people')."""
    value = str(value or "").strip().lower()
    if value in allowed:
        return value
    hits = [a for a in allowed if re.search(rf"\b{re.escape(a)}\b", value)]
    return hits[0] if len(hits) == 1 else None


def validate(req):
    errors = []

    for field in REQUIRED_TEXT:
        value = req.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"'{field}' is required and must be non-empty text.")

    for field in REQUIRED_LISTS:
        value = req.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"'{field}' must be a non-empty list.")
        elif not all(isinstance(v, str) and v.strip() for v in value):
            errors.append(f"Every item in '{field}' must be non-empty text.")

    for field, allowed in ENUMS.items():
        if not match_enum(req.get(field), allowed):
            errors.append(f"'{field}' must be one of: {', '.join(sorted(allowed))} (got '{req.get(field)}').")

    email = str(req.get("traveler_email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append(f"'traveler_email' doesn't look like an email address (got '{email}').")

    num_days = req.get("num_days")
    if not isinstance(num_days, int) or isinstance(num_days, bool) or not 1 <= num_days <= MAX_DAYS:
        errors.append(f"'num_days' must be a whole number from 1 to {MAX_DAYS} (got {num_days!r}).")

    start = None
    try:
        start = date.fromisoformat(str(req.get("start_date", "")))
    except ValueError:
        errors.append(f"'start_date' must be YYYY-MM-DD (got '{req.get('start_date')}').")

    return errors, start


def normalize(req, start):
    num_days = req["num_days"]
    dates = [(start + timedelta(days=i)).isoformat() for i in range(num_days)]
    destination_city = req["destination"].split(",")[0]
    return {
        "traveler_name": req["traveler_name"].strip(),
        "traveler_email": str(req.get("traveler_email") or "").strip().lower(),
        "destination": req["destination"].strip(),
        "origin_city": req["origin_city"].strip(),
        "start_date": dates[0],
        "end_date": dates[-1],
        "num_days": num_days,
        "trip_dates": dates,
        "what_they_like": [v.strip() for v in req["what_they_like"]],
        "why_visiting": req["why_visiting"].strip(),
        "trip_goals": [v.strip() for v in req["trip_goals"]],
        "budget_level": match_enum(req["budget_level"], ENUMS["budget_level"]),
        "group_type": match_enum(req["group_type"], ENUMS["group_type"]),
        "group_detail": req["group_type"].strip(),
        "pace": match_enum(req["pace"], ENUMS["pace"]),
        "special_needs": str(req.get("special_needs") or "").strip(),
        # Traveller name keeps plans unique: they all share one Drive folder.
        "trip_slug": f"{slugify(req['traveler_name'])}_{slugify(destination_city)}_{dates[0]}",
        "days_until_trip": (start - date.today()).days,
    }


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    if not path.exists():
        print(f"Trip request not found: {path}\nCopy inputs/trip_request.template.json to inputs/trip_request.json and fill it in.")
        sys.exit(1)

    try:
        req = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {path}: {e}")
        sys.exit(1)

    errors, start = validate(req)
    if errors:
        print("Trip request has problems:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    normalized = normalize(req, start)
    out_dir = ROOT / ".tmp" / normalized["trip_slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "request.normalized.json"
    out_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK: {normalized['destination']}, {normalized['start_date']} to {normalized['end_date']} ({normalized['num_days']} days)")
    if not normalized["traveler_email"]:
        print("NOTE: no traveler_email, so the PDF can't be uploaded to Google Drive (it will still be saved locally).")
    if normalized["days_until_trip"] < 0:
        print("WARNING: start_date is in the past.")
    elif normalized["days_until_trip"] > 120:
        print("NOTE: trip is 4+ months away; event listings may be incomplete. Mark unconfirmed events as tentative.")
    print(out_path)


if __name__ == "__main__":
    main()
