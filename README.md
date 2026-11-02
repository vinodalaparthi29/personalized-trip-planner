# Personalized Trip Planner

Turns a short trip request into a polished PDF travel plan: events happening during your dates, a day-by-day
itinerary sized to your trip, how to get to each place, and why each pick fits *you*.

It's built on the **WAT pattern** (Workflows, Agents, Tools):

- `workflows/`: a plain-language SOP for the whole job ([plan_personalized_trip.md](workflows/plan_personalized_trip.md))
- **Agent**: [Claude Code](https://claude.com/claude-code) reads the workflow, does the web research and writes the itinerary
- `tools/`: deterministic Python scripts that validate, render the PDF and deliver it via Google Drive

```
Google Form ─► fetch_form_requests.py ─► validate_trip_request.py ─► Claude researches & plans
   ─► validate_itinerary.py ─► render_trip_pdf.py ─► upload_to_drive.py (shared with the traveller)
```

## Ways to use it

### 1. Ask for a plan (no setup)
Fill in the trip request form you were sent. Your plan arrives in your Gmail as a Google Drive share,
usually within a day or two. Use an email address that has a Google account.

### 2. Run it yourself
You need [Claude Code](https://claude.com/claude-code) (a Claude Pro plan or higher) and Python 3.10+.

```bash
git clone https://github.com/vinodalaparthi29/personalized-trip-planner.git
cd personalized-trip-planner
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip install -r requirements.txt
cp inputs/trip_request.template.json inputs/trip_request.json   # then edit it
claude
```

Then tell Claude: *"Plan my trip using workflows/plan_personalized_trip.md"*. The PDF is saved in `outputs/`.
Google Drive delivery is optional. Skip it, or do the Google setup below.

## Request fields

| Field | Example |
|---|---|
| `traveler_name` | Asha |
| `traveler_email` | asha@gmail.com (optional, for Drive delivery) |
| `destination` / `origin_city` | Lisbon, Portugal / Hyderabad, India |
| `start_date` / `num_days` | 2027-03-10 / 5 (1–30) |
| `what_they_like` / `trip_goals` | lists of short phrases |
| `why_visiting` | free text |
| `budget_level` | budget, mid-range, luxury |
| `group_type` | solo, couple, family, friends |
| `pace` | relaxed, balanced, packed |
| `special_needs` | optional: diet, mobility, kids' ages |

## Google setup (for Drive delivery and the form)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the
   **Google Drive API** and **Google Sheets API**.
2. Set up the OAuth consent screen with only the `drive.file` scope, and publish it ("In production").
3. Create an OAuth client of type **TVs and Limited Input devices**, download it, and save it as `credentials.json`
   in the project root.
4. Copy `.env.example` to `.env` and set `OWNER_EMAIL` to your Google account.
5. Check it: `python tools/upload_to_drive.py --check-credentials`. The first real upload asks you to sign in
   once with a URL and code.

Plans are stored in a `Travel Plans` folder in your Drive and shared view-only with each traveller.
The app can only see files it created.

### Taking requests through a Google Form

1. Run `python tools/fetch_form_requests.py --create-sheet` and put the printed ID in `.env` as `FORM_SHEET_ID`.
2. Create a Google Form whose question titles **contain** these phrases (any wording around them is fine):

   | Question title contains | Type |
   |---|---|
   | `your name` | Short answer |
   | `mail` (e.g. "Email" or "Gmail address") | Short answer |
   | `destination` | Short answer, e.g. "Destination (city, country)" |
   | `travelling from` | Short answer |
   | `start date` | Date |
   | `number of days` | Short answer, number 1–30 |
   | `things you like` | Paragraph (one per line) or Checkboxes |
   | `why are you visiting` | Paragraph |
   | `get out of this trip` | Paragraph, one goal per line |
   | `budget` | Multiple choice: budget / mid-range / luxury |
   | `who is travelling` | Multiple choice: solo / couple / family / friends |
   | `pace` | Multiple choice: relaxed / balanced / packed |
   | `special needs` | Paragraph (optional) |

3. In the form: **Responses → Link to Sheets → Select existing spreadsheet** and pick "Trip Planner Requests".
4. Share the form link. When requests come in, open Claude Code here and run **`/plan-trips`**.
   It plans one request per run; use `/clear` between trips to keep token use low.

## Project layout

```
tools/        Python scripts (validation, PDF rendering, Google Drive/Sheets)
workflows/    The SOP Claude follows
inputs/       trip_request.template.json (your own requests are gitignored)
.claude/      the /plan-trips skill
.tmp/         intermediate files (gitignored)
outputs/      generated PDFs (gitignored)
```

Secrets (`.env`, `credentials.json`, `tokens/`) are gitignored and never committed.
