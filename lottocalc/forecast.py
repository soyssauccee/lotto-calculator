"""Forecast how many plays a draw will sell, before it happens.

For each game, log(plays) is fitted by least squares on what is known before
a draw: the jackpot, the Gold Ball balls, the weekday, Super Draw prizes, the
holiday season and a slow trend. Sales drift in runs, so the fit is then
nudged toward the average miss on the last few ordinary draws.

The accuracy claims come from a walk-forward backtest: every past draw is
predicted from earlier draws only. The 80% range is taken from those
out-of-sample errors in similar draws, so it widens where the model has been
less reliable (few balls left, Super Draws, the holidays). With too few past
errors to trust their tails, it assumes normal errors of the same size.

An upcoming Super Draw is not announced anywhere this project can read, so
forecasts assume a normal draw; a Super Draw sells 6-18% more.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from . import model

LEVEL_WEIGHT = 0.7  # how much of the recent average miss to carry into the forecast
LEVEL_DRAWS = 4  # how many recent draws that average covers
RANGE = (0.10, 0.90)  # quantiles of past errors that bound the 80% range
Z_80 = 1.2816  # the same quantiles for normally distributed errors, in standard deviations
MIN_TRAINING = {model.LOTTO_649: 100, model.LOTTO_MAX: 16}  # draws before the first backtest prediction
MIN_REGIME_ERRORS = 20  # fewer past errors in a regime than this: use all past errors
MIN_QUANTILE_ERRORS = 50  # fewer past errors than this: too few to trust their tails
FORMAT_START = {model.LOTTO_649: date(2022, 9, 14), model.LOTTO_MAX: date(2026, 4, 14)}


def _holiday(day):
    return (day.month == 12 and day.day >= 15) or (day.month == 1 and day.day == 1)


def _features_649(draw):
    day = date.fromisoformat(draw["draw_date"])
    jackpot, balls = draw["gold_ball_amount"] / 1e7, draw["balls_remaining"]
    return {
        "gold_ball": jackpot,
        "gold_ball_sq": jackpot**2,
        "one_over_balls": 1 / balls,
        "guaranteed": float(balls == 1),
        "saturday": float(day.weekday() == 5),
        "super_prizes": sum(p["prize"] * p["count"] for p in draw.get("super_draw_prizes") or []) / 1e6,
        "holiday": float(_holiday(day)),
        "years": (day - FORMAT_START[model.LOTTO_649]).days / 365.25,
        "launch": float(day < FORMAT_START[model.LOTTO_649] + timedelta(days=7)),
    }


def _special_649(draw):
    day = date.fromisoformat(draw["draw_date"])
    return draw["balls_remaining"] <= 5 or bool(draw.get("super_draw_prizes")) or _holiday(day)


def _features_max(draw):
    jackpot = draw["jackpot"] / 1e7
    return {
        "jackpot": jackpot,
        "jackpot_sq": jackpot**2,
        "friday": float(date.fromisoformat(draw["draw_date"]).weekday() == 4),
    }


FEATURES = {model.LOTTO_649: _features_649, model.LOTTO_MAX: _features_max}
SPECIAL = {model.LOTTO_649: _special_649, model.LOTTO_MAX: lambda draw: False}


@dataclass
class Prediction:
    draw_number: int
    draw_date: str
    special: bool
    actual: int
    predicted: float
    error: float  # log(actual / predicted)


def _design(game, draws):
    rows = [FEATURES[game](d) for d in draws]
    return np.array([[1.0, *row.values()] for row in rows])


def _log_forecast(X, y, x_next):
    """Fit on (X, y), forecast x_next, and apply the recent-level correction."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    recent = (y - X @ beta)[-LEVEL_DRAWS:]
    return float(x_next @ beta + LEVEL_WEIGHT * recent.mean())


NEEDED = {
    model.LOTTO_649: ("est_plays", "gold_ball_amount", "balls_remaining"),
    model.LOTTO_MAX: ("est_plays", "jackpot"),
}


