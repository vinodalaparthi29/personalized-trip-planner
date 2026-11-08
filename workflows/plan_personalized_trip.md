# Workflow: Personalized Event & Travel Planner

## Objective
Turn one traveller's trip request into a compact, deeply personalized PDF travel plan with photos, 7 pages at most,
covering: events not to miss during their dates, a day-by-day plan for exactly the number of days requested,
how to get to each place, what to do there, and why each item fits *this* traveller.

## Required inputs
`inputs/trip_request.json` (copy from `inputs/trip_request.template.json`):

| Field | Notes |
|---|---|
| `traveler_name` | Used on the cover and headers |
| `traveler_email` | The traveller's Google account; the PDF in the owner's Drive is shared with it. Optional: without it you get a link to send yourself |
| `destination` | "City, Country" works best |
| `origin_city` | Where they travel from (for the "Getting there" section) |
| `start_date` | `YYYY-MM-DD` |
| `num_days` | 1–30 |
| `what_they_like` | List of short phrases |
| `why_visiting` | Free text |
| `trip_goals` | List of short notes on what they want to achieve |
| `budget_level` | `budget` / `mid-range` / `luxury` |
| `group_type` | `solo` / `couple` / `family` / `friends`. Descriptive text like "family of 4 people" is accepted; the full text is kept as `group_detail` |
| `pace` | `relaxed` / `balanced` / `packed` |
| `special_needs` | Optional: dietary, mobility, kids' ages, etc. |

If the file is missing or vague (e.g. likes = "nice things"), ask the user before researching.
Requests from the Google Form arrive via `tools/fetch_form_requests.py` (the `/plan-trips` skill drives this).

## Tools
| Step | Tool |
|---|---|
| Pull a request from the Google Form | `tools/fetch_form_requests.py` |
| Validate & normalize request | `tools/validate_trip_request.py` |
| Research | Agent's built-in web search (no API key needed) |
| Check itinerary | `tools/validate_itinerary.py` |
| Download photos (Wikipedia / Wikimedia Commons, no key) | `tools/fetch_trip_photos.py` |
| Render PDF | `tools/render_trip_pdf.py` |
| Upload to owner's Drive and share with traveller | `tools/upload_to_drive.py` |
| Email the PDF to the traveller | `tools/send_plan_email.py` |
| Run all of this unattended for new form responses | `tools/auto_plan.py` (Task Scheduler) |

Run Python with the project venv: `.venv\Scripts\python.exe` (on macOS/Linux: `.venv/bin/python`).

## Token budget
Runs use the owner's Claude subscription, so keep them lean:
- Plan one trip per session; `/clear` between trips.
- About 12–15 web searches per trip. Run them in parallel and combine likes into one query where they overlap.
  Open a page only to confirm an event's dates or a key price, not for general reading.
- Write `itinerary.json` in one go, and when the validator reports problems, fix just those fields. Don't re-read
  files you just wrote, and don't open the PDF unless the renderer printed a warning.

## Steps

### 1. Validate the request
```
.venv\Scripts\python.exe tools/validate_trip_request.py inputs/trip_request.json
```
Prints the path of `.tmp/<trip_slug>/request.normalized.json`. Fix any errors with the user.
Note the `days_until_trip` warning: trips more than ~4 months out often have incomplete event listings.

### 2. Research (agent, web search)
Run searches in parallel where possible. Always include the destination **and the exact month/dates**.

1. **Events during the dates.** Queries like `"<city> events <Month Year>"`, `"<city> festival <Month Year>"`,
   `"<city> concerts <dates>"`, plus one per like (`"<city> <like> event <Month Year>"`).
   Keep only events that actually overlap the trip dates. Open the official or ticketing page to confirm the dates.
2. **Experiences for each like.** For every item in `what_they_like`, find 2–3 concrete places or activities
   (named venues, not generic categories).
3. **Goal-driven activities.** For every item in `trip_goals`, find something that directly achieves it
   (a class, a viewpoint, a quiet day, a specific experience).
4. **Getting there** from `origin_city`: the main modes, typical journey time, rough cost for the budget level.
5. **Getting around**: transit cards or passes, ride-hailing apps, walkability, and day-trip transport.
6. **Where to stay**: 2–3 areas that suit the budget, group type and likes.
7. **Food** that matches the likes, budget and `special_needs`.
8. **Practical**: typical weather for the dates, currency and payments, etiquette, safety, emergency number,
   and closures (e.g. museums closed on Mondays, public holidays during the dates).

