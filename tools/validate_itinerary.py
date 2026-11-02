"""Check an itinerary.json against its trip request before rendering the PDF.

Usage:
    python tools/validate_itinerary.py .tmp/<trip_slug>

Expects request.normalized.json and itinerary.json in that folder.
Checks structure, dates, sources, and that every like and goal is covered.
Exits with code 1 and a list of problems if anything needs fixing.
"""

import json
import sys
from pathlib import Path

DAY_PARTS = {"morning", "afternoon", "evening"}
BLOCK_FIELDS = ["time_of_day", "activity", "location", "how_to_get_there", "why_for_you", "serves"]
EVENT_FIELDS = ["name", "dates", "venue", "why_for_you", "how_to_get_there", "tickets", "source_url", "status"]
TOP_LEVEL = ["summary", "must_not_miss_events", "getting_there", "getting_around",
             "where_to_stay", "days", "food", "goals_map", "practical", "sources"]


def norm(text):
    return " ".join(str(text).lower().split())


def check(req, it):
    errors, warnings = [], []

    for key in TOP_LEVEL:
        if key not in it:
            errors.append(f"Missing top-level key '{key}'.")
    if errors:
        return errors, warnings

    trip_dates = req["trip_dates"]
    likes = {norm(v): v for v in req["what_they_like"]}
    goals = {norm(v): v for v in req["trip_goals"]}
    served = set()

    days = it["days"]
    if len(days) != req["num_days"]:
        errors.append(f"Expected {req['num_days']} days, found {len(days)}.")
    for i, day in enumerate(days):
        label = f"Day {i + 1}"
        if i < len(trip_dates) and day.get("date") != trip_dates[i]:
            errors.append(f"{label} date is '{day.get('date')}', expected '{trip_dates[i]}'.")
        if not day.get("theme"):
            errors.append(f"{label} has no theme.")
        blocks = day.get("blocks") or []
        if not blocks:
            errors.append(f"{label} has no activity blocks.")
        for j, block in enumerate(blocks):
            where = f"{label}, block {j + 1}"
            for field in BLOCK_FIELDS:
                if not block.get(field):
                    errors.append(f"{where} is missing '{field}'.")
            if block.get("time_of_day") and block["time_of_day"].lower() not in DAY_PARTS:
                errors.append(f"{where} time_of_day must be morning/afternoon/evening.")
            for tag in block.get("serves") or []:
                key = norm(tag)
                if key not in likes and key not in goals:
                    errors.append(f"{where} serves '{tag}', which is not a like or goal from the request (copy them verbatim).")
                served.add(key)

    for i, event in enumerate(it["must_not_miss_events"]):
        where = f"Event {i + 1} ('{event.get('name', '?')}')"
        for field in EVENT_FIELDS:
            if not event.get(field):
                errors.append(f"{where} is missing '{field}'.")
        event_dates = event.get("dates") or []
        if event_dates and not any(d in trip_dates for d in event_dates):
            errors.append(f"{where} has no date inside the trip ({trip_dates[0]} to {trip_dates[-1]}).")
        if event.get("status") not in (None, "confirmed", "tentative", "recurring"):
            errors.append(f"{where} status must be confirmed/tentative/recurring.")
        for tag in event.get("serves") or []:
            served.add(norm(tag))
    if not it["must_not_miss_events"]:
        warnings.append("No must-not-miss events. Make sure the summary explains why.")

    for key, original in likes.items():
        if key not in served:
            errors.append(f"Like not covered by any activity or event: '{original}'.")
    for key, original in goals.items():
        if key not in served:
            errors.append(f"Goal not covered by any activity or event: '{original}'.")

    mapped_goals = {norm(g.get("goal", "")) for g in it["goals_map"]}
    for key, original in goals.items():
        if key not in mapped_goals:
            errors.append(f"goals_map has no entry for goal: '{original}'.")

    if not it["sources"]:
        errors.append("No sources listed.")
    if not it["food"]:
        warnings.append("No food recommendations.")

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    folder = Path(sys.argv[1])
    try:
        req = json.loads((folder / "request.normalized.json").read_text(encoding="utf-8"))
        it = json.loads((folder / "itinerary.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        print(f"Missing file: {e.filename}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)

    errors, warnings = check(req, it)
    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        print(f"Itinerary has {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("OK: itinerary is complete and covers every like and goal.")


if __name__ == "__main__":
    main()
