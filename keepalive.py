"""Keeps the scheduled jobs running when GitHub's own timer runs late or skips.

GitHub starts scheduled jobs late, and on a quiet repository it can skip most of
them. This file gives every job three more ways to get started, so no single
missed timer leaves a board frozen:

  python keepalive.py next       Last step of the status job. Starts the next
                                 status job, so the chain never waits for the timer.
  python keepalive.py ticker     Runs beside the status loop. Every few minutes it
                                 reads the cron lines in .github/workflows/ and
                                 starts any job whose time has passed with no run.
  python keepalive.py watchdog   Last step of every other job. Starts the status
                                 job if none is running, then does one ticker pass.
  python keepalive.py alert      Runs when a job fails. Posts one line to Discord
                                 if the DISCORD_ALERT_WEBHOOK_URL secret exists.
  python keepalive.py save "Commit message" [folder ...]
                                 Commits changed files (default folder: state) back
                                 to the repository, trying again if another job
                                 pushed at the same moment. Without the retry, two
                                 saves landing together made one job fail and lose
                                 its Discord message ids.

Nothing here can fail a job: every problem is printed and the command exits 0.
The timers in the workflow files stay as they are. They are now the backup.

Off switch: disable the workflow on the Actions tab (or cancel a run). A
disabled workflow cannot be started by this file, and a cancelled status job
does not start the next one.

Settings (environment variables, set by GitHub or in the workflow files):
  GITHUB_TOKEN, GITHUB_REPOSITORY   set in the workflow step; needs "actions: write"
  KEEPALIVE_STATUS_FILE     the long-running job's workflow file (default status.yml)
  KEEPALIVE_CHECK_SECONDS   seconds between ticker passes (default 240)
  KEEPALIVE_GRACE_MINUTES   how late GitHub's timer may be before we step in (default 4)
  DISCORD_ALERT_WEBHOOK_URL optional secret: a webhook on a private admin channel
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
BRANCH = os.environ.get("KEEPALIVE_BRANCH", "main")
STATUS_FILE = os.environ.get("KEEPALIVE_STATUS_FILE", "status.yml")
CHECK_SECONDS = max(60, int(os.environ.get("KEEPALIVE_CHECK_SECONDS", "") or 240))
GRACE = timedelta(minutes=float(os.environ.get("KEEPALIVE_GRACE_MINUTES", "") or 4))
LOOK_BACK = timedelta(days=6)          # a weekly job missed on Monday is still started by Sunday
ALERT_WEBHOOK = os.environ.get("DISCORD_ALERT_WEBHOOK_URL", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS = os.path.join(HERE, ".github", "workflows")
WAITING = ("queued", "pending", "waiting", "requested")
ACTIVE = WAITING + ("in_progress",)
UTC = timezone.utc


def say(message):
    print("keepalive: " + message, flush=True)


def api(method, path, body=None):
    """One call to the GitHub API for this repository. Returns the parsed answer."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}/repos/{REPO}{path}", data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "keepalive (GitHub Actions)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def when(iso):
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


def runs(workflow_file, count=10):
    """The newest runs of one workflow, newest first."""
    return api("GET", f"/actions/workflows/{workflow_file}/runs?per_page={count}").get("workflow_runs") or []


def start(workflow_file, why):
    """Start one workflow by its file name. Returns True if GitHub accepted it."""
    try:
        api("POST", f"/actions/workflows/{workflow_file}/dispatches", {"ref": BRANCH})
        say(f"started {workflow_file} ({why}).")
        return True
    except urllib.error.HTTPError as e:
        hint = ""
        if e.code == 403:
            hint = ' Check that the job has "actions: write" under permissions.'
        elif e.code in (404, 422):
            hint = " The workflow may be disabled or have no manual trigger."
        say(f"could not start {workflow_file}: HTTP {e.code}.{hint}")
    except Exception as e:  # noqa: BLE001 - never fail the job over this
        say(f"could not start {workflow_file}: {type(e).__name__}.")
    return False


# ---- reading the cron lines -------------------------------------------------

def _field(text, low, high):
    """One cron field ('*', '*/15', '7,22', '1-5') as a set of numbers."""
    out = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
        if part in ("*", ""):
            a, b = low, high
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return out


def parse_cron(line):
    """'7 15 * * 1' -> (minutes, hours, days of month, months, weekdays) or None."""
    parts = line.split()
    if len(parts) != 5:
        return None
    try:
        minute, hour, dom, month = (_field(p, lo, hi) for p, (lo, hi) in
                                    zip(parts[:4], ((0, 59), (0, 23), (1, 31), (1, 12))))
        dow = {d % 7 for d in _field(parts[4], 0, 7)}   # 0 and 7 both mean Sunday
    except ValueError:
        return None   # names like MON or anything unusual: leave that line to GitHub
    return minute, hour, dom, month, dow, parts[2] == "*", parts[4] == "*"


def matches(cron, t):
    minute, hour, dom, month, dow, any_dom, any_dow = cron
    if t.minute not in minute or t.hour not in hour or t.month not in month:
        return False
    dom_ok, dow_ok = t.day in dom, (t.weekday() + 1) % 7 in dow
    if any_dom or any_dow:
        return dom_ok and dow_ok
    return dom_ok or dow_ok   # cron rule: with both set, either one is enough


def last_due(crons, now):
    """The newest scheduled time at or before now - GRACE, or None."""
    t = (now - GRACE).replace(second=0, microsecond=0)
    stop = now - LOOK_BACK
    while t >= stop:
        if any(matches(c, t) for c in crons):
            return t
        t -= timedelta(minutes=1)
    return None


