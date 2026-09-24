import math
from pathlib import Path

import pytest

from lottocalc import model, store, value

HISTORY = Path(__file__).parent / "fixtures" / "draws_history.json"  # real draws through 6/49 #4452


def lotto649(gold_ball, balls, **extra):
    return {"gold_ball_amount": gold_ball, "balls_remaining": balls, **extra}


def lottomax(jackpot, maxmillions, maxplus=None):
    return {"jackpot": jackpot, "maxmillions_count": maxmillions,
            "maxplus_count": jackpot // 1_000_000 if maxplus is None else maxplus, "maxplus_prize": 100_000}


def top(game, draw, plays):
    return value.top_prize_value(game, value.evaluate(game, draw, plays)[0])


def test_plan_example_40m_gold_ball_with_15_balls():
    # From the plan: $40M with 15 balls and N = 4.5M gives about $0.37.
    parts, _ = value.evaluate(model.LOTTO_649, lotto649(40_000_000, 15), 4_500_000)
    assert parts["gold_ball"] == pytest.approx(0.266667, abs=1e-6)  # (40M/15 + 1M x 14/15) / 4.5M / $3
    assert parts["classic_jackpot"] == pytest.approx(0.101910, abs=1e-6)  # $5M / C(49,6) / $3, 85.5% kept
    assert top(model.LOTTO_649, lotto649(40_000_000, 15), 4_500_000) == pytest.approx(0.368577, abs=1e-6)


def test_lotto_max_60m_with_6_maxmillions():
    # share (1 - e^-λ)/λ with λ = 5.34M x 4 / C(52,7); prizes $60M + 60 x $100k + 6 x $1M
    assert top(model.LOTTO_MAX, lottomax(60_000_000, 6), 5_340_000) == pytest.approx(0.331609, abs=1e-6)
    parts, _ = value.evaluate(model.LOTTO_MAX, lottomax(60_000_000, 6), 5_340_000)
    assert parts["maxplus"] == pytest.approx(parts["jackpot"] / 10)
    assert parts["maxmillions"] == pytest.approx(parts["jackpot"] / 10)


def test_guaranteed_gold_ball_jackpot_is_worth_more_than_the_ticket():
    # Draw #4141: $68M with 1 ball left, 14.33M plays sold.
    assert top(model.LOTTO_649, lotto649(68_000_000, 1), 14_330_000) == pytest.approx(1.656329, abs=1e-6)


def test_super_draw_prizes_add_their_share():
    plain = value.evaluate(model.LOTTO_649, lotto649(10_000_000, 30), 4_000_000)[0]
    boosted = value.evaluate(model.LOTTO_649, lotto649(10_000_000, 30, super_draw_prizes=[{"prize": 40_000, "count": 20}]), 4_000_000)[0]
    assert boosted["super_draw"] == pytest.approx(800_000 / 4_000_000 / 3)
    assert plain["super_draw"] == 0


@pytest.mark.parametrize("expected_others, share", [(0, 1.0), (1e-9, 1.0), (1.0, 1 - math.exp(-1)), (0.1, 0.951626)])
def test_split_factor(expected_others, share):
    assert value.split_factor(expected_others) == pytest.approx(share, abs=1e-6)


def test_more_sales_mean_less_value():
    draw = lotto649(40_000_000, 15)
    assert top(model.LOTTO_649, draw, 4_000_000) > top(model.LOTTO_649, draw, 5_000_000)
    draw = lottomax(60_000_000, 6)
    assert top(model.LOTTO_MAX, draw, 4_000_000) > top(model.LOTTO_MAX, draw, 6_000_000)


@pytest.mark.parametrize(
    "game, plays, per_play",
    [(model.LOTTO_649, 4_500_000, 0.543517), (model.LOTTO_MAX, 5_340_000, 1.176295)],
)
def test_lower_tier_value(game, plays, per_play):
    # Fixed prizes at their odds, free plays at $1.44 / $2.88, pooled shares when won.
    assert value.lower_tier_value(game, plays) == pytest.approx(per_play, abs=1e-6)


def test_odds_per_play():
    _, odds = value.evaluate(model.LOTTO_MAX, lottomax(60_000_000, 6), 5_340_000)
    assert odds["jackpot"] == pytest.approx(33_446_140)
    assert odds["million_plus"] == pytest.approx(5_469_879, rel=1e-6)  # jackpot or an unshared MAXMILLIONS
    _, odds = value.evaluate(model.LOTTO_649, lotto649(40_000_000, 15), 4_500_000)
    assert odds["jackpot"] == pytest.approx(4_500_000 * 15)  # drawn in the Gold Ball Draw, then the gold ball
    assert odds["classic_jackpot"] == pytest.approx(13_983_816)
    assert odds["million_plus"] == pytest.approx(1 / (1 / 4_500_000 + 1 / 13_983_816))


def forecast_info(draw, plays, low, high):
    return dict(draw, forecast={"plays": plays, "low": low, "high": high})


def test_next_draw_value_brackets_the_forecast_range():
    info = forecast_info(lotto649(40_000_000, 15), 4_500_000, 4_300_000, 4_700_000)
    result = value.next_draw_value(model.LOTTO_649, info)
    low, high = result["per_dollar_range"]
    assert low < result["per_dollar"] < high
    assert result["per_dollar"] == pytest.approx(0.3686, abs=1e-4)
    assert result["per_dollar_all_prizes"] == pytest.approx(0.3686 + 0.1812, abs=2e-4)
    assert result["odds_one_in"]["jackpot"] == 67_500_000 and result["price"] == 3


def test_next_draw_value_needs_a_forecast():
    assert value.next_draw_value(model.LOTTO_649, lotto649(40_000_000, 15)) is None


def values(max_value, max_range, value_649, range_649):
    return {
        model.LOTTO_MAX: {"per_dollar": max_value, "per_dollar_range": max_range,
                          "per_dollar_all_prizes": max_value + 0.2, "per_dollar_all_prizes_range": [r + 0.2 for r in max_range]},
        model.LOTTO_649: {"per_dollar": value_649, "per_dollar_range": range_649,
                          "per_dollar_all_prizes": value_649 + 0.18, "per_dollar_all_prizes_range": [r + 0.18 for r in range_649]},
    }


def test_recommendation_picks_the_better_value_with_its_margin():
    result = value.recommend(values(0.332, [0.331, 0.333], 0.218, [0.214, 0.224]))
    assert result["top_prizes"] == {
        "game": model.LOTTO_MAX, "per_dollar": 0.332, "runner_up_per_dollar": 0.218, "margin": 0.114, "close_call": False,
    }
    assert result["all_prizes"]["game"] == model.LOTTO_MAX


@pytest.mark.parametrize(
    "max_value, value_649, play",
    [(0.332, 0.218, True), (0.30, 0.22, True), (0.25, 0.20, False), (0.12, 0.2999, False)],
)
def test_recommending_play_needs_the_minimum_in_big_prizes(max_value, value_649, play):
    result = value.recommend(values(max_value, [max_value, max_value], value_649, [value_649, value_649]))
    assert result["play"] is play
    assert result["min_per_dollar"] == value.MIN_WORTH_PLAYING == 0.30
    # the better game is still named, so the page can say which one came closest
    assert result["top_prizes"]["game"] == (model.LOTTO_MAX if max_value > value_649 else model.LOTTO_649)


def test_all_prize_values_dont_decide_whether_to_play():
    # $0.25 in big prizes is a skip even though counting every prize it's $0.45
    result = value.recommend(values(0.25, [0.25, 0.25], 0.20, [0.20, 0.20]))
    assert result["all_prizes"]["per_dollar"] == pytest.approx(0.45)
    assert result["play"] is False


def test_overlapping_ranges_are_a_close_call():
    result = value.recommend(values(0.30, [0.29, 0.31], 0.305, [0.28, 0.33]))
    assert result["top_prizes"]["game"] == model.LOTTO_649
    assert result["top_prizes"]["close_call"] is True


def test_no_recommendation_without_both_values():
    assert value.recommend({model.LOTTO_649: None, model.LOTTO_MAX: {"per_dollar": 0.3}}) is None


def test_annotate_history():
    records = [
        dict(lotto649(40_000_000, 15), game=model.LOTTO_649, est_plays=4_500_000),
        dict(lotto649(None, None), game=model.LOTTO_649, est_plays=4_500_000),  # Gold Ball state unknown
        dict(lottomax(60_000_000, 6), game=model.LOTTO_MAX, est_plays=5_340_000),
    ]
    value.annotate(records)
    assert [r["value_per_dollar"] for r in records] == [0.3686, None, 0.3316]


@pytest.fixture(scope="module")
def history():
    return store.load_draws(HISTORY)


def within_three_sd(expected, variance, observed):
    return abs(observed - expected) < 3 * math.sqrt(variance)


def test_gold_ball_and_classic_wins_match_the_model_over_history(history):
    draws = [d for d in history if d["game"] == model.LOTTO_649]
    gold = [1 / d["balls_remaining"] for d in draws]
    assert within_three_sd(sum(gold), sum(q * (1 - q) for q in gold), sum(d["gold_ball_drawn"] == "gold" for d in draws))
    classic = [d["est_plays"] * value.CLASSIC_ODDS for d in draws]
    assert within_three_sd(sum(classic), sum(classic), sum(d["tier_winners"]["6/6"] for d in draws))


def test_lotto_max_prizes_won_match_the_model_over_history(history):
    draws = [d for d in history if d["game"] == model.LOTTO_MAX]
    won = {d["draw_number"]: -math.expm1(-d["est_plays"] * value.LOTTO_MAX_SERIES_ODDS) for d in draws}
    for count, observed in (("maxplus_count", "maxplus_won"), ("maxmillions_count", "maxmillions_won")):
        expected = sum(d[count] * won[d["draw_number"]] for d in draws)
        variance = sum(d[count] * won[d["draw_number"]] * (1 - won[d["draw_number"]]) for d in draws)
        assert within_three_sd(expected, variance, sum(d[observed] for d in draws))
