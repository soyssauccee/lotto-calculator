"""Send the alerts for one scheduled run.

    python alert.py --previous PREVIOUS_NEXT_JSON [--log SCRAPE_LOG]

Run by .github/workflows/scrape.yml after scrape.py, with the next.json the run
started from. Data problems open a GitHub issue (which emails the repository
owner) and the issue is closed when a run comes back clean. Value alerts are
pushed to the ntfy.sh topic in NTFY_TOPIC when that secret is set, and are
otherwise posted as comments on a "Value alerts" issue. With NTFY_TOPIC set,
opening and closing the problem issue is pushed to the phone as well.

Needs GITHUB_TOKEN and GITHUB_REPOSITORY; VALUE_ALERT_THRESHOLD is optional.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from lottocalc import alerts, store

DATA_DIR = Path(__file__).resolve().parent / "data"
PROBLEM_LABEL = "data-problem"
VALUE_LABEL = "value-alert"


class GitHub:
    """The few issue calls the alerts need."""

    def __init__(self, repository, token, session=None):
        self.repository = repository
        self.base = f"https://api.github.com/repos/{repository}"
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _call(self, method, path, **kwargs):
        response = self.session.request(method, self.base + path, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def open_issue(self, label):
        issues = self._call("GET", "/issues", params={"labels": label, "state": "open", "per_page": 1})
        return issues[0]["number"] if issues else None

    def create_issue(self, title, body, label):
        return self._call("POST", "/issues", json={"title": title, "body": body, "labels": [label]})["number"]

    def comment(self, number, body):
        self._call("POST", f"/issues/{number}/comments", json={"body": body})

    def close(self, number):
        self._call("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "completed"})

    def issue_url(self, number):
        return f"https://github.com/{self.repository}/issues/{number}"


def push_ntfy(topic, message, click_url, title="Lotto Calculator", tags="moneybag", priority="default", session=requests):
    response = session.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Tags": tags, "Priority": priority, "Click": click_url},
        timeout=30,
    )
    response.raise_for_status()


def handle(github, previous, current, *, owner, run_url, page_url, log_tail="", ntfy_topic=None, threshold=None, now=None):
    """Open, leave or close the data-problem issue, and send value alerts. Returns what was done."""
    done = []
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    found = alerts.run_problems(previous, current)
    open_number = github.open_issue(PROBLEM_LABEL)
    if found and alerts.should_report(previous, current) and open_number is None:
        body = "\n".join([
            f"@{owner} the lottery data stopped updating properly ({stamp}).",
            "",
            *[f"- {p}" for p in found],
            "",
            f"Run: {run_url}",
            "The page keeps showing the last good numbers and warns that they may be out of date.",
            "This issue closes itself when a run succeeds again.",
        ] + (["", "Log:", "```", log_tail, "```"] if log_tail else []))
        number = github.create_issue("Lottery data isn't updating", body, PROBLEM_LABEL)
        done.append(f"opened issue #{number}")
        if ntfy_topic:
            push_ntfy(ntfy_topic, f"{found[0]} Details in issue #{number}.", github.issue_url(number),
                      title="Lottery data isn't updating", tags="warning", priority="high")
            done.append("pushed the problem")
    elif not found and open_number is not None:
        github.comment(open_number, f"Back to normal as of {stamp}: {run_url}")
        github.close(open_number)
        done.append(f"closed issue #{open_number}")
        if ntfy_topic:
            push_ntfy(ntfy_topic, "The lottery data is updating again.", page_url,
                      title="Back to normal", tags="white_check_mark", priority="low")
            done.append("pushed the recovery")
    elif found:
        done.append("problem noted; alerting only if the next run also has it" if open_number is None
                    else f"problem continues; issue #{open_number} is already open")

    messages = alerts.value_alerts(previous, current, alerts.DEFAULT_VALUE_THRESHOLD if threshold is None else threshold)
    for message in messages:
        if ntfy_topic:
            push_ntfy(ntfy_topic, message, page_url)
            done.append("pushed a value alert")
        else:
            number = github.open_issue(VALUE_LABEL) or github.create_issue(
                "Value alerts",
                f"@{owner} alerts about which game is the better buy show up here as comments. Page: {page_url}",
                VALUE_LABEL,
            )
            github.comment(number, f"@{owner} {message}\n\n{page_url}")
            done.append(f"posted a value alert on issue #{number}")
    return done


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send the alerts for one scheduled run.")
    parser.add_argument("--previous", type=Path, required=True, help="next.json as it was before the run")
    parser.add_argument("--log", type=Path, help="scrape.py output, quoted in problem reports")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    repository = os.environ["GITHUB_REPOSITORY"]
    owner, name = repository.split("/")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID")
    threshold = os.environ.get("VALUE_ALERT_THRESHOLD") or None
    log_tail = "\n".join(args.log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]) if args.log and args.log.exists() else ""

    done = handle(
        GitHub(repository, os.environ["GITHUB_TOKEN"]),
        store.load_json(args.previous),
        store.load_json(args.data_dir / "next.json"),
        owner=owner,
        run_url=f"{server}/{repository}/actions/runs/{run_id}" if run_id else f"{server}/{repository}/actions",
        page_url=f"https://{owner}.github.io/{name}/",
        log_tail=log_tail,
        ntfy_topic=os.environ.get("NTFY_TOPIC") or None,
        threshold=float(threshold) if threshold else None,
    )
    print("\n".join(done) or "nothing to report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
