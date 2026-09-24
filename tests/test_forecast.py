import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from lottocalc import forecast, model, store

HISTORY = Path(__file__).parent / "fixtures" / "draws_history.json"  # real draws through 6/49 #4452


def synthetic_649(count, noise=0.0, seed=1):
    """6/49 draws whose sales follow a known formula, cycling through the Gold Ball ladder."""
    rng = np.random.default_rng(seed)
    draws, day, balls = [], date(2022, 9, 14), 30
    for i in range(count):
        jackpot = model.GOLD_BALL_BASE + model.GOLD_BALL_STEP * (30 - balls)
        log_plays = 15.2 + 0.05 * jackpot / 1e7 + 0.3 / balls + 0.07 * (day.weekday() == 5)
        draws.append({
            "game": model.LOTTO_649,
            "draw_number": model.GOLD_BALL_FIRST_DRAW + i,
            "draw_date": day.isoformat(),
            "gold_ball_amount": jackpot,
            "balls_remaining": balls,
            "super_draw_prizes": [],
            "est_plays": round(math.exp(log_plays + noise * rng.standard_normal())),
        })
        balls = 30 if balls <= 15 else balls - 1
        day += timedelta(days=3 if day.weekday() == 2 else 4)
    return draws


def upcoming_after(draws, balls=20):
    last = date.fromisoformat(draws[-1]["draw_date"])
    day = last + timedelta(days=3 if last.weekday() == 2 else 4)
    jackpot = model.GOLD_BALL_BASE + model.GOLD_BALL_STEP * (30 - balls)
    return {"draw_number": draws[-1]["draw_number"] + 1, "draw_date": day.isoformat(),
            "gold_ball_amount": jackpot, "balls_remaining": balls}


def test_backtest_recovers_an_exact_model():
    predictions = forecast.backtest(model.LOTTO_649, synthetic_649(150))
    assert len(predictions) == 150 - forecast.MIN_TRAINING[model.LOTTO_649]
    assert max(abs(p.error) for p in predictions) < 1e-6


def test_forecast_of_an_exact_model_hits_the_true_value():
    draws = synthetic_649(150)
    upcoming = upcoming_after(draws, balls=20)
    day = date.fromisoformat(upcoming["draw_date"])
    truth = math.exp(15.2 + 0.05 * upcoming["gold_ball_amount"] / 1e7 + 0.3 / 20 + 0.07 * (day.weekday() == 5))
    result = forecast.forecast_next(model.LOTTO_649, draws, upcoming)
    assert result["plays"] == pytest.approx(truth, rel=1e-4)
    assert result["low"] <= result["plays"] <= result["high"]


def test_backtest_uses_only_earlier_draws():
    draws = synthetic_649(160, noise=0.05)
    cut = 130
    altered = [dict(d, est_plays=d["est_plays"] * 2) if i >= cut else d for i, d in enumerate(draws)]
    before = {p.draw_number: p.predicted for p in forecast.backtest(model.LOTTO_649, draws)}
    after = {p.draw_number: p.predicted for p in forecast.backtest(model.LOTTO_649, altered)}
    for number, predicted in before.items():
        if number <= draws[cut]["draw_number"]:
            assert after[number] == pytest.approx(predicted, rel=1e-12)
        else:
            assert after[number] != pytest.approx(predicted, rel=1e-3)


def test_recent_misses_pull_the_forecast():
    draws = synthetic_649(150)
    upcoming = upcoming_after(draws)
    plain = forecast.forecast_next(model.LOTTO_649, draws, upcoming)["plays"]
    hot = [dict(d, est_plays=round(d["est_plays"] * 1.10)) if i >= 146 else d for i, d in enumerate(draws)]
    assert 1.04 < forecast.forecast_next(model.LOTTO_649, hot, upcoming)["plays"] / plain < 1.10


def test_draws_with_an_unknown_gold_ball_state_are_left_out():
    draws = synthetic_649(150)
    draws[140] = dict(draws[140], gold_ball_amount=None, balls_remaining=None)  # e.g. cut off by a failed fetch
    result = forecast.forecast_next(model.LOTTO_649, draws, upcoming_after(draws))
    assert result is not None and result["plays"] > 0
    assert len(forecast.backtest(model.LOTTO_649, draws)) == 149 - forecast.MIN_TRAINING[model.LOTTO_649]


def test_too_little_history_gives_no_forecast():
    draws = synthetic_649(forecast.MIN_TRAINING[model.LOTTO_649] + 5)
    assert forecast.forecast_next(model.LOTTO_649, draws, upcoming_after(draws)) is None


def predictions_with_errors(errors, special=False):
    return [forecast.Prediction(i, "2026-01-01", special, 1, 1.0, e) for i, e in enumerate(errors)]


def test_range_from_few_errors_assumes_normal_errors():
    errors = [0.02, -0.03] * 15  # 30 errors: too few to trust their 10th/90th percentiles
    low, high = forecast._error_range(predictions_with_errors(errors), special=False)
    rms = math.sqrt(np.mean(np.square(errors)))
    assert (low, high) == pytest.approx((-forecast.Z_80 * rms, forecast.Z_80 * rms))


def test_range_from_many_errors_uses_their_quantiles():
    errors = list(np.linspace(-0.10, 0.02, 101))
    low, high = forecast._error_range(predictions_with_errors(errors), special=False)
    assert (low, high) == pytest.approx((-0.088, 0.008))


def test_special_draws_get_their_own_range():
    predictions = predictions_with_errors([0.01, -0.01] * 30) + predictions_with_errors([0.2, -0.2] * 30, special=True)
    ordinary = forecast._error_range(predictions, special=False)
    special = forecast._error_range(predictions, special=True)
    assert special[1] - special[0] > 10 * (ordinary[1] - ordinary[0])


@pytest.fixture(scope="module")
def history():
    return store.load_draws(HISTORY)


@pytest.mark.parametrize("game", model.GAMES)
def test_backtest_on_real_history_meets_the_target(history, game):
    stats = forecast.accuracy(forecast.backtest(game, [d for d in history if d["game"] == game]))
    assert stats["mape"] < 0.035  # target was +/-15%
    assert stats["within_15pct"] > 0.95
    assert 0.7 < stats["range_coverage"] < 0.95
    assert abs(stats["bias"]) < 0.03


def test_forecast_for_a_draw_the_history_has_not_seen(history):
    # 6/49 #4453 (2026-09-23) sold 3,651,921 plays; the history stops at #4452.
    upcoming = {"draw_number": 4453, "draw_date": "2026-09-23", "gold_ball_amount": 10_000_000, "balls_remaining": 30}
    result = forecast.forecast_next(model.LOTTO_649, [d for d in history if d["game"] == model.LOTTO_649], upcoming)
    assert result["low"] <= 3_651_921 <= result["high"]
    assert result["plays"] == pytest.approx(3_651_921, rel=0.05)
    assert result["assumes_no_super_draw"] is True and result["special"] is False


def test_lotto_max_forecast_on_real_history(history):
    upcoming = {"draw_number": 1273, "draw_date": "2026-09-25", "jackpot": 60_000_000}
    result = forecast.forecast_next(model.LOTTO_MAX, [d for d in history if d["game"] == model.LOTTO_MAX], upcoming)
    assert 4_500_000 < result["plays"] < 6_500_000
    assert result["low"] < result["plays"] < result["high"]
    assert result["assumes_no_super_draw"] is False
