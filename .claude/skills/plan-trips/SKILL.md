---
name: plan-trips
description: Plan the next pending trip request from the Google Form and deliver the PDF to the traveller. Use when the user says /plan-trips, "plan the next trip", or "check the form".
---

# Plan the next trip from the form

Plans **one** request per run, to keep each session's context (and token use) small.

1. `.venv\Scripts\python.exe tools/fetch_form_requests.py`
   - "No pending trip requests." → tell the user and stop.
   - Otherwise it wrote `inputs/trip_request.json`; note the `response_id` it printed.
2. Follow `workflows/plan_personalized_trip.md` from step 1, with these changes:
   - The traveller isn't here to answer questions. If something is vague, make a sensible assumption and
     state it in the plan's `summary` instead of asking.
   - Keep to the workflow's **Token budget** section.
3. After the upload succeeds (or the user confirms they'll send the PDF themselves), run
   `.venv\Scripts\python.exe tools/fetch_form_requests.py --done <response_id>`.
4. Reply in 3 lines: who it was for, the Drive link, and how many requests are still pending.
   If more are pending, suggest `/clear` then `/plan-trips` for the next one.
