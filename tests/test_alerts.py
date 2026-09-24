from datetime import datetime, timezone

import pytest

import alert
from lottocalc import alerts, model


def doc(stamp, errors=(), warnings=(), best=model.LOTTO_MAX, max_value=0.33, g649_value=0.22,
        max_draw=1273, g649_draw=4454, balls=29):
    runner_up = g649_value if best == model.LOTTO_MAX else max_value
    return {
        "scraped_at": stamp,
        model.LOTTO_MAX: {"draw_number": max_draw, "draw_date": "2026-09-25", "jackpot": 60_000_000,
                          "maxmillions_count": 6, "value": {"per_dollar": max_value}},
        model.LOTTO_649: {"draw_number": g649_draw, "draw_date": "2026-09-26", "gold_ball_amount": 12_000_000,
                          "balls_remaining": balls, "value": {"per_dollar": g649_value}},
        "recommendation": {"top_prizes": {"game": best, "per_dollar": max(max_value, g649_value),
                                          "runner_up_per_dollar": runner_up}},
        "errors": list(errors),
        "warnings": list(warnings),
    }


CLEAN_BEFORE, CLEAN_NOW = doc("2026-09-24T11:17:00Z"), doc("2026-09-24T21:17:00Z")
BROKEN = ["Lotto 6/49: WCLC results page unavailable, no new draws (HTTP 503)"]


def test_clean_run_has_no_problems():
    assert alerts.run_problems(CLEAN_BEFORE, CLEAN_NOW) == []
    assert not alerts.should_report(CLEAN_BEFORE, CLEAN_NOW)


def test_a_run_that_wrote_nothing_is_a_crash_and_reported_at_once():
    assert alerts.run_problems(CLEAN_BEFORE, CLEAN_BEFORE) == [alerts.CRASHED]
    assert alerts.should_report(CLEAN_BEFORE, CLEAN_BEFORE)


def test_errors_are_reported_only_once_they_last_two_runs():
    first = doc("2026-09-24T21:17:00Z", errors=BROKEN)
    second = doc("2026-09-25T04:17:00Z", errors=BROKEN)
    assert alerts.run_problems(CLEAN_BEFORE, first) == BROKEN
    assert not alerts.should_report(CLEAN_BEFORE, first)
    assert alerts.should_report(first, second)


def test_falling_back_to_the_backup_source_counts_as_a_problem():
    warning = "Lotto Max: next draw taken from the backup source, Lottery Canada"
    degraded = doc("2026-09-24T21:17:00Z", warnings=[warning, "Lotto 6/49: results for 2026-09-23 not stored yet"])
    assert alerts.problems(degraded) == [warning]


def test_flip_of_the_better_buy_is_announced():
    flipped = doc("2026-09-26T11:17:00Z", best=model.LOTTO_649, max_value=0.05, g649_value=0.24, max_draw=1274)
    messages = alerts.value_alerts(CLEAN_NOW, flipped)
    assert len(messages) == 1
    assert messages[0].startswith("Lotto 6/49 is now the better buy: $0.24 vs $0.05")


def test_threshold_alert_fires_once_per_draw():
    rich = doc("2026-09-24T21:17:00Z", best=model.LOTTO_649, g649_value=0.52, balls=9)
    first = alerts.value_alerts(doc("2026-09-24T11:17:00Z", best=model.LOTTO_649, g649_value=0.45, balls=9), rich)
    assert first == ["Lotto 6/49 is worth $0.52 back per $1 for the 2026-09-26 draw "
                     "($12M Gold Ball, 9 balls left), above your $0.50 alert."]
    assert alerts.value_alerts(rich, doc("2026-09-25T04:17:00Z", best=model.LOTTO_649, g649_value=0.53, balls=9)) == []
    next_draw = doc("2026-09-27T11:17:00Z", best=model.LOTTO_649, g649_value=0.58, g649_draw=4455, balls=8)
    assert len(alerts.value_alerts(rich, next_draw)) == 1


def test_threshold_can_be_changed():
    before = doc("2026-09-23T11:17:00Z", max_draw=1272, max_value=0.30)
    assert alerts.value_alerts(before, CLEAN_NOW, threshold=0.33)  # Lotto Max reaches $0.33 on draw 1273
    assert not alerts.value_alerts(before, CLEAN_NOW, threshold=0.40)


class FakeGitHub:
    def __init__(self, open_issues=None):
        self.open_issues = dict(open_issues or {})  # label -> number
        self.calls = []
        self.next_number = 10

    def open_issue(self, label):
        return self.open_issues.get(label)

    def create_issue(self, title, body, label):
        self.next_number += 1
        self.open_issues[label] = self.next_number
        self.calls.append(("create", label, title, body))
        return self.next_number

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def close(self, number):
        self.open_issues = {k: v for k, v in self.open_issues.items() if v != number}
        self.calls.append(("close", number))

    def issue_url(self, number):
        return f"https://github.com/soyssauccee/lotto-calculator/issues/{number}"


