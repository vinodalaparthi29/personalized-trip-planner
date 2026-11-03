---
name: plan-trips
description: Plan the next pending trip request from the Google Form and email the PDF to the traveller. Use when the user says /plan-trips, "plan the next trip", or "check the form".
---

# Plan the next trip from the form

Plans **one** request per run, to keep each session's context (and token use) small.
`tools/auto_plan.py` also runs this skill unattended (via `claude -p`) for each new form response.

1. `.venv\Scripts\python.exe tools/fetch_form_requests.py` (if you were given a response_id, add `--id <response_id>`)
   - "No pending trip requests." → tell the user and stop.
   - Otherwise it wrote `inputs/trip_request.json`; note the `response_id` it printed.
2. Follow `workflows/plan_personalized_trip.md` from step 1, with these changes:
   - The traveller isn't here to answer questions. If something is vague, make a sensible assumption and
     state it in the plan's `summary` instead of asking.
   - Keep to the workflow's **Token budget** section.
   - For delivery (step 6), run `upload_to_drive.py .tmp/<trip_slug> --no-share` (backup copy and link),
     then `send_plan_email.py .tmp/<trip_slug>` (emails the PDF to the traveller, BCC the owner).
3. Only after the email succeeds, run `.venv\Scripts\python.exe tools/fetch_form_requests.py --done <response_id>`.
   If the email fails, stop **without** `--done` and report the error, so the request is retried.
   A failed Drive upload doesn't block the email.
4. Reply in 3 lines: who it was for, the Drive link, and how many requests are still pending.
   If more are pending, suggest `/clear` then `/plan-trips` for the next one.

When running unattended, nobody can reply: never ask questions or wait for confirmation, and don't open files
for review. Follow the steps and finish.
