"""What a ticket is worth per dollar, and which game is the better buy.

A value is the expected payout per $1 spent: each prize times its odds, times
the share you would keep if other tickets win it too.

Lotto Max ($6 play, 4 lines). The main jackpot, each MAXPLUS series and each
MAXMILLIONS series is matched by 1 line in C(52,7), so a play wins a given one
with p = 4 / C(52,7) = 1 in 33,446,140. With N plays sold, the other winning
lines are Poisson with mean λ = N·p, so the expected share of a prize is
s = (1 - e^-λ) / λ, and

    value = s · (jackpot + MAXPLUS prizes + MAXMILLIONS prizes) · p / $6

Lotto 6/49 ($3 play). One play's number out of N wins the Gold Ball Draw: the
jackpot with probability 1/balls, otherwise $1M, never shared. The Classic 6/6
$5M is shared like a Lotto Max series. Super Draw prizes, when known, are also
drawn from play numbers:

    value = [ (J/balls + $1M · (1 - 1/balls) + Super Draw prizes) / N
              + s · $5M / C(49,6) ] / $3

The lower categories are valued separately (lower_tier_value) so they can be
switched on and off; they add about $0.18 (6/49) and $0.20 (Lotto Max) per $1.
"""
import math

from . import model, sales

PRICE = sales.PRICE
MIN_WORTH_PLAYING = 0.30  # big-prize value per $1 below which neither game is recommended
LOTTO_MAX_SERIES_ODDS = sales.LINES_PER_PLAY[model.LOTTO_MAX] / math.comb(52, 7)  # per play
CLASSIC_ODDS = sales.tier_probability(model.LOTTO_649, "6/6")
MAXMILLIONS_PRIZE = 1_000_000
TOP_PRIZE_PARTS = {
    model.LOTTO_649: ("gold_ball", "classic_jackpot", "super_draw"),
    model.LOTTO_MAX: ("jackpot", "maxplus", "maxmillions"),
}


def split_factor(expected_others):
    """Expected share of a prize when the number of other winners is Poisson with this mean."""
    if expected_others < 1e-12:
        return 1.0
    return -math.expm1(-expected_others) / expected_others


def lower_tier_value(game, plays):
    """Expected winnings per play from the categories below the jackpots.

    Fixed prizes at their odds, free plays at the deemed value in the game
    conditions, and each pooled category's expected share of the Pools Fund,
    which a ticket only collects when that category is won at all.
    """
    odds = {t: sales.tier_probability(game, t) * sales.LINES_PER_PLAY[game] for t in model.TIERS[game]}
    fixed = sum(odds[t] * amount for t, amount in sales.FIXED_PRIZES[game].items())
    pools_per_play = sales.PRIZE_FUND_PER_PLAY[game] - fixed
    pooled = sum(share * pools_per_play * -math.expm1(-plays * odds[t]) for t, share in sales.POOL_SHARES[game].items())
    return fixed + pooled


def evaluate(game, draw, plays):
    """(value parts per $1, odds per play as 'one in') for a draw with `plays` sold.

    `draw` is a stored draw record or next-draw info; both use the same field names.
    """
    price = PRICE[game]
    if game == model.LOTTO_649:
        jackpot, balls = draw["gold_ball_amount"], draw["balls_remaining"]
        super_prizes = sum(p["prize"] * p["count"] for p in draw.get("super_draw_prizes") or [])
        classic_share = split_factor(plays * CLASSIC_ODDS)
        parts = {
            "gold_ball": (jackpot / balls + model.WHITE_BALL_PRIZE * (1 - 1 / balls)) / plays / price,
            "classic_jackpot": classic_share * model.CLASSIC_JACKPOT * CLASSIC_ODDS / price,
            "super_draw": super_prizes / plays / price,
        }
        odds = {
            "jackpot": plays * balls,  # the Gold Ball jackpot
            "classic_jackpot": 1 / CLASSIC_ODDS,
            "million_plus": 1 / (1 / plays + CLASSIC_ODDS),
        }
    else:
        p = LOTTO_MAX_SERIES_ODDS
        share = split_factor(plays * p)
        maxmillions = draw.get("maxmillions_count") or 0
        parts = {
            "jackpot": share * draw["jackpot"] * p / price,
            "maxplus": share * (draw.get("maxplus_count") or 0) * (draw.get("maxplus_prize") or 0) * p / price,
            "maxmillions": share * maxmillions * MAXMILLIONS_PRIZE * p / price,
        }
        # A shared MAXMILLIONS prize falls below $1M, so those only count when nobody else wins them.
        odds = {"jackpot": 1 / p, "million_plus": 1 / (p * (1 + maxmillions * math.exp(-plays * p)))}
    parts["lower_tiers"] = lower_tier_value(game, plays) / price
    return parts, odds


def top_prize_value(game, parts):
    return sum(parts[k] for k in TOP_PRIZE_PARTS[game])


def annotate(records):
    """Set value_per_dollar (top prizes, with the plays actually sold) on each record, in place."""
    for record in records:
        game, plays = record["game"], record.get("est_plays")
        known = plays and (game == model.LOTTO_MAX or record.get("balls_remaining"))
        record["value_per_dollar"] = round(top_prize_value(game, evaluate(game, record, plays)[0]), 4) if known else None


def next_draw_value(game, info):
    """Value of a ticket for the upcoming draw, using the sales forecast; None without one."""
    forecast = info.get("forecast")
    if not forecast:
        return None
    parts, odds = evaluate(game, info, forecast["plays"])
    top = top_prize_value(game, parts)
    total = top + parts["lower_tiers"]
    # Selling more plays lowers the value, so the forecast's 80% range bounds it.
    bounds = [evaluate(game, info, forecast[end])[0] for end in ("high", "low")]
    tops = [top_prize_value(game, b) for b in bounds]
    totals = [top_prize_value(game, b) + b["lower_tiers"] for b in bounds]
    return {
        "per_dollar": round(top, 4),
        "per_dollar_range": [round(min(tops), 4), round(max(tops), 4)],
        "per_dollar_all_prizes": round(total, 4),
        "per_dollar_all_prizes_range": [round(min(totals), 4), round(max(totals), 4)],
        "parts": {k: round(v, 4) for k, v in parts.items()},
        "odds_one_in": {k: round(v) for k, v in odds.items()},
        "price": PRICE[game],
    }


def recommend(values):
    """Whether either game is worth playing, and the better buy by top-prize and by all-prize value.

    `values` maps each game to its next_draw_value. `play` is false when neither
    game reaches MIN_WORTH_PLAYING per $1 in big prizes; the all-prize values run
    about $0.20 higher, so they don't decide it. A close call means the runner-up
    could come out ahead within the sales forecasts' 80% ranges.
    """
    if any(values.get(game) is None for game in model.GAMES):
        return None
    result = {
        "play": max(values[game]["per_dollar"] for game in model.GAMES) >= MIN_WORTH_PLAYING,
        "min_per_dollar": MIN_WORTH_PLAYING,
    }
    for basis, key in (("top_prizes", "per_dollar"), ("all_prizes", "per_dollar_all_prizes")):
        best, other = sorted(model.GAMES, key=lambda g: values[g][key], reverse=True)
        result[basis] = {
            "game": best,
            "per_dollar": values[best][key],
            "runner_up_per_dollar": values[other][key],
            "margin": round(values[best][key] - values[other][key], 4),
            "close_call": values[best][f"{key}_range"][0] <= values[other][f"{key}_range"][1],
        }
    return result