Record every URL you rely on. They go into `sources` and into each event's `source_url`.

### 3. Build the plan
Write `.tmp/<trip_slug>/itinerary.json` following the schema below.

**Personalization rules (these are what make the plan good):**
- Every block and every event has a `why_for_you` sentence that names the traveller's specific like, goal or
  reason for visiting. Never write generic filler like "a must-see attraction".
- Every block's `serves` list holds the likes and goals it serves, **copied verbatim** from the request.
  Every like and every goal must be served at least once (the validator enforces this).
- Place each must-not-miss event on the day it actually happens, and build that day around it.
- Pace: `relaxed` means 1–2 main activities a day with free time; `balanced` means one per morning, afternoon
  and evening; `packed` means 3 blocks with extra stops described in `details`.
- Group fit: family days have shorter transfers and kid-friendly options; couples get evening highlights;
  friends get nightlife and group activities, as fits their likes.
- Arrival and departure days are lighter, and account for the travel time from `getting_there`.
- Put nearby places on the same day to cut down transit. Each `how_to_get_there` gives a concrete mode,
  the stop or landmark, and the time (e.g. "Metro Line 2 to Baixa-Chiado, 8 min walk").
- Costs are in local currency, with an approximate conversion to the traveller's home currency where useful.
- Every `food` price is a real amount per person (`₹800–1,200`), never a symbol tier (`₹₹`, `$$`) or "varies". Take it
  from the research, and if a place publishes no prices, give the typical range for that kind of place with "about".
  The only exception is a meal already paid for, such as "Included in the boat rate".