def _history(game, draws):
    """The game's draws with sales and every feature known, in draw order. A draw whose
    Gold Ball state couldn't be derived (after a fetch failure) is left out, not fatal."""
    usable = (d for d in draws if all(d.get(field) for field in NEEDED[game]))
    return sorted(usable, key=lambda d: d["draw_number"])


def backtest(game, draws):
    """Predict each draw after the first MIN_TRAINING from the draws before it only."""
    history = _history(game, draws)
    X = _design(game, history)
    y = np.log([d["est_plays"] for d in history])
    predictions = []
    for i in range(MIN_TRAINING[game], len(history)):
        log_predicted = _log_forecast(X[:i], y[:i], X[i])
        predictions.append(Prediction(
            draw_number=history[i]["draw_number"],
            draw_date=history[i]["draw_date"],
            special=SPECIAL[game](history[i]),
            actual=history[i]["est_plays"],
            predicted=float(np.exp(log_predicted)),
            error=float(y[i] - log_predicted),
        ))
    return predictions


def _error_range(predictions, special):
    """(low, high) bounds on the log error, from past predictions in the same regime."""
    same = [p.error for p in predictions if p.special == special]
    errors = np.array(same if len(same) >= MIN_REGIME_ERRORS else [p.error for p in predictions])
    if len(errors) >= MIN_QUANTILE_ERRORS:
        low, high = np.quantile(errors, RANGE)
        return float(low), float(high)
    spread = Z_80 * float(np.sqrt(np.mean(errors**2)))
    return -spread, spread


def accuracy(predictions):
    """Summary of backtest errors, including how often an honestly built 80% range held."""
    ape = np.abs(np.expm1([p.error for p in predictions]))
    covered = []
    for k in range(MIN_REGIME_ERRORS, len(predictions)):
        low, high = _error_range(predictions[:k], predictions[k].special)
        covered.append(low <= predictions[k].error <= high)

    def regime_mape(special):
        errors = [abs(np.expm1(p.error)) for p in predictions if p.special == special]
        return float(np.mean(errors)) if errors else None

    worst = predictions[int(np.argmax(ape))]
    return {
        "draws": len(predictions),
        "mape": float(ape.mean()),
        "median_ape": float(np.median(ape)),
        "p90_ape": float(np.quantile(ape, 0.9)),
        "within_15pct": float(np.mean(ape <= 0.15)),
        "bias": float(np.mean(np.expm1([p.error for p in predictions]))),
        "range_coverage": float(np.mean(covered)) if covered else None,
        "mape_ordinary": regime_mape(False),
        "mape_special": regime_mape(True),
        "worst": {"draw_number": worst.draw_number, "draw_date": worst.draw_date, "ape": float(ape.max())},
    }


def forecast_next(game, draws, upcoming):
    """Forecast for the upcoming draw ({'plays', 'low', 'high', ...}), or None if history is too short.

    `upcoming` is the next-draw info from next.json; it is treated as a normal (non-Super) draw.
    """
    history = _history(game, draws)
    if len(history) < MIN_TRAINING[game] + MIN_REGIME_ERRORS:
        return None
    predictions = backtest(game, history)
    X = _design(game, history)
    y = np.log([d["est_plays"] for d in history])
    upcoming_is_special = SPECIAL[game](upcoming)
    log_plays = _log_forecast(X, y, _design(game, [upcoming])[0])
    low, high = _error_range(predictions, upcoming_is_special)
    stats = accuracy(predictions)
    return {
        "plays": int(round(np.exp(log_plays))),
        "low": int(round(np.exp(log_plays + low))),
        "high": int(round(np.exp(log_plays + high))),
        "special": upcoming_is_special,
        "assumes_no_super_draw": game == model.LOTTO_649,
        "backtest_mape": round(stats["mape"], 4),
        "backtest_draws": stats["draws"],
    }
