"""Catch a draw's results soon after they're posted, and update the page then.

    python watch.py         wait until shortly after tonight's draw, then keep checking
    python watch.py --now   start checking at once (for a run started by hand)

GitHub often starts scheduled workflows hours late, so the Scrape workflow's own
post-draw runs can miss the evening. This runs as one long job, started before the
draw: it sleeps until just after draw time, then scrapes every POLL_EVERY. When the
lottery sites have something new, it starts the Scrape workflow (which commits the
data, redeploys the page and sends alerts; runs started this way begin at once),
waits for it to finish, and carries on until tonight's results and the next jackpot
are both in, or its time runs out.

Needs GITHUB_TOKEN (with actions: write) and GITHUB_REPOSITORY, as set in the
Draw watch workflow.
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
POLL_EVERY = timedelta(minutes=10)
RUN_BUDGET = timedelta(hours=5, minutes=40)  # the job's timeout is 6 hours
SCRAPE_WAIT = timedelta(minutes=15)  # longest to wait for a Scrape run to finish
VOLATILE = {"scraped_at", "as_of"}  # change on every scrape, so they don't count as news
API = "https://api.github.com"


def tonight(now):
    """The draw date being watched: today, or yesterday while the job runs past midnight."""
    local = now.astimezone(EASTERN)
    date = local.date()
    return date - timedelta(days=1) if local.hour < 12 else date


def watched_draws(next_doc, date):
    """{game: draw_number} for the games whose next draw, per next.json, is on `date`."""
    watched = {}
    for game in model.GAMES:
        info = next_doc.get(game) or {}
        if info.get("draw_date") == date.isoformat() and info.get("draw_number"):
            watched[game] = info["draw_number"]
    return watched


def settled(watched, draws, next_doc):
    """True once every watched draw is stored and its game's next jackpot is posted."""
    stored = {(d["game"], d["draw_number"]) for d in draws}
    return all(
        (game, number) in stored and ((next_doc.get(game) or {}).get("draw_number") or 0) > number
        for game, number in watched.items()
    )


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


class GitHub:
    def __init__(self, token, repo):
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})

    def run_scrape(self):
        """Start the Scrape workflow and wait for it; True if it finished successfully."""
        started = datetime.now(timezone.utc) - timedelta(seconds=5)
        url = f"{API}/repos/{self.repo}/actions/workflows/scrape.yml"
        self.session.post(f"{url}/dispatches", json={"ref": "main"}, timeout=30).raise_for_status()
        deadline = datetime.now(timezone.utc) + SCRAPE_WAIT
        while datetime.now(timezone.utc) < deadline:
            time.sleep(20)
            runs = self.session.get(f"{url}/runs", params={"event": "workflow_dispatch", "per_page": 5}, timeout=30)
            runs.raise_for_status()
            for run in runs.json()["workflow_runs"]:
                created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                if created >= started and run["status"] == "completed":
                    print(f"Scrape run {run['html_url']}: {run['conclusion']}", flush=True)
                    return run["conclusion"] == "success"
        print("Scrape run didn't finish in time; carrying on", flush=True)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--now", action="store_true", help="start checking at once instead of after draw time")
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    deadline = started + RUN_BUDGET
    date = tonight(started)
    watched = watched_draws(read_data()["next.json"], date)
    if not watched:
        print(f"No draw to watch on {date}: next.json lists none for that date.")
        return 0
    names = ", ".join(f"{model.GAME_NAMES[g]} #{n}" for g, n in watched.items())
    print(f"Watching {names} ({date})", flush=True)

    wake = datetime.combine(date, DRAW_TIME, EASTERN) + FIRST_LOOK
    if not args.now and wake > started:
        print(f"Sleeping until {wake.isoformat(timespec='minutes')}", flush=True)
        time.sleep((wake - started).total_seconds())

    github = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    while True:
        sync()
        if settled(watched, store.load_draws(DATA_DIR / "draws.json"), read_data()["next.json"]):
            print("Results and next jackpots are in; done.")
            return 0
        # After an update that stored something, check again at once: the next jackpot often
        # follows the results closely. Otherwise wait, so a failing update isn't retried nonstop.
        if found_news():
            head = git("rev-parse", "HEAD")
            if github.run_scrape():
                sync()
                if git("rev-parse", "HEAD") != head:
                    continue
        if datetime.now(timezone.utc) + POLL_EVERY > deadline:
            print("Out of time; the scheduled Scrape runs will pick up the rest.")
            return 0
        time.sleep(POLL_EVERY.total_seconds())


if __name__ == "__main__":
    sys.exit(main())
