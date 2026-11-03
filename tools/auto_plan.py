"""Unattended runner: plan and email every new Google Form request. Windows Task Scheduler calls this.

Usage:
    python tools/auto_plan.py             # plan up to MAX_PER_RUN pending requests, one Claude session each
    python tools/auto_plan.py --dry-run   # show what would be planned, without starting Claude

Checking the sheet is plain Python, so runs with nothing pending cost no Claude tokens. Each request gets a
fresh headless `claude -p` session that runs the plan-trips skill for that response_id. A request is done
once the skill marks it with fetch_form_requests.py --done (after the email is sent). Requests that fail
MAX_ATTEMPTS times are skipped and the owner is emailed, so one bad response can't burn tokens every run.

Logs: .tmp/logs/auto_plan.log (runner) and .tmp/logs/<response_id>.log (each Claude session).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from fetch_form_requests import load_done, read_responses
from google_auth import ROOT

MAX_PER_RUN = 3
MAX_ATTEMPTS = 2
SESSION_TIMEOUT = 60 * 60  # seconds per trip
LOCK_FILE = ROOT / ".tmp" / "auto_plan.lock"
LOCK_STALE = 2 * 60 * 60  # a lock older than this is left over from a crashed run
LOG_DIR = ROOT / ".tmp" / "logs"
ATTEMPTS_FILE = ROOT / "inputs" / "auto_attempts.json"

# What the headless session may do without asking: run the project's tools, search, and write plan files.
ALLOWED_TOOLS = [
    "Skill",
    "Read",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Edit(.tmp/**)",  # covers Write too
    "Bash(.venv/Scripts/python.exe tools/*)",
    "Bash(.venv\\Scripts\\python.exe tools/*)",
    "PowerShell(.venv\\Scripts\\python.exe tools/*)",
    "PowerShell(.venv/Scripts/python.exe tools/*)",
]
PROMPT = ("Run the plan-trips skill for response_id {rid}. You are running unattended: nobody can answer "
          "questions or approve anything, so never wait for a reply.")


def log(msg):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    if sys.stdout:  # None under pythonw (Task Scheduler)
        print(line, flush=True)
    with open(LOG_DIR / "auto_plan.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def take_lock():
    LOCK_FILE.parent.mkdir(exist_ok=True)
    if LOCK_FILE.exists() and time.time() - LOCK_FILE.stat().st_mtime < LOCK_STALE:
        return False
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def load_attempts():
    return json.loads(ATTEMPTS_FILE.read_text(encoding="utf-8")) if ATTEMPTS_FILE.exists() else {}


def save_attempts(attempts):
    ATTEMPTS_FILE.parent.mkdir(exist_ok=True)
    ATTEMPTS_FILE.write_text(json.dumps(attempts, indent=2), encoding="utf-8")


def claude_exe():
    found = shutil.which("claude") or shutil.which("claude.exe")
    if found:
        return found
    default = Path.home() / ".local" / "bin" / "claude.exe"  # Task Scheduler may not have the user's PATH
    if default.exists():
        return str(default)
    sys.exit("claude not found on PATH or in ~/.local/bin.")


def run_session(rid):
    """Run one headless Claude session for this request; return True if it ended up marked done."""
    cmd = [claude_exe(), "-p", PROMPT.format(rid=rid), "--allowedTools", *ALLOWED_TOOLS]
    session_log = LOG_DIR / f"{rid.replace(':', '-')}.log"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(session_log, "a", encoding="utf-8") as out:
        out.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        out.flush()
        try:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  timeout=SESSION_TIMEOUT, creationflags=flags)
            log(f"{rid}: claude exited with code {proc.returncode} (log: {session_log.name})")
        except subprocess.TimeoutExpired:
            log(f"{rid}: claude timed out after {SESSION_TIMEOUT // 60} min")
    return rid in load_done()


def give_up(rid, req):
    log(f"{rid}: failed {MAX_ATTEMPTS} times, skipping it from now on")
    try:
        from send_plan_email import notify_owner
        notify_owner(f"Trip planner: could not plan {req.get('traveler_name')}'s request",
                     f"Response {rid} ({req.get('traveler_name')}: {req.get('destination')}) failed "
                     f"{MAX_ATTEMPTS} times and won't be retried automatically.\n"
                     f"See .tmp/logs/{rid.replace(':', '-')}.log. To retry, remove it from "
                     "inputs/auto_attempts.json, or plan it by hand with /plan-trips.")
    except SystemExit as e:  # email itself failed; the log still has it
        log(f"{rid}: could not email the owner ({e})")


def main():
    dry_run = "--dry-run" in sys.argv
    if not dry_run and not take_lock():
        return log("Another run is still going; skipping this one.")
    try:
        try:
            done = load_done()
            pending = [r for r in read_responses() if r["response_id"] not in done]
        except SystemExit as e:  # read_responses exits with a message on setup problems
            return log(f"Could not read the form sheet: {e}")
        except Exception as e:  # network errors, expired sign-in, etc.
            return log(f"Could not read the form sheet: {e!r}")

        attempts = load_attempts()
        todo = [r for r in pending if attempts.get(r["response_id"], 0) < MAX_ATTEMPTS][:MAX_PER_RUN]
        if not todo:
            if dry_run:
                print(f"Nothing to plan ({len(pending)} pending, all skipped after {MAX_ATTEMPTS} failures).")
            return
        if dry_run:
            for r in todo:
                print(f"Would plan {r['response_id']}  {r['traveler_name']}: {r['destination']}")
            return

        for r in todo:
            rid = r["response_id"]
            attempts[rid] = attempts.get(rid, 0) + 1
            save_attempts(attempts)
            log(f"{rid}: planning {r['traveler_name']}: {r['destination']} (attempt {attempts[rid]})")
            if run_session(rid):
                log(f"{rid}: done")
                attempts.pop(rid, None)
                save_attempts(attempts)
            elif attempts[rid] >= MAX_ATTEMPTS:
                give_up(rid, r)
            else:
                log(f"{rid}: not finished; will retry next run")
    finally:
        if not dry_run:
            LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
