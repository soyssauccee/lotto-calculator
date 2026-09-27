"""Catch a draw's results soon after they're posted, and update the page then.

    python watch.py         watch tonight's draw: wait until just after it, then keep checking
    python watch.py --now   start checking at once (for a run started by hand)

GitHub starts scheduled workflows anywhere from minutes to hours late, and sometimes
skips them, so no single scheduled run can be counted on to be there at draw time.
Instead, the Draw watch workflow is scheduled several times on draw days, well ahead of
the 10:30 PM Eastern draw, and the first run to start keeps watch:

- It sleeps until just after draw time. A job can only run for 6 hours, so when the draw
  is further off than that, the run hands over before its time is up by starting a fresh
  run of the workflow (runs started that way begin at once) and exits.
- After the draw it scrapes every POLL_EVERY. When the lottery sites have something new
  (not just a fresh timestamp), it starts the Scrape workflow, which commits the data,
  redeploys the page and sends alerts, and waits for it.
- It stops once the night's results and next jackpots are all stored, or at noon the
  next day, after which the scheduled Scrape runs pick up the rest.

Runs that start while another is already watching exit at once, so the extra schedule
entries cost a minute each. Needs GITHUB_TOKEN (with actions: write), GITHUB_REPOSITORY
and GITHUB_RUN_ID, as set in the Draw watch workflow.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as clock, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from lottocalc import model, store

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
EASTERN = ZoneInfo("America/Toronto")
DRAW_TIME = clock(22, 30)  # both games, Eastern
FIRST_LOOK = timedelta(minutes=15)  # after the draw
GIVE_UP = clock(12, 0)  # the next day, Eastern
MAX_LEAD = timedelta(hours=14)  # don't start watching a draw further off than this
POLL_EVERY = timedelta(minutes=10)
RUN_BUDGET = timedelta(hours=5, minutes=30)  # then hand over; the job's timeout is 6 hours
SCRAPE_WAIT = timedelta(minutes=15)  # longest to wait for a Scrape run to finish
VOLATILE = {"scraped_at", "as_of"}  # change on every scrape, so they don't count as news
API = "https://api.github.com"


def game_settled(game, night, draws, next_doc):
    """Whether `night`'s draw of `game` is stored and the game's next jackpot is posted."""
    stored = any(d["game"] == game and d["draw_date"] == night.isoformat() for d in draws)
    info = next_doc.get(game) or {}
    posted = (info.get("draw_date") or "") > night.isoformat() and bool(info.get("draw_number"))
    return stored and posted


def pick_night(now, draws, next_doc):
    """(night, games) to watch: last night's draws until noon if they're still unsettled,
    otherwise tonight's. (None, []) when neither has a draw left to catch."""
    today = now.astimezone(EASTERN).date()
    nights = [today - timedelta(days=1), today] if now.astimezone(EASTERN).time() < GIVE_UP else [today]
    for night in nights:
        games = [g for g in model.GAMES if night.weekday() in model.DRAW_WEEKDAYS[g]]
        pending = [g for g in games if not game_settled(g, night, draws, next_doc)]
        if pending:
            return night, pending
    return None, []


def without_volatile(doc):
    """A copy of a JSON document without the fields that change on every scrape."""
    if isinstance(doc, dict):
        return {k: without_volatile(v) for k, v in doc.items() if k not in VOLATILE}
    if isinstance(doc, list):
        return [without_volatile(v) for v in doc]
    return doc


def is_news(before, after):
    """Whether a scrape found anything new: {name: parsed JSON} before and after."""
    return any(without_volatile(before[name]) != without_volatile(after[name]) for name in before)


def read_data():
    return {name: json.loads((DATA_DIR / name).read_text(encoding="utf-8")) for name in ("next.json", "draws.json")}