def schedules():
    """{workflow file name: [parsed cron lines]} for every workflow with a timer
    and a manual trigger, read from the workflow files themselves."""
    found = {}
    for path in sorted(glob.glob(os.path.join(WORKFLOWS, "*.y*ml"))):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if "workflow_dispatch" not in text:
            continue
        crons = [c for c in (parse_cron(m) for m in
                             re.findall(r'^\s*-\s*cron:\s*["\']([^"\']+)["\']', text, re.M)) if c]
        if crons:
            found[os.path.basename(path)] = crons
    return found


# ---- the four commands ------------------------------------------------------

def catch_up(done, skip=()):
    """Start every job whose scheduled time has passed with no run since.
    done remembers {workflow file: scheduled time already handled}."""
    now = datetime.now(UTC)
    for name, crons in schedules().items():
        if name == STATUS_FILE or name in skip:
            continue   # the status job is kept going by "next" and "watchdog"
        due = last_due(crons, now)
        if not due or done.get(name) == due:
            continue
        try:
            recent = runs(name, 5)
        except Exception as e:  # noqa: BLE001
            say(f"could not read the runs of {name} ({type(e).__name__}); trying again later.")
            continue
        covered = any(r.get("status") in ACTIVE or when(r["created_at"]) >= due - timedelta(minutes=1)
                      for r in recent)
        if covered or start(name, f"its {due:%a %H:%M} UTC run never started"):
            done[name] = due


def status_alive():
    """True if a status job is running or waiting to run."""
    return any(r.get("status") in ACTIVE for r in runs(STATUS_FILE, 8))


def cmd_next():
    recent = runs(STATUS_FILE, 10)
    mine = os.environ.get("GITHUB_RUN_ID", "")
    others = [r for r in recent if str(r.get("id")) != mine]
    if any(r.get("status") in WAITING for r in others):
        say("a status job is already waiting in line; nothing to start.")
        return
    # Stop a broken job from restarting itself for ever: three failures in a row
    # that each lasted under ten minutes means something needs a person.
    finished = [r for r in others if r.get("status") == "completed"][:3]
    quick_fail = [r for r in finished if r.get("conclusion") == "failure"
                  and (when(r["updated_at"]) - when(r.get("run_started_at") or r["created_at"])) < timedelta(minutes=10)]
    this_failed = os.environ.get("JOB_STATUS", "success") == "failure"
    if this_failed and len(finished) == 3 and len(quick_fail) == 3:
        message = "The status job failed four times in a row, so it was not restarted. The timer will try again later."
        say(message)
        print(f"::error::{message}")
        alert(message)
        return
    if this_failed:
        time.sleep(60)   # give a short outage a moment before trying again
    start(STATUS_FILE, "handing over to the next status job")


def cmd_ticker():
    done = {}
    say(f"watching the timers of {', '.join(n for n in schedules() if n != STATUS_FILE) or 'no other jobs'}.")
    while True:
        try:
            catch_up(done)
        except Exception as e:  # noqa: BLE001
            say(f"a pass was skipped ({type(e).__name__}).")
        time.sleep(CHECK_SECONDS)


def cmd_watchdog():
    own = os.path.basename((os.environ.get("GITHUB_WORKFLOW_REF", "").split("@")[0]))
    if own != STATUS_FILE:
        if not status_alive():
            start(STATUS_FILE, "no status job was running")
        else:
            say("the status job is running.")
    catch_up({}, skip=(own,))


def alert(message):
    """One line to the admin channel. Does nothing until the secret exists."""
    if not ALERT_WEBHOOK:
        return
    link = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{REPO}/actions"
    if os.environ.get("GITHUB_RUN_ID"):
        link += "/runs/" + os.environ["GITHUB_RUN_ID"]
    body = json.dumps({"content": f"⚠ **{REPO.split('/')[-1]}**: {message} [Open the run](<{link}>)"[:1900],
                       "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(ALERT_WEBHOOK, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "keepalive (GitHub Actions)"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:  # noqa: BLE001 - never print the webhook address
        say(f"the alert could not be sent ({type(e).__name__}).")


def git(*args):
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)


def cmd_save():
    message = sys.argv[2] if len(sys.argv) > 2 else "Save state"
    folders = sys.argv[3:] or ["state"]
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "--", *folders)
    if git("diff", "--cached", "--quiet").returncode == 0:
        return print("Nothing to save.", flush=True)
    if git("commit", "-q", "-m", message).returncode != 0:
        return print("::warning::The state could not be committed.", flush=True)
    for attempt in range(1, 7):
        if git("pull", "-q", "--rebase", "--autostash").returncode == 0 and git("push", "-q").returncode == 0:
            return print(f"Saved (attempt {attempt}).", flush=True)
        git("rebase", "--abort")
        print(f"Save attempt {attempt} did not go through; waiting to try again.", flush=True)
        time.sleep(attempt * 5)
    print("::warning::The state could not be saved after 6 attempts. The next run will save it.", flush=True)


def cmd_alert():
    alert(f'The job "{os.environ.get("GITHUB_WORKFLOW", "?")}" failed.')


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "alert":
        return cmd_alert()
    if command == "save":
        return cmd_save()
    if not TOKEN or not REPO:
        return say("GITHUB_TOKEN or GITHUB_REPOSITORY is not set; nothing done.")
    {"next": cmd_next, "ticker": cmd_ticker, "watchdog": cmd_watchdog}.get(
        command, lambda: say("use: next | ticker | watchdog | alert | save"))()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001 - this file must never fail a job
        say(f"stopped early ({type(e).__name__}: {str(e)[:200]}).")
    sys.exit(0)