@pytest.fixture
def pushed(monkeypatch):
    sent = []
    monkeypatch.setattr(alert, "push_ntfy", lambda topic, message, url, **options: sent.append((topic, message, url, options)))
    return sent


OPTIONS = dict(owner="soyssauccee", run_url="https://github.com/run/1", page_url="https://soyssauccee.github.io/lotto-calculator/",
               now=datetime(2026, 9, 25, 4, 17, tzinfo=timezone.utc))


def test_lasting_problem_opens_one_issue_mentioning_the_owner():
    github = FakeGitHub()
    first, second = doc("2026-09-24T21:17:00Z", errors=BROKEN), doc("2026-09-25T04:17:00Z", errors=BROKEN)
    assert alert.handle(github, CLEAN_BEFORE, first, **OPTIONS) == ["problem noted; alerting only if the next run also has it"]
    assert alert.handle(github, first, second, **OPTIONS) == ["opened issue #11"]
    kind, label, title, body = github.calls[0]
    assert (kind, label) == ("create", alert.PROBLEM_LABEL)
    assert body.startswith("@soyssauccee") and BROKEN[0] in body
    third = doc("2026-09-25T06:47:00Z", errors=BROKEN)
    assert alert.handle(github, second, third, **OPTIONS) == ["problem continues; issue #11 is already open"]
    assert len(github.calls) == 1  # no repeat emails while it stays broken


def test_recovery_closes_the_issue():
    github = FakeGitHub({alert.PROBLEM_LABEL: 7})
    assert alert.handle(github, doc("2026-09-25T04:17:00Z", errors=BROKEN), CLEAN_NOW, **OPTIONS) == ["closed issue #7"]
    assert [c[0] for c in github.calls] == ["comment", "close"]


def test_value_alert_goes_to_an_issue_without_ntfy():
    github = FakeGitHub()
    flipped = doc("2026-09-26T11:17:00Z", best=model.LOTTO_649, max_value=0.05, g649_value=0.24, max_draw=1274)
    assert alert.handle(github, CLEAN_NOW, flipped, **OPTIONS) == ["posted a value alert on issue #11"]
    assert [c[0] for c in github.calls] == ["create", "comment"]
    assert github.calls[1][2].startswith("@soyssauccee Lotto 6/49 is now the better buy")


def test_value_alert_is_pushed_when_ntfy_is_set_up(pushed):
    github = FakeGitHub()
    flipped = doc("2026-09-26T11:17:00Z", best=model.LOTTO_649, max_value=0.05, g649_value=0.24, max_draw=1274)
    assert alert.handle(github, CLEAN_NOW, flipped, ntfy_topic="secret-topic", **OPTIONS) == ["pushed a value alert"]
    assert pushed[0][0] == "secret-topic" and pushed[0][2] == OPTIONS["page_url"]
    assert github.calls == []


def test_problem_and_recovery_are_pushed_when_ntfy_is_set_up(pushed):
    github = FakeGitHub()
    first, second = doc("2026-09-24T21:17:00Z", errors=BROKEN), doc("2026-09-25T04:17:00Z", errors=BROKEN)
    assert alert.handle(github, first, second, ntfy_topic="secret-topic", **OPTIONS) == ["opened issue #11", "pushed the problem"]
    topic, message, url, options = pushed[0]
    assert message == f"{BROKEN[0]} Details in issue #11." and url.endswith("/issues/11")
    assert options["priority"] == "high"
    later = doc("2026-09-25T11:17:00Z")
    assert alert.handle(github, second, later, ntfy_topic="secret-topic", **OPTIONS) == ["closed issue #11", "pushed the recovery"]
    assert pushed[1][3]["priority"] == "low"


def test_github_client_sends_authorised_requests():
    class Response:
        def __init__(self, payload):
            self.payload, self.content = payload, b"x" if payload is not None else b""

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.headers, self.requests = {}, []

        def request(self, method, url, timeout, **kwargs):
            self.requests.append((method, url, kwargs))
            return Response([{"number": 5}] if method == "GET" else {"number": 6})

    session = Session()
    github = alert.GitHub("soyssauccee/lotto-calculator", "token123", session=session)
    assert github.open_issue(alert.PROBLEM_LABEL) == 5
    assert github.create_issue("t", "b", alert.VALUE_LABEL) == 6
    assert session.headers["Authorization"] == "Bearer token123"
    assert session.requests[0][1] == "https://api.github.com/repos/soyssauccee/lotto-calculator/issues"
    assert session.requests[1][2]["json"] == {"title": "t", "body": "b", "labels": [alert.VALUE_LABEL]}
