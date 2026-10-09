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
    # after midnight, a scrape notes the draw has passed while its results are pending
    noted = {"next.json": next_doc(), "draws.json": {"draws": [WEDNESDAY_649]}}
    noted["next.json"]["warnings"] = ["Lotto 6/49: the 2026-09-26 draw has passed but the source hasn't moved on"]
    assert not watch.is_news(before, noted)
    assert watch.is_news(before, {"next.json": next_doc(), "draws.json": {"draws": [WEDNESDAY_649, SATURDAY_649]}})
    assert watch.is_news(before, {"next.json": next_doc(g649=(4455, "2026-09-30")), "draws.json": before["draws.json"]})


# ---------- whole runs, on a simulated clock ----------

def night(stored, result, waiting, settled):
    """A draw night: the draws stored beforehand, the night's result, and next.json before
    and after the result and the next jackpot are in."""
    return {"stored": stored, "result": result, "waiting": waiting, "settled": settled}


SEPTEMBER_26 = night([FRIDAY_MAX, WEDNESDAY_649], SATURDAY_649, next_doc(), next_doc(g649=(4455, "2026-09-30")))
# The clocks go back at 2 AM on Sunday Nov 1, in the night after Saturday's draw...
OCTOBER_31 = night(
    [{"game": "lottomax", "draw_date": "2026-10-30", "draw_number": 1283},
     {"game": "lotto649", "draw_date": "2026-10-28", "draw_number": 4463}],
    {"game": "lotto649", "draw_date": "2026-10-31", "draw_number": 4464},
    next_doc(g649=(4464, "2026-10-31"), lottomax=(1284, "2026-11-03")),
    next_doc(g649=(4465, "2026-11-04"), lottomax=(1284, "2026-11-03")),
)
# ...so the next Saturday's draw is at 10:30 PM EST, 03:30 UTC
NOVEMBER_7 = night(
    [{"game": "lottomax", "draw_date": "2026-11-06", "draw_number": 1285},
     {"game": "lotto649", "draw_date": "2026-11-04", "draw_number": 4465}],
    {"game": "lotto649", "draw_date": "2026-11-07", "draw_number": 4466},
    next_doc(g649=(4466, "2026-11-07"), lottomax=(1286, "2026-11-10")),
    next_doc(g649=(4467, "2026-11-11"), lottomax=(1286, "2026-11-10")),
)


class World:
    """The repo and the lottery sites: the night's result appears at `posted_at`, and a
    Scrape run stores it along with the next jackpot."""

    def __init__(self, clock, posted_at, other_watcher=None, night=SEPTEMBER_26):
        self.clock, self.posted_at = clock, posted_at
        self.draws = list(night["stored"])
        self.next_doc = night["waiting"]
        self.result, self.settled = night["result"], night["settled"]
        self.version = 1
        self.scrapes = self.handovers = self.checks = 0
        self.other_watcher = other_watcher

    # stand-ins for watch.py's helpers
    def read_state(self):
        return self.draws, self.next_doc

    def found_news(self):
        self.checks += 1
        return self.clock.now >= self.posted_at and self.result not in self.draws

    def git(self, *args):
        return str(self.version)

    # and for its GitHub client
    def older_watcher(self, handed_over_by=None):
        return self.other_watcher

    def run_scrape(self):
        self.scrapes += 1
        if self.clock.now >= self.posted_at:
            self.draws = self.draws + [self.result]
            self.next_doc = self.settled
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
    def go(start, posted_at, *args, other_watcher=None, night=SEPTEMBER_26):
        clock = Clock(start)
        world = World(clock, posted_at, other_watcher, night)
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


# ---------- when the clocks go back ----------

def test_the_night_the_clocks_go_back_gives_up_at_noon_standard_time(run):
    # Saturday Oct 31's result never arrives. By Sunday noon the clocks have gone back, so noon
    # is 17:00 UTC, not 16:00 as it would have been the day before.
    never = datetime(2026, 11, 3, tzinfo=timezone.utc)
    start = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # 7 AM EST
    status, world, clock = run(start, never, "--handed-over-by", "7", night=OCTOBER_31)
    assert (status, world.handovers, world.scrapes) == (0, 0, 0)
    assert clock.now == datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)


def test_on_standard_time_the_watch_starts_at_1045_pm_eastern(run):
    # Saturday Nov 7: a run handed over at 4:37 PM EST is still 6 hours from the draw, so it
    # hands over again...
    start = datetime(2026, 11, 7, 21, 37, tzinfo=timezone.utc)
    status, world, clock = run(start, start + timedelta(days=2), "--handed-over-by", "7", night=NOVEMBER_7)
    assert (status, world.checks, world.handovers) == (0, 0, 1)
    # ...and the next run first looks at 10:45 PM EST (03:45 UTC), then catches a result
    # posted at 10:50 PM on its next look
    posted = datetime(2026, 11, 8, 3, 50, tzinfo=timezone.utc)
    status, world, clock = run(start + watch.RUN_BUDGET, posted, "--handed-over-by", "8", night=NOVEMBER_7)
    assert (status, world.checks, world.scrapes, world.handovers) == (0, 2, 1, 0)
    assert clock.now == datetime(2026, 11, 8, 3, 55, tzinfo=timezone.utc)
