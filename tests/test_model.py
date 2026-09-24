from datetime import date

import pytest

from lottocalc import model
from lottocalc.sources import wclc


@pytest.mark.parametrize(
    "label, key",
    [
        ("6 of 6", "6/6"),
        ("5 of 6 + Bonus", "5/6+B"),
        ("3 of 7+Bonus", "3/7+B"),
        (" 2 of 6 ", "2/6"),
        ("Last 4 digits", None),
        ("All 7 digits", None),
    ],
)
def test_tier_key(label, key):
    assert model.tier_key(label) == key


@pytest.mark.parametrize(
    "jackpot, balls",
    [(10_000_000, 30), (32_000_000, 19), (68_000_000, 1), (11_000_000, None), (70_000_000, None), (8_000_000, None)],
)
def test_balls_for_jackpot(jackpot, balls):
    assert model.balls_for_jackpot(jackpot) == balls


def test_draws_between():
    sat, wed, next_sat = date(2026, 9, 19), date(2026, 9, 23), date(2026, 9, 26)
    assert model.draws_between(model.LOTTO_649, sat, wed) == [wed]
    assert model.draws_between(model.LOTTO_649, sat, next_sat) == [wed, next_sat]
    assert model.draws_between(model.LOTTO_649, wed, wed) == []
    assert model.draws_between(model.LOTTO_MAX, date(2026, 9, 22), date(2026, 9, 25)) == [date(2026, 9, 25)]


def gold_ball_draws(first, balls, prizes=None):
    """6/49 records numbered from `first`, one per character of balls ('w' or 'g')."""
    prizes = prizes or {}
    return [
        {
            "game": model.LOTTO_649,
            "draw_number": first + i,
            "gold_ball_drawn": "gold" if ball == "g" else "white",
            "gold_ball_prize": prizes.get(first + i, model.WHITE_BALL_PRIZE),
        }
        for i, ball in enumerate(balls)
    ]


def state(draws):
    return [(d["gold_ball_amount"], d["balls_remaining"]) for d in draws]


def test_gold_ball_state_is_walked_both_ways_from_anchors():
    draws = gold_ball_draws(10, "wwgw", prizes={12: 16_000_000})
    warnings = model.derive_gold_ball(draws, {"draw_number": 14, "gold_ball_amount": 12_000_000})
    assert warnings == []
    assert state(draws) == [(12_000_000, 29), (14_000_000, 28), (16_000_000, 27), (10_000_000, 30)]


def test_gold_ball_state_from_the_format_start():
    draws = gold_ball_draws(model.GOLD_BALL_FIRST_DRAW, "ww")
    assert model.derive_gold_ball(draws) == []
    assert state(draws) == [(10_000_000, 30), (12_000_000, 29)]


def test_next_draw_that_contradicts_the_history_is_reported():
    draws = gold_ball_draws(10, "gw", prizes={10: 20_000_000})
    warnings = model.derive_gold_ball(draws, {"draw_number": 12, "gold_ball_amount": 16_000_000})
    assert warnings and "draw 12" in warnings[0]


def test_draw_cut_off_by_a_gap_stays_unknown():
    draws = [d for d in gold_ball_draws(10, "www") if d["draw_number"] != 11]
    warnings = model.derive_gold_ball(draws, {"draw_number": 13, "gold_ball_amount": 20_000_000})
    assert state(draws) == [(None, None), (18_000_000, 26)]
    assert len(warnings) == 1 and "unknown for 1 draw" in warnings[0]


def test_gold_prize_off_the_ladder_is_reported():
    draws = gold_ball_draws(10, "g", prizes={10: 11_000_000})
    assert "not on the Gold Ball ladder" in model.derive_gold_ball(draws)[0]


def test_check_draw_catches_parser_drift(page):
    draw = wclc.parse_prize_details(page("wclc_649_4452.html"), model.LOTTO_649, 4452)
    tiers = {k: v for k, v in draw["tier_winners"].items() if k != "3/6"}
    problems = model.check_draw(dict(draw, numbers=[1, 2, 3], tier_winners=tiers))
    assert any("winning numbers" in p for p in problems)
    assert any("3/6" in p for p in problems)


def test_check_next_derives_missing_balls():
    info = {"draw_date": "2026-09-23", "gold_ball_amount": 12_000_000, "balls_remaining": None}
    errors, warnings = model.check_next(model.LOTTO_649, info)
    assert errors == [] and info["balls_remaining"] == 29 and warnings


def test_check_next_flags_balls_that_dont_match_the_jackpot():
    info = {"draw_date": "2026-09-23", "gold_ball_amount": 12_000_000, "balls_remaining": 30}
    errors, warnings = model.check_next(model.LOTTO_649, info)
    assert errors == [] and "expected 29" in warnings[0]


def test_check_next_requires_a_jackpot():
    errors, _ = model.check_next(model.LOTTO_MAX, {"draw_date": "2026-09-25", "jackpot": None})
    assert errors