**Keep it short (the PDF is 7 pages at most, and travellers won't read more):**
- Word limits: `summary` 50, `why_for_you` 25, `how_to_get_there` 20, `details` 20, `tip` 15. At most 6 `food` entries.
- The renderer drops `details` and then `tip` when a trip won't fit, so anything the traveller must know
  (book ahead, closed on Mondays) goes in `how_to_get_there` or `practical.before_you_go`.

**Choose photos (they should show what's actually recommended):**
- `cover_photo`: the destination's best landscape. Each day's `photos`: up to 2, mixing landscapes, monuments and
  places on that day's plan. Each `food` entry's `photo`: the dish to order, since most restaurants have no free photo.
- Use the **exact English Wikipedia article title** (`Basilica of Bom Jesus`, `Fontainhas (quarter)`, `Xacuti`). No
  separate searching is needed. For a name shared by several places, add the location (`Blue Grotto, Capri`).

### 4. Validate
```
.venv\Scripts\python.exe tools/validate_itinerary.py .tmp/<trip_slug>
```
Fix every reported problem (missing likes or goals, wrong dates, missing fields) and re-run until it says OK.
Warnings don't block, but fix missing photos and text over the word limits, as they cost pages.

### 5. Fetch photos
```
.venv\Scripts\python.exe tools/fetch_trip_photos.py .tmp/<trip_slug>
```
Prints `title -> matched file` per photo. **Read the matched filenames:** if one is clearly the wrong place, change
that title in `itinerary.json` and re-run (photos already downloaded aren't fetched again). A skipped photo is fine;
the plan just goes without it. This step never blocks a trip, even if Wikimedia is down.

### 6. Render and check the PDF
```
.venv\Scripts\python.exe tools/render_trip_pdf.py .tmp/<trip_slug>
```
Output: `outputs/<trip_slug>_travel_plan.pdf`. It prints `pages=N density=K` (1 is the richest of 6 layouts; it picks
the richest that fits). The renderer's checks plus the validator cover day count and dates; only open the PDF if the
renderer printed a warning. If it warns about being over 7 pages, shorten the longest text and re-render. Unattended
runs should still deliver if that doesn't work.

### 7. Upload to the owner's Drive and share it with the traveller
```
.venv\Scripts\python.exe tools/upload_to_drive.py .tmp/<trip_slug>
```
- The PDF goes to `Travel Plans/` in the owner's Drive (`OWNER_EMAIL` in `.env`) and is shared view-only with
  `traveler_email`. Google emails the traveller the link, and they don't sign in to anything.
- The first run ever asks the **owner** to sign in once (URL + code; run it in the background and pass these on).
  The token is saved as `tokens/owner.json`.
- Re-running the same trip **replaces** the file, so the link stays the same and Drive keeps the old version.
- If sharing fails (e.g. the address has no Google account), the tool prints the link. Tell the user to set it to
  "Anyone with the link" in Drive and send it themselves (WhatsApp, email).
- If the upload fails, the local PDF in `outputs/` is still the deliverable. Report the failure and offer to retry.

**Form requests (`/plan-trips`) use email instead of the share:**
```
.venv\Scripts\python.exe tools/upload_to_drive.py .tmp/<trip_slug> --no-share
.venv\Scripts\python.exe tools/send_plan_email.py .tmp/<trip_slug>
```
- The PDF goes out as an attachment from the owner's Gmail (SMTP + `GMAIL_APP_PASSWORD`), BCC to the owner. This works
  for any address, not just Google accounts. The Drive upload is only a backup copy, and `--no-share` avoids a
  second email.
- Gmail goes through SMTP because the device sign-in flow can't grant Gmail scopes.
- `--to <addr>` sends to another address, for testing.

Finish by giving the user the Drive link (or the local path) and a 3–4 line summary.

## Automatic mode
`tools/auto_plan.py` runs every 15 min from Windows Task Scheduler (task "TripPlanner"; registration command in
README). It reads the response sheet in plain Python, so a run with nothing pending costs no tokens. For each new
response (max 3 per run) it starts a headless `claude -p` session that runs the plan-trips skill with that
`response_id`.
- A request counts as done only after the skill runs `--done`, which happens after the email is sent.
- A request is retried on the next run, and is skipped after 2 failed attempts. The owner is emailed when that
  happens; `inputs/auto_attempts.json` holds the counts, and deleting an entry re-enables it.
- Logs: `.tmp/logs/auto_plan.log` and `.tmp/logs/<response_id>.log`.
- The task runs only while the owner is logged in, because headless Claude needs the user's sign-in.
- It must be allowed to run on battery. Task Scheduler's default skips every run while a laptop is unplugged, and a
  skipped run leaves no trace in `auto_plan.log`. The log also stays silent when nothing is pending, so check
  `Get-ScheduledTaskInfo TripPlanner` (last run, missed runs) rather than judging by the log.
- The headless session's permissions are the `ALLOWED_TOOLS` list in `auto_plan.py` (project tools, web search, writes
  under `.tmp/`). If a session stalls on a denied tool, its log says so: add that tool to the list.

**One-time setup:** see README "Google setup". You need a Google Cloud project with the Drive and Sheets APIs enabled,
the consent screen published with only the `drive.file` scope, a "TVs and Limited Input devices" OAuth client saved
as `credentials.json`, and `OWNER_EMAIL` (plus `FORM_SHEET_ID` for the form) in `.env`.
To check it still works: `upload_to_drive.py --check-credentials`.

## itinerary.json schema
```json
{
  "summary": "2-3 sentences, personal, tied to why_visiting and the goals",
  "cover_photo": "Wikipedia article title",
  "no_events_note": "Only if must_not_miss_events is empty: why, and what to do instead",
  "must_not_miss_events": [{
    "name": "", "dates": ["YYYY-MM-DD"], "time": "19:00-23:00", "venue": "",
    "why_for_you": "", "how_to_get_there": "", "tickets": "price + where to buy",
    "tip": "optional", "status": "confirmed | tentative | recurring",
    "serves": ["verbatim like/goal"], "source_url": "https://..."
  }],
  "getting_there": {
    "overview": "",
    "options": [{"mode": "Flight", "details": "", "duration": "", "cost": ""}]
  },
  "getting_around": {"overview": "", "tips": [""]},
  "where_to_stay": [{"area": "", "why": "", "price_range": "", "example": "optional hotel name"}],
  "days": [{
    "date": "YYYY-MM-DD", "theme": "short title", "summary": "optional 1 sentence",
    "photos": ["Wikipedia article title", "up to 2"],
    "blocks": [{
      "time_of_day": "morning | afternoon | evening",
      "activity": "", "location": "", "details": "optional",
      "how_to_get_there": "", "duration": "", "cost": "",
      "why_for_you": "", "tip": "optional", "serves": ["verbatim like/goal"]
    }]
  }],
  "food": [{"name": "", "area": "", "what_to_order": "", "why_for_you": "", "price": "₹800–1,200 (amount per person)", "photo": "dish's Wikipedia article title"}],
  "goals_map": [{"goal": "verbatim goal", "how": "", "days": [1, 3]}],
  "practical": {
    "weather": "", "currency": "",
    "daily_budget": [{"item": "Accommodation", "cost": ""}],
    "before_you_go": ["visa, entry forms, bookings to make in advance"],
    "packing": [""], "etiquette": [""], "safety": [""], "emergency": ""
  },
  "sources": [{"title": "", "url": ""}]
}
```

## Edge cases
- **No events found for the dates:** leave `must_not_miss_events` empty and fill `no_events_note`. Lean on recurring
  experiences (weekly markets, nightly shows) and mark them `status: "recurring"` if you list them as events.
- **Trip far ahead (4+ months):** listings are often unpublished. Use last year's edition to judge likely
  events, mark them `tentative`, and say "verify closer to the date" in `tip`.
- **Very short stay (1–2 days):** focus on the single best thing for each like and skip day trips.
- **Long stay (10+ days):** add rest or flex days, group days by neighbourhood or region, and consider a base change.
  Long trips get fewer photos and briefer days to stay within 7 pages, so stick closely to the word limits.
- **A like that doesn't fit the destination** (e.g. "skiing" in Goa): offer the closest option and say so
  plainly in `why_for_you`. Don't pretend it fits.
- **Obscure destination, thin web data:** say so in the summary, and prefer fewer, well-sourced recommendations
  over invented ones. Never make up venues, events, prices or URLs.
- **Special needs:** check accessibility and dietary options for each pick, and mention it in `tip`.

## Lessons learned
- ReportLab's built-in Helvetica can't render ₹ and some accented characters, so the renderer registers a system
  Unicode font (Segoe UI/Arial on Windows, Arial on macOS, DejaVu Sans on Linux).
- Plans from everyone share one Drive folder, so `trip_slug` includes the traveller's name. Otherwise two people
  going to the same city on the same date would overwrite each other's PDF, and it would be shared with both.
- Drive delivery used to upload into each traveller's own Drive, but everyone having to approve a sign-in was too
  much friction. Now one owner token is used and the file is shared. Sheets are read with the same `drive.file` scope,
  which is why the form's response sheet must be created by `fetch_form_requests.py --create-sheet`.
- Section headings use `keepWithNext` so a heading never sits alone at the bottom of a page (first test run left
  "Sources" stranded on its own).
- Search results for future events are often blog estimates (e.g. Sunburn dates). Confirm on the organiser's or
  government page before marking an event `confirmed`; otherwise mark it `tentative`.
- Users may fill in `trip_request.template.json` directly instead of copying it. If `trip_request.json` is missing
  but the template has real values, copy it across and continue.
- Check the weekly rhythm of the destination: in the Maldives, public ferries don't run and museums close on
  Fridays, so Friday is the best day for a speedboat island transfer. Check for similar patterns elsewhere
  (Monday museum closures in Europe, Sabbath closures, etc.).
- Drive uses the **device sign-in flow** so travellers can approve from their own phone, without being at this
  computer. It needs an OAuth client of type "TVs and Limited Input devices"; a Desktop client fails with
  `invalid_client`. Device flow allows only a few Drive scopes, and `drive.file` is one of them.
- If the consent screen is ever set back to "Testing", travellers must be added as test users, and their saved
  approvals expire after 7 days (they'd have to approve again).
- `serves` matching ignores case and extra spaces but otherwise needs exact text, so copy likes and goals verbatim.
- PDFs used to run 11–17 pages (39 for a 30-day trip), mostly from forced page breaks and repeated information rather
  than the content itself. Sections now flow continuously, and the renderer steps down through densities to fit 7 pages.
- Wikimedia returns HTTP 429 with `Retry-After` after about 10 quick requests, so `fetch_trip_photos.py` batches title
  lookups, spaces out requests and honours that header. It needs a descriptive `User-Agent`; don't put an email in it.
- Wikipedia *search* gives wrong photos ("Viva Panjim" returned Goa Carnival), so lookups use exact titles. Lead images can
  be logos, which the tool filters out. Commons matches can still be the wrong place: "Blue Grotto" matched one in Malta,
  which is why the tool prints every matched filename for checking.
- Food prices written as `₹₹` or "varies" tell the traveller nothing, and 15 of 41 across the first 8 trips had no
  amount. The validator now warns on any food price without a number.
- Photo licences (mostly CC BY / CC BY-SA) require credit, so the PDF's last page lists author and licence per photo.
