import pytest

from lottocalc import model
from lottocalc.sources import ParseError, lotterycanada


def test_649_next_draw(page):
    assert lotterycanada.parse_next(page("lc_649.html"), model.LOTTO_649) == {
        "draw_date": "2026-09-23",
        "jackpot": 5_000_000,
        "gold_ball_amount": 10_000_000,
        "balls_remaining": 30,
    }


def test_lotto_max_next_draw(page):
    assert lotterycanada.parse_next(page("lc_max.html"), model.LOTTO_MAX) == {
        "draw_date": "2026-09-25",
        "jackpot": 60_000_000,
        "maxmillions_count": None,
        "maxplus_count": 60,
        "maxplus_prize": 100_000,
    }


def test_page_without_next_draw_is_a_parse_error():
    with pytest.raises(ParseError):
        lotterycanada.parse_next("<html></html>", model.LOTTO_649)
