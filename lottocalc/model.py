"""Game rules shared by every source, and the checks that catch parser drift."""
import re
from datetime import date, timedelta

LOTTO_649 = "lotto649"
LOTTO_MAX = "lottomax"
GAMES = (LOTTO_649, LOTTO_MAX)
GAME_NAMES = {LOTTO_649: "Lotto 6/49", LOTTO_MAX: "Lotto Max"}

# Prize categories, top to bottom; the keys of tier_winners and tier_prizes.
TIERS = {
    LOTTO_649: ("6/6", "5/6+B", "5/6", "4/6", "3/6", "2/6+B", "2/6"),
    LOTTO_MAX: ("7/7", "6/7+B", "6/7", "5/7+B", "5/7", "4/7+B", "4/7", "3/7+B", "3/7"),
}
NUMBERS_DRAWN = {LOTTO_649: 6, LOTTO_MAX: 7}
HIGHEST_NUMBER = {LOTTO_649: 49, LOTTO_MAX: 52}
DRAW_WEEKDAYS = {LOTTO_649: (2, 5), LOTTO_MAX: (1, 4)}  # Wed/Sat and Tue/Fri

CLASSIC_JACKPOT = 5_000_000  # fixed 6/49 6/6 prize, shared between winners

# Gold Ball Jackpot Draw: 29 white balls and 1 gold ball. A white ball pays $1M,
# is removed, and grows the jackpot by $2M; the gold ball pays the jackpot and
# resets the drum.
GOLD_BALL_BALLS = 30
GOLD_BALL_BASE = 10_000_000
GOLD_BALL_STEP = 2_000_000
WHITE_BALL_PRIZE = 1_000_000
GOLD_BALL_FIRST_DRAW = 4033  # 2022-09-14

LOTTO_MAX_JACKPOT_RANGE = (10_000_000, 90_000_000)
MAXMILLIONS_FROM = 50_000_000  # MAXMILLIONS prizes are offered at or above this jackpot
MAXPLUS_TRANCHE = 1_000_000  # at least one MAXPLUS prize per $1M of jackpot
LOTTO_MAX_752_FIRST_DRAW = 1226  # 2026-04-14, first 7/52 $6 draw

# First draw of each game's current format; older draws have other odds and prices.
FORMAT_FIRST_DRAW = {LOTTO_649: GOLD_BALL_FIRST_DRAW, LOTTO_MAX: LOTTO_MAX_752_FIRST_DRAW}

_TIER_LABEL = re.compile(r"^(\d)\s*of\s*(\d)\s*(\+\s*bonus)?$", re.IGNORECASE)


def tier_key(label):
    """'5 of 6 + Bonus' -> '5/6+B'; None when label is not a prize category."""
    match = _TIER_LABEL.match(label.strip())
    if not match:
        return None
    return f"{match[1]}/{match[2]}" + ("+B" if match[3] else "")


def balls_for_jackpot(jackpot):
    """Balls in the Gold Ball drum when the jackpot is `jackpot`; None if off the ladder."""
    whites_drawn, remainder = divmod(jackpot - GOLD_BALL_BASE, GOLD_BALL_STEP)
    balls = GOLD_BALL_BALLS - whites_drawn
    if remainder or not 1 <= balls <= GOLD_BALL_BALLS:
        return None
    return balls