def read_state():
    """(draws, next_doc) as stored in the checkout."""
    return store.load_draws(DATA_DIR / "draws.json"), read_data()["next.json"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def sync():
    """Match the checkout to main, where the Scrape workflow commits."""
    git("fetch", "--quiet", "origin", "main")
    git("reset", "--quiet", "--hard", "origin/main")


def found_news():
    """Scrape into the checkout and report whether anything changed, leaving the files as they were."""
    before = read_data()
    result = subprocess.run([sys.executable, "scrape.py"], cwd=ROOT, capture_output=True, text=True)
    print(result.stdout.strip() or result.stderr.strip(), flush=True)
    try:
        return result.returncode == 0 and is_news(before, read_data())
    finally:
        git("checkout", "--", "data")


def utcnow():
    return datetime.now(timezone.utc)


def say(text):
    print(f"{utcnow().astimezone(EASTERN):%a %H:%M} ET  {text}", flush=True)


class GitHub:
    def __init__(self, token, repo, run_id=None):
        self.repo = repo
        self.run_id = int(run_id) if run_id else None
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})

    def workflow(self, name):
        return f"{API}/repos/{self.repo}/actions/workflows/{name}"

    def dispatch(self, name, inputs=None):
        body = {"ref": "main", **({"inputs": inputs} if inputs else {})}
        self.session.post(f"{self.workflow(name)}/dispatches", json=body, timeout=30).raise_for_status()

    def run_scrape(self):
        """Start the Scrape workflow and wait for it; True if it finished successfully."""
        started = datetime.now(timezone.utc) - timedelta(seconds=5)
        self.dispatch("scrape.yml")
        deadline = datetime.now(timezone.utc) + SCRAPE_WAIT
        while datetime.now(timezone.utc) < deadline:
            time.sleep(20)
            runs = self.session.get(f"{self.workflow('scrape.yml')}/runs",
                                    params={"event": "workflow_dispatch", "per_page": 5}, timeout=30)
            runs.raise_for_status()
            for run in runs.json()["workflow_runs"]:
                created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                if created >= started and run["status"] == "completed":
                    say(f"Scrape run {run['html_url']}: {run['conclusion']}")
                    return run["conclusion"] == "success"
        say("Scrape run didn't finish in time; carrying on")
        return False

    def older_watcher(self, handed_over_by=None):
        """The URL of an earlier Draw watch run still in progress, if any (ignoring the run
        that handed over to this one, which may not have finished exiting yet)."""
        runs = self.session.get(f"{self.workflow('draw-watch.yml')}/runs",
                                params={"status": "in_progress", "per_page": 20}, timeout=30)
        runs.raise_for_status()
        for run in runs.json()["workflow_runs"]:
            if run["id"] < (self.run_id or 0) and run["id"] != handed_over_by:
                return run["html_url"]
        return None

    def hand_over(self):
        """Start a fresh Draw watch run to carry on from this one."""
        self.dispatch("draw-watch.yml", {"now": "false", "handed_over_by": str(self.run_id or "")})
        say("Handed over to a fresh run")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", action="store_true", help="start checking at once instead of after draw time")
    parser.add_argument("--handed-over-by", type=int, help="the run this one carries on from")
    parser.add_argument("--check-dispatch", action="store_true", help="just start one Scrape run and wait for it, to test access")
    args = parser.parse_args(argv)

    github = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_RUN_ID"))
    if args.check_dispatch:
        return 0 if github.run_scrape() else 1

    started = utcnow()
    budget_end = started + RUN_BUDGET
    night, games = pick_night(started, *read_state())
    if not night:
        say("No draw to watch: last night's results are in and there's no draw tonight.")
        return 0
    wake = datetime.combine(night, DRAW_TIME, EASTERN) + FIRST_LOOK
    give_up = datetime.combine(night + timedelta(days=1), GIVE_UP, EASTERN)
    if not args.now and wake - started > MAX_LEAD:
        say(f"The draw is more than {MAX_LEAD.seconds // 3600} hours off; a later scheduled run will watch it.")
        return 0
    other = github.older_watcher(args.handed_over_by)
    if other:
        say(f"Another run is already watching: {other}")
        return 0
    say(f"Watching {night:%a %b %d}: {', '.join(model.GAME_NAMES[g] for g in games)}")

    check_at_once = args.now  # a run started by hand checks straight away, then carries on as usual
    while True:
        now = utcnow()
        if now < wake and not check_at_once:
            if wake - now > MAX_LEAD:
                say("The draw is still hours off; a scheduled run will watch it.")
                return 0
            if wake > budget_end:
                say(f"The draw is more than {RUN_BUDGET.seconds // 3600} hours off; sleeping, then handing over")
                time.sleep(max(0.0, (budget_end - now).total_seconds()))
                github.hand_over()
                return 0
            say(f"Sleeping until {wake.astimezone(EASTERN):%H:%M} ET")
            time.sleep((wake - now).total_seconds())
        check_at_once = False
        sync()
        draws, next_doc = read_state()
        if all(game_settled(g, night, draws, next_doc) for g in games):
            say("Results and next jackpots are in; done.")
            return 0
        # After an update that stored something, check again at once: the next jackpot often
        # follows the results closely. Otherwise wait, so a failing update isn't retried nonstop.
        if found_news():
            head = git("rev-parse", "HEAD")
            if github.run_scrape():
                sync()
                if git("rev-parse", "HEAD") != head:
                    continue
        now = utcnow()
        if now + POLL_EVERY > give_up:
            say("Giving up for the night; the scheduled Scrape runs will pick up the rest.")
            return 0
        if now + POLL_EVERY > budget_end:
            github.hand_over()
            return 0
        time.sleep(POLL_EVERY.total_seconds())


if __name__ == "__main__":
    sys.exit(main())
