from datetime import date, datetime, timezone

import watch


def next_doc(max_number=1273, max_date="2026-09-25", g649_number=4454, g649_date="2026-09-26"):
    return {
        "scraped_at": "2026-09-25T23:57:06Z",
        "lottomax": {"draw_number": max_number, "draw_date": max_date, "as_of": "2026-09-25T23:57:06Z"},
        "lotto649": {"draw_number": g649_number, "draw_date": g649_date, "as_of": "2026-09-25T23:57:06Z"},
    }


def test_tonight_is_the_eastern_evening_even_after_midnight():
    # 7:37 PM EDT Friday, and 1:30 AM EDT Saturday: both watch Friday's draw
    assert watch.tonight(datetime(2026, 9, 25, 23, 37, tzinfo=timezone.utc)) == date(2026, 9, 25)
    assert watch.tonight(datetime(2026, 9, 26, 5, 30, tzinfo=timezone.utc)) == date(2026, 9, 25)
    # Saturday afternoon is Saturday
    assert watch.tonight(datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)) == date(2026, 9, 26)


def test_watches_only_the_games_drawing_that_night():
    assert watch.watched_draws(next_doc(), date(2026, 9, 25)) == {"lottomax": 1273}
    assert watch.watched_draws(next_doc(), date(2026, 9, 26)) == {"lotto649": 4454}
    assert watch.watched_draws(next_doc(), date(2026, 9, 27)) == {}
    # while a jackpot isn't posted, the draw number is missing: nothing to watch for that game
    assert watch.watched_draws(next_doc(max_number=None), date(2026, 9, 25)) == {}


def test_settled_needs_the_result_and_the_next_jackpot():
    watched = {"lottomax": 1273}
    stored = [{"game": "lottomax", "draw_number": 1272}]
    assert not watch.settled(watched, stored, next_doc())
    stored.append({"game": "lottomax", "draw_number": 1273})
    assert not watch.settled(watched, stored, next_doc(max_number=None))  # result in, jackpot not yet
    assert not watch.settled(watched, stored, next_doc(max_number=1273))
    assert watch.settled(watched, stored, next_doc(max_number=1274, max_date="2026-09-29"))


def test_only_real_changes_count_as_news():
    before = {"next.json": next_doc(), "draws.json": {"draws": [{"game": "lottomax", "draw_number": 1272}]}}
    restamped = {
        "next.json": dict(next_doc(), scraped_at="2026-09-26T03:00:00Z",
                          lottomax=dict(next_doc()["lottomax"], as_of="2026-09-26T03:00:00Z")),
        "draws.json": before["draws.json"],
    }
    assert not watch.is_news(before, restamped)
    new_draw = dict(before, **{"draws.json": {"draws": [{"game": "lottomax", "draw_number": 1272}, {"game": "lottomax", "draw_number": 1273}]}})
    assert watch.is_news(before, new_draw)
    new_jackpot = dict(before, **{"next.json": next_doc(max_number=1274, max_date="2026-09-29")})
    assert watch.is_news(before, new_jackpot)
