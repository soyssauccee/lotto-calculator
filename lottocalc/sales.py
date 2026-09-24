"""Plays sold per draw, recovered from the published prize breakdown.

The game conditions put a fixed amount of every play into a Prize Fund. The
fixed prizes ($10/$5/$20 and free plays, at a set deemed value) are paid out
of it and the rest, the Pools Fund, is split between the shared categories by
fixed percentages. Each shared prize therefore reveals the Pools Fund, and

    plays = (Pools Fund + fixed prizes paid) / Prize Fund per play

is exact up to the 10-cent rounding of shared prizes (about 0.02%).

The textbook alternative, winners ÷ odds for a low category, is kept as a
cross-check only: players' favourite numbers make it swing ±5% per 6/49 draw.
"""
from math import comb

from . import model

PRICE = {model.LOTTO_649: 3, model.LOTTO_MAX: 6}
LINES_PER_PLAY = {model.LOTTO_649: 1, model.LOTTO_MAX: 4}  # Lotto Max winners are counted per line
PRIZE_FUND_PER_PLAY = {model.LOTTO_649: 0.55, model.LOTTO_MAX: 1.19}
FIXED_PRIZES = {
    model.LOTTO_649: {"3/6": 10, "2/6+B": 5, "2/6": 1.44},  # free play at its deemed value
    model.LOTTO_MAX: {"4/7": 20, "3/7+B": 20, "3/7": 2.88},
}
POOL_SHARES = {
    model.LOTTO_649: {"5/6+B": 0.3215, "5/6": 0.135, "4/6": 0.5435},
    model.LOTTO_MAX: {"6/7+B": 0.185, "6/7": 0.1885, "5/7+B": 0.1225, "5/7": 0.275, "4/7+B": 0.229},
}
# Low categories for the cross-check: many winners, so little random noise.
CHECK_TIERS = {model.LOTTO_649: ("4/6", "3/6", "2/6+B", "2/6"), model.LOTTO_MAX: ("4/7+B", "4/7", "3/7+B", "3/7")}

MAX_POOL_SPREAD = 0.01  # shared prizes implying Pools Funds further apart than this: parse bug or rule change
CHECK_RANGE = (0.8, 1.25)  # cross-check ratio outside this: something is off


def tier_probability(game, tier):
    """Chance that one line wins exactly `tier` ('3/7+B', '2/6', ...)."""
    drawn, pool = model.NUMBERS_DRAWN[game], model.HIGHEST_NUMBER[game]
    matched = int(tier.split("/")[0])
    others = pool - drawn - 1  # neither a winning number nor the bonus
    with_bonus = comb(drawn, matched) * comb(others, drawn - matched - 1) if matched < drawn else 0
    without_bonus = comb(drawn, matched) * comb(others, drawn - matched)
    if tier.endswith("+B"):
        ways = with_bonus
    elif f"{tier}+B" in model.TIERS[game]:
        ways = without_bonus
    else:
        ways = with_bonus + without_bonus
    return ways / comb(pool, drawn)


def pools_fund(record):
    """(Pools Fund, relative spread between the shared categories), or (None, None) if none was won."""
    shares = POOL_SHARES[record["game"]]
    winners, prizes = record["tier_winners"], record["tier_prizes"]
    implied = {t: winners[t] * prizes[t] / share for t, share in shares.items() if winners[t] and prizes[t]}
    if not implied:
        return None, None
    fund = sum(winners[t] * prizes[t] for t in implied) / sum(shares[t] for t in implied)
    return fund, (max(implied.values()) - min(implied.values())) / fund


def plays_from_prizes(record):
    """Plays sold, from the Pools Fund identity; None if no shared category was won."""
    game = record["game"]
    fund, _ = pools_fund(record)
    if fund is None:
        return None
    fixed = sum(record["tier_winners"][t] * amount for t, amount in FIXED_PRIZES[game].items())
    return round((fund + fixed) / PRIZE_FUND_PER_PLAY[game])


def plays_from_odds(record):
    """Plays sold if winners in the low categories matched their odds exactly."""
    game = record["game"]
    tiers = CHECK_TIERS[game]
    winners = sum(record["tier_winners"][t] for t in tiers)
    per_line = sum(tier_probability(game, t) for t in tiers)
    return round(winners / per_line / LINES_PER_PLAY[game])


def annotate(records):
    """Set est_plays and est_plays_check on each record, in place. Returns warnings."""
    warnings = []
    for record in records:
        name = f"{model.GAME_NAMES[record['game']]} draw {record['draw_number']}"
        plays, check = plays_from_prizes(record), plays_from_odds(record)
        record["est_plays"], record["est_plays_check"] = plays, check
        _, spread = pools_fund(record)
        if plays is None:
            warnings.append(f"{name}: no shared prize category won, so plays sold are unknown")
            continue
        if spread > MAX_POOL_SPREAD:
            warnings.append(f"{name}: shared prizes imply Pools Funds {spread:.1%} apart")
        low, high = CHECK_RANGE
        if not low <= check / plays <= high:
            warnings.append(f"{name}: {plays:,} plays from prizes but {check:,} from the odds")
    return warnings