def expected_maxmillions(jackpot):
    """MAXMILLIONS prizes ILC has offered at this jackpot: 2 more per $5M from $50M (50→2 ... 70→10)."""
    if jackpot < MAXMILLIONS_FROM:
        return 0
    return 2 * ((jackpot - MAXMILLIONS_FROM) // 5_000_000 + 1)


def draws_between(game, after, until):
    """Scheduled draw dates d with after < d <= until."""
    dates = []
    day = after + timedelta(days=1)
    while day <= until:
        if day.weekday() in DRAW_WEEKDAYS[game]:
            dates.append(day)
        day += timedelta(days=1)
    return dates


def derive_gold_ball(draws, next_draw=None):
    """Fill gold_ball_amount and balls_remaining on 6/49 records, in place.

    Past draws don't show the jackpot, but it follows from the balls drawn.
    Anchors are the format's first draw ($10M), every gold-ball draw (its prize
    is that draw's jackpot) and the jackpot advertised for the next draw; runs
    of consecutive draw numbers are then walked forward and backward from them.
    Returns warnings for disagreements, which mean a parsing bug or a rule change.
    """
    by_number = {d["draw_number"]: d for d in draws}
    known, warnings = {}, []

    def settle(number, jackpot, how):
        if number not in known:
            known[number] = jackpot
        elif known[number] != jackpot:
            warnings.append(
                f"Lotto 6/49 draw {number}: Gold Ball jackpot from {how} is ${jackpot:,}, "
                f"but ${known[number]:,} was derived first"
            )

    for number, draw in by_number.items():
        if draw.get("gold_ball_drawn") == "gold" and draw.get("gold_ball_prize"):
            settle(number, draw["gold_ball_prize"], "its gold-ball prize")
    if GOLD_BALL_FIRST_DRAW in by_number:
        settle(GOLD_BALL_FIRST_DRAW, GOLD_BALL_BASE, "the format start")
    if next_draw and next_draw.get("draw_number") and next_draw.get("gold_ball_amount"):
        settle(next_draw["draw_number"], next_draw["gold_ball_amount"], "the next-draw listing")

    numbers = sorted(by_number)
    for number in numbers:
        ball = by_number[number].get("gold_ball_drawn")
        if number in known and ball in ("gold", "white"):
            after = GOLD_BALL_BASE if ball == "gold" else known[number] + GOLD_BALL_STEP
            settle(number + 1, after, f"draw {number}")
    for number in reversed(numbers):
        if number + 1 in known and by_number[number].get("gold_ball_drawn") == "white":
            settle(number, known[number + 1] - GOLD_BALL_STEP, f"draw {number + 1}")

    unresolved = []
    for number in numbers:
        draw, jackpot = by_number[number], known.get(number)
        draw["gold_ball_amount"] = jackpot
        draw["balls_remaining"] = balls_for_jackpot(jackpot) if jackpot else None
        if jackpot is None:
            unresolved.append(number)
        elif draw["balls_remaining"] is None:
            warnings.append(f"Lotto 6/49 draw {number}: ${jackpot:,} is not on the Gold Ball ladder")
    if unresolved:
        warnings.append(
            f"Lotto 6/49: Gold Ball jackpot unknown for {len(unresolved)} draw(s) "
            f"not linked to an anchor ({unresolved[0]}..{unresolved[-1]})"
        )
    return warnings


def check_history(game, draws):
    """Warnings for missing draw numbers and draws off the Tue/Fri or Wed/Sat schedule.

    `draws` is the game's records sorted by draw_number.
    """
    name, warnings = GAME_NAMES[game], []
    if draws and draws[0]["draw_number"] > FORMAT_FIRST_DRAW[game]:
        warnings.append(f"{name}: history starts at draw {draws[0]['draw_number']}, not {FORMAT_FIRST_DRAW[game]}")
    for before, after in zip(draws, draws[1:]):
        first, second = before["draw_number"], after["draw_number"]
        if second != first + 1:
            warnings.append(f"{name}: draws {first + 1}..{second - 1} missing")
            continue
        start, end = date.fromisoformat(before["draw_date"]), date.fromisoformat(after["draw_date"])
        if draws_between(game, start, end) != [end]:
            warnings.append(f"{name}: draw {second} on {end} is not the next scheduled draw after {start}")
    return warnings


def check_draw(record):
    """Problems that mean a draw record was parsed wrongly (empty list if none)."""
    game, problems = record["game"], []
    numbers, bonus = record.get("numbers") or [], record.get("bonus")
    highest = HIGHEST_NUMBER[game]
    if (
        len(numbers) != NUMBERS_DRAWN[game]
        or len(set(numbers + [bonus])) != NUMBERS_DRAWN[game] + 1
        or not all(isinstance(n, int) and 1 <= n <= highest for n in numbers + [bonus])
    ):
        problems.append(f"winning numbers {numbers} bonus {bonus}")
    missing = [t for t in TIERS[game] if t not in record.get("tier_winners", {})]
    if missing:
        problems.append(f"missing prize categories {missing}")
    elif not record["tier_winners"][TIERS[game][-1]]:
        problems.append(f"no winners in the {TIERS[game][-1]} category")

    if game == LOTTO_649:
        ball, prize = record.get("gold_ball_drawn"), record.get("gold_ball_prize")
        if ball not in ("gold", "white"):
            problems.append(f"gold ball drawn {ball!r}")
        elif ball == "white" and prize != WHITE_BALL_PRIZE:
            problems.append(f"white-ball prize ${prize}")
        elif ball == "gold" and not (prize and prize >= GOLD_BALL_BASE):
            problems.append(f"gold-ball prize ${prize}")
    else:
        low, high = LOTTO_MAX_JACKPOT_RANGE
        if not (record.get("jackpot") and low <= record["jackpot"] <= high):
            problems.append(f"jackpot {record.get('jackpot')}")
        if not record.get("maxplus_count"):
            problems.append("no MAXPLUS prizes found")
    return problems


def check_next(game, info):
    """(errors, warnings) for next-draw info. Fills in what the rules imply when a source omits it:
    6/49 balls remaining from the jackpot, Lotto Max MAXPLUS and MAXMILLIONS counts from the jackpot."""
    name, errors, warnings = GAME_NAMES[game], [], []
    if not info.get("draw_date"):
        errors.append(f"{name}: next draw date missing")
    if game == LOTTO_649:
        amount = info.get("gold_ball_amount")
        if not amount:
            errors.append(f"{name}: next Gold Ball jackpot missing")
            return errors, warnings
        ladder = balls_for_jackpot(amount)
        if info.get("balls_remaining") is None:
            info["balls_remaining"] = ladder
            warnings.append(f"{name}: balls remaining not shown; derived {ladder} from the jackpot")
        elif info["balls_remaining"] != ladder:
            warnings.append(
                f"{name}: {info['balls_remaining']} balls remaining doesn't match "
                f"the ${amount:,} jackpot (expected {ladder})"
            )
    else:
        jackpot = info.get("jackpot")
        if not jackpot:
            errors.append(f"{name}: next jackpot missing")
            return errors, warnings
        low, high = LOTTO_MAX_JACKPOT_RANGE
        if not low <= jackpot <= high:
            warnings.append(f"{name}: next jackpot ${jackpot:,} is outside the usual range")
        if info.get("maxplus_count") is None:
            info["maxplus_count"], info["maxplus_prize"] = jackpot // MAXPLUS_TRANCHE, 100_000
            warnings.append(f"{name}: MAXPLUS prizes not shown; assumed {info['maxplus_count']} x $100,000")
        elif info["maxplus_count"] < jackpot // MAXPLUS_TRANCHE:
            warnings.append(f"{name}: only {info['maxplus_count']} MAXPLUS prizes for a ${jackpot:,} jackpot")
        if info.get("maxmillions_count") is None:
            info["maxmillions_count"] = expected_maxmillions(jackpot)
            warnings.append(f"{name}: MAXMILLIONS count not shown; assumed {info['maxmillions_count']} from the jackpot")
    return errors, warnings
