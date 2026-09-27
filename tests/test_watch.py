from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import watch

FRIDAY_MAX = {"game": "lottomax", "draw_date": "2026-09-25", "draw_number": 1273}
WEDNESDAY_649 = {"game": "lotto649", "draw_date": "2026-09-23", "draw_number": 4453}
SATURDAY_649 = {"game": "lotto649", "draw_date": "2026-09-26", "draw_number": 4454}


def utc(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def next_doc(g649=(4454, "2026-09-26"), lottomax=(1274, "2026-09-29")):
    return {
        "scraped_at": "2026-09-26T16:00:00Z",
        "lotto649": {"draw_number": g649[0], "draw_date": g649[1], "as_of": "2026-09-26T16:00:00Z"},
        "lottomax": {"draw_number": lottomax[0], "draw_date": lottomax[1], "as_of": "2026-09-26T16:00:00Z"},
    }


# ---------- which night to watch, and when it's settled ----------

def test_a_draw_is_settled_once_stored_and_the_next_jackpot_is_posted():
    saturday = date(2026, 9, 26)
    assert not watch.game_settled("lotto649", saturday, [WEDNESDAY_649], next_doc())
    # stored, but the next jackpot isn't posted yet (the sites list no draw number meanwhile)
    waiting = next_doc(g649=(None, "2026-09-26"))
    assert not watch.game_settled("lotto649", saturday, [WEDNESDAY_649, SATURDAY_649], waiting)
    assert watch.game_settled("lotto649", saturday, [WEDNESDAY_649, SATURDAY_649], next_doc(g649=(4455, "2026-09-30")))


def test_picks_tonights_draw_on_a_draw_day():
    # Saturday 12:07 PM EDT: Friday's Lotto Max is in, so tonight's 6/49
    assert watch.pick_night(utc(26, 16, 7), [FRIDAY_MAX, WEDNESDAY_649], next_doc()) == (date(2026, 9, 26), ["lotto649"])


def test_keeps_watching_last_night_until_noon():
    # Sunday 1:30 AM EDT, Saturday's result not in yet
    assert watch.pick_night(utc(27, 5, 30), [FRIDAY_MAX, WEDNESDAY_649], next_doc()) == (date(2026, 9, 26), ["lotto649"])
    # once it's in and the next jackpot is posted, Sunday has no draw: nothing to do
    done = next_doc(g649=(4455, "2026-09-30"))
    assert watch.pick_night(utc(27, 5, 30), [FRIDAY_MAX, WEDNESDAY_649, SATURDAY_649], done) == (None, [])
    # and after noon, last night is left to the scheduled scrapes
    assert watch.pick_night(utc(27, 17, 0), [FRIDAY_MAX, WEDNESDAY_649], next_doc()) == (None, [])


def test_only_real_changes_count_as_news():
    before = {"next.json": next_doc(), "draws.json": {"draws": [WEDNESDAY_649]}}
    restamped = {"next.json": next_doc(), "draws.json": {"draws": [WEDNESDAY_649]}}
    restamped["next.json"]["scraped_at"] = "2026-09-27T03:00:00Z"
    restamped["next.json"]["lotto649"]["as_of"] = "2026-09-27T03:00:00Z"
    assert not watch.is_news(before, restamped)
    assert watch.is_news(before, {"next.json": next_doc(), "draws.json": {"draws": [WEDNESDAY_649, SATURDAY_649]}})
    assert watch.is_news(before, {"next.json": next_doc(g649=(4455, "2026-09-30")), "draws.json": before["draws.json"]})


# ---------- whole runs, on a simulated clock ----------

class World:
    """The repo and the lottery sites: Saturday's 6/49 result appears at `posted_at`,
    and a Scrape run stores it along with the next jackpot."""

    def __init__(self, clock, posted_at, other_watcher=None):
        self.clock, self.posted_at = clock, posted_at
        self.draws = [FRIDAY_MAX, WEDNESDAY_649]
        self.next_doc = next_doc()
        self.version = 1
        self.scrapes = self.handovers = self.checks = 0
        self.other_watcher = other_watcher

    # stand-ins for watch.py's helpers
    def read_state(self):
        return self.draws, self.next_doc

    def found_news(self):
        self.checks += 1
        return self.clock.now >= self.posted_at and SATURDAY_649 not in self.draws

    def git(self, *args):
        return str(self.version)

    # and for its GitHub client
    def older_watcher(self, handed_over_by=None):
        return self.other_watcher

    def run_scrape(self):
        self.scrapes += 1
        if self.clock.now >= self.posted_at:
            self.draws = self.draws + [SATURDAY_649]
            self.next_doc = next_doc(g649=(4455, "2026-09-30"))
            self.version += 1
        return True

    def hand_over(self):
        self.handovers += 1


class Clock:
    def __init__(self, start):
        self.now = start

    def sleep(self, seconds):
        assert seconds >= 0
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def run(monkeypatch):
    """run(start, posted_at, *args) -> (exit status, world, clock) for one Draw watch run."""
    def go(start, posted_at, *args, other_watcher=None):
        clock = Clock(start)
        world = World(clock, posted_at, other_watcher)
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setattr(watch, "utcnow", lambda: clock.now)
        monkeypatch.setattr(watch, "time", SimpleNamespace(sleep=clock.sleep))
        monkeypatch.setattr(watch, "GitHub", lambda *a, **k: world)
        monkeypatch.setattr(watch, "sync", lambda: None)
        for name in ("read_state", "found_news", "git"):
            monkeypatch.setattr(watch, name, getattr(world, name))
        return watch.main(list(args)), world, clock
    return go


def test_an_early_start_sleeps_then_hands_over_before_the_job_limit(run):
    status, world, clock = run(utc(26, 16, 7), utc(27, 2, 55))  # Saturday 12:07 PM EDT
    assert (status, world.handovers, world.scrapes, world.checks) == (0, 1, 0, 0)
    assert clock.now == utc(26, 16, 7) + watch.RUN_BUDGET


def test_the_run_it_hands_over_to_catches_the_result_minutes_after_its_posted(run):
    # the draw is at 10:30 PM EDT (02:30 UTC); the result is posted at 10:55 PM
    status, world, clock = run(utc(26, 21, 38), utc(27, 2, 55), "--handed-over-by", "7")
    assert (status, world.handovers, world.scrapes) == (0, 0, 1)
    assert SATURDAY_649 in world.draws
    assert clock.now == utc(27, 2, 55)  # woke at 10:45 PM, checked, and again 10 minutes later


def test_a_slow_night_hands_over_rather_than_stopping(run):
    status, world, clock = run(utc(26, 21, 38), utc(27, 5, 0), "--handed-over-by", "7")
    assert (status, world.handovers, world.scrapes) == (0, 1, 0)
    assert clock.now <= utc(26, 21, 38) + watch.RUN_BUDGET


def test_gives_up_at_noon_the_next_day(run):
    never = utc(30, 0, 0)
    status, world, clock = run(utc(27, 11, 0), never, "--handed-over-by", "7")  # Sunday 7 AM EDT
    assert (status, world.handovers, world.scrapes) == (0, 0, 0)
    assert clock.now <= utc(27, 16, 0)  # noon EDT


def test_a_second_run_leaves_it_to_the_one_already_watching(run):
    status, world, clock = run(utc(26, 20, 7), utc(27, 2, 55), other_watcher="https://example/runs/1")
    assert (status, world.checks, world.handovers) == (0, 0, 0)
    assert clock.now == utc(26, 20, 7)


def test_a_run_far_ahead_of_the_draw_leaves_it_to_a_later_one(run):
    status, world, clock = run(utc(26, 9, 0), utc(27, 2, 55))  # Saturday 5 AM EDT
    assert (status, world.checks, world.handovers) == (0, 0, 0)


def test_a_run_started_by_hand_checks_once_even_far_ahead(run):
    status, world, clock = run(utc(26, 11, 0), utc(27, 2, 55), "--now")  # Saturday 7 AM EDT
    assert (status, world.checks, world.handovers, world.scrapes) == (0, 1, 0, 0)
