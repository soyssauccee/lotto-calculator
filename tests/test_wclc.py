import pytest

from lottocalc import model
from lottocalc.sources import ParseError, wclc


@pytest.mark.parametrize("listing", ["wclc_649_listing.html", "wclc_max_listing.html"])
def test_next_draw_sidebar_is_on_either_listing_page(page, listing):
    upcoming = wclc.parse_next(page(listing))
    assert upcoming[model.LOTTO_649] == {
        "draw_date": "2026-09-23",
        "jackpot": 5_000_000,
        "gold_ball_amount": 10_000_000,
        "balls_remaining": 30,
    }
    assert upcoming[model.LOTTO_MAX] == {
        "draw_date": "2026-09-25",
        "jackpot": 60_000_000,
        "maxmillions_count": 6,
        "maxplus_count": 60,
        "maxplus_prize": 100_000,
    }


def test_page_without_sidebar_is_a_parse_error():
    with pytest.raises(ParseError):
        wclc.parse_next("<html><body>Down for maintenance</body></html>")


def test_draw_lists(page):
    draws = wclc.parse_draw_list(page("wclc_649_listing.html"))
    assert [d["draw_number"] for d in draws] == list(range(4452, 4444, -1))
    assert (draws[0]["draw_date"], draws[-1]["draw_date"]) == ("2026-09-19", "2026-08-26")

    draws = wclc.parse_draw_list(page("wclc_max_listing.html"))
    assert [d["draw_number"] for d in draws] == list(range(1272, 1264, -1))
    assert (draws[0]["draw_date"], draws[-1]["draw_date"]) == ("2026-09-22", "2026-08-28")


def test_649_gold_ball_win(page):
    draw = wclc.parse_prize_details(page("wclc_649_4452.html"), model.LOTTO_649, 4452)
    assert draw["draw_date"] == "2026-09-19"
    assert (draw["numbers"], draw["bonus"]) == ([1, 4, 13, 18, 25, 42], 29)
    assert draw["tier_winners"] == {
        "6/6": 0, "5/6+B": 2, "5/6": 95, "4/6": 4707, "3/6": 82670, "2/6+B": 55821, "2/6": 548286,
    }
    assert draw["tier_prizes"] == {
        "6/6": None, "5/6+B": 82782.5, "5/6": 731.8, "4/6": 59.5, "3/6": 10, "2/6+B": 5, "2/6": None,
    }
    assert (draw["gold_ball_drawn"], draw["gold_ball_prize"]) == ("gold", 32_000_000)
    assert (draw["super_draw"], draw["super_draw_prizes"]) == (False, [])
    assert model.check_draw(draw) == []


def test_649_super_draw(page):
    draw = wclc.parse_prize_details(page("wclc_649_4446.html"), model.LOTTO_649, 4446)
    assert (draw["super_draw"], draw["super_draw_prizes"]) == (True, [{"prize": 40_000, "count": 20}])
    assert (draw["gold_ball_drawn"], draw["gold_ball_prize"]) == ("white", 1_000_000)
    assert (draw["tier_winners"]["5/6+B"], draw["tier_prizes"]["5/6+B"]) == (2, 108203.4)
    assert model.check_draw(draw) == []


def test_649_first_gold_ball_draw_has_an_unwon_pool(page):
    draw = wclc.parse_prize_details(page("wclc_649_4033.html"), model.LOTTO_649, 4033)
    assert draw["draw_date"] == "2022-09-14"
    assert (draw["tier_winners"]["5/6+B"], draw["tier_prizes"]["5/6+B"]) == (0, None)
    assert draw["tier_winners"]["2/6"] == 438991
    assert model.check_draw(draw) == []


@pytest.mark.parametrize(
    "number, draw_date, jackpot, maxmillions, maxplus",
    [
        (1272, "2026-09-22", 55_000_000, (4, 0), (55, 7)),
        (1271, "2026-09-18", 50_000_000, (2, 1), (50, 10)),  # includes MAXPLUS prizes shared 3 and 2 ways
        (1270, "2026-09-15", 40_000_000, (0, 0), (40, 3)),  # below $50M: no MAXMILLIONS section
    ],
)
def test_lotto_max_breakdowns(page, number, draw_date, jackpot, maxmillions, maxplus):
    draw = wclc.parse_prize_details(page(f"wclc_max_{number}.html"), model.LOTTO_MAX, number)
    assert (draw["draw_date"], draw["jackpot"]) == (draw_date, jackpot)
    assert (draw["maxmillions_count"], draw["maxmillions_won"]) == maxmillions
    assert (draw["maxplus_count"], draw["maxplus_won"], draw["maxplus_prize"]) == (*maxplus, 100_000)
    assert list(draw["tier_winners"]) == list(model.TIERS[model.LOTTO_MAX])
    assert model.check_draw(draw) == []


def test_lotto_max_prize_tiers(page):
    draw = wclc.parse_prize_details(page("wclc_max_1272.html"), model.LOTTO_MAX, 1272)
    assert (draw["numbers"], draw["bonus"]) == ([1, 10, 12, 17, 30, 37, 42], 8)
    assert draw["tier_winners"] == {
        "7/7": 0, "6/7+B": 2, "6/7": 42, "5/7+B": 120, "5/7": 2753,
        "4/7+B": 4691, "4/7": 63262, "3/7+B": 65417, "3/7": 644944,
    }
    assert (draw["tier_prizes"]["6/7+B"], draw["tier_prizes"]["4/7"], draw["tier_prizes"]["3/7"]) == (85036.2, 20, None)


def test_breakdown_for_the_wrong_game_is_rejected(page):
    with pytest.raises(ParseError):
        wclc.parse_prize_details(page("wclc_max_1272.html"), model.LOTTO_649, 1272)


def test_empty_breakdown_is_rejected():
    with pytest.raises(ParseError):
        wclc.parse_prize_details("", model.LOTTO_649, 4453)
