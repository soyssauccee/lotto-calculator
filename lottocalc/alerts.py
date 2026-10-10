"""Deciding when to tell the owner something: stale data, a draw's outcome, or a value worth knowing about.

Everything here compares the next.json a run started with to the one it wrote.
"""
from datetime import date

from . import model, value

# Warnings that mean a source is degrading even though the data is still current.
DEGRADED_MARKERS = ("backup source", "unreadable")
CRASHED = "The scraper stopped before writing new data. The run log has the details."
DEFAULT_VALUE_THRESHOLD = 0.55  # whole-ticket value per $1 that sends an alert; matches WHOLE_TICKET_MINIMUM in web/app.js


def problems(doc):
    """Errors and source-degradation warnings recorded in a next.json."""
    if not doc:
        return []
    found = list(doc.get("errors") or [])
    found += [w for w in doc.get("warnings") or [] if any(marker in w for marker in DEGRADED_MARKERS)]
    return found


def run_problems(previous, current):
    """Problems with the run that turned `previous` into `current` ([] if it went fine)."""
    if not current or current.get("scraped_at") == (previous or {}).get("scraped_at"):
        return [CRASHED]
    return problems(current)


def should_report(previous, current):
    """Report a crash at once, but other problems only once they have lasted two runs,
    so a single network blip doesn't send an alert."""
    found = run_problems(previous, current)
    return bool(found) and (found == [CRASHED] or bool(problems(previous)))


def verdict(doc):
    """The game a next.json recommends, "skip" if neither is worth playing, or None without a recommendation."""
    recommendation = (doc or {}).get("recommendation") or {}
    top = recommendation.get("top_prizes")
    if not top:
        return None
    # next.json files written before the minimum existed lack "play"
    play = recommendation.get("play", top["per_dollar"] >= value.MIN_WORTH_PLAYING)
    return top["game"] if play else "skip"


def finished_draws(previous, current):
    """Games whose next draw moved on between the two: a draw was held and the next jackpot is
    posted. While a jackpot isn't posted yet the draw number is missing, so that counts once
    the number appears."""
    games = []
    for game in model.GAMES:
        before, now = previous.get(game), current.get(game) or {}
        if before and now.get("draw_number") and now["draw_number"] > (before.get("draw_number") or 0):
            games.append(game)
    return games


def value_alerts(previous, current, threshold=DEFAULT_VALUE_THRESHOLD):
    """Messages for a change of verdict (play one game, the other, or skip; judged on big prizes);
    after each draw, once the next jackpot is posted, whether to keep playing if the verdict
    didn't change; and for a draw whose whole ticket, every prize counted, is worth `threshold`
    or more per $1."""
    if not current:
        return []
    previous = previous or {}
    alerts = []
    now, before = verdict(current), verdict(previous)
    finished = finished_draws(previous, current)
    if now and finished and now == before:
        alerts.append(_after_draw(previous, current, finished, now))
    if now and before and now != before:
        recommendation = current["recommendation"]
        top = recommendation["top_prizes"]
        best, other = top["game"], model.LOTTO_649 if top["game"] == model.LOTTO_MAX else model.LOTTO_MAX
        info = current[best]
        if now == "skip":
            alerts.append(
                f"Neither game is worth playing now: the better one, {model.GAME_NAMES[best]}, is at "
                f"${top['per_dollar']:.2f} back per $1, {_short_of(recommendation, top['per_dollar'])}."
            )
        elif before == "skip":
            alerts.append(
                f"{model.GAME_NAMES[best]} is worth playing: ${top['per_dollar']:.2f} back per $1 for the "
                f"{info['draw_date']} draw ({_prizes(best, info)}). {model.GAME_NAMES[other]} is at "
                f"${top['runner_up_per_dollar']:.2f}."
            )
        else:
            alerts.append(
                f"{model.GAME_NAMES[best]} is now the better buy: ${top['per_dollar']:.2f} vs "
                f"${top['runner_up_per_dollar']:.2f} back per $1 for the {info['draw_date']} draw ({_prizes(best, info)})."
            )
    for game in model.GAMES:
        info = current.get(game) or {}
        values = info.get("value") or {}
        worth = values.get("per_dollar_all_prizes")
        if worth is None or worth < threshold:
            continue
        earlier = previous.get(game) or {}
        earlier_worth = (earlier.get("value") or {}).get("per_dollar_all_prizes")
        if earlier.get("draw_number") == info.get("draw_number") and earlier_worth is not None and earlier_worth >= threshold:
            continue  # already alerted for this draw
        message = (
            f"{model.GAME_NAMES[game]}'s whole ticket is worth ${worth:.2f} back per $1 for the {info['draw_date']} "
            f"draw ({_prizes(game, info)}), {_against(worth, threshold)} your ${threshold:.2f} alert."
        )
        if now == "skip":  # the play/skip verdict goes by big prizes, so say this doesn't change it
            big = values["per_dollar"]
            message += f" Still a skip: big prizes are ${big:.2f}, {_short_of(current['recommendation'], big)}."
        alerts.append(message)
    return alerts


def _after_draw(previous, current, finished, now):
    """The post-draw message when the verdict stayed the same."""
    held = " and ".join(
        f"{date.fromisoformat(previous[g]['draw_date']):%A}'s {model.GAME_NAMES[g]}" if previous[g].get("draw_date")
        else model.GAME_NAMES[g]
        for g in sorted(finished, key=lambda g: previous[g].get("draw_date") or "")
    ) + (" draws" if len(finished) > 1 else " draw")
    recommendation = current["recommendation"]
    top = recommendation["top_prizes"]
    best, other = top["game"], model.LOTTO_649 if top["game"] == model.LOTTO_MAX else model.LOTTO_MAX
    if now == "skip":
        return (f"After {held}: still nothing worth playing. The better one, {model.GAME_NAMES[best]}, is at "
                f"${top['per_dollar']:.2f} back per $1, {_short_of(recommendation, top['per_dollar'])}.")
    info = current[best]
    return (f"After {held}: keep playing {model.GAME_NAMES[best]}: ${top['per_dollar']:.2f} back per $1 for "
            f"{date.fromisoformat(info['draw_date']):%a %b %d} ({_prizes(best, info)}). "
            f"{model.GAME_NAMES[other]} is at ${top['runner_up_per_dollar']:.2f}.")


def _against(amount, line):
    """How `amount` stands against `line`, in words that agree with both shown to the cent:
    $0.3996 is "just under" a $0.40 minimum, not "$0.40 back per $1, under your $0.40 minimum"."""
    if f"{amount:.2f}" == f"{line:.2f}":
        return "at" if amount >= line else "just under"
    return "above" if amount >= line else "under"


def _short_of(recommendation, amount):
    """'under your $0.40 minimum' for a big-prize value that is under it."""
    minimum = recommendation.get("min_per_dollar", value.MIN_WORTH_PLAYING)  # files from before the minimum lack it
    return f"{_against(amount, minimum)} your ${minimum:.2f} minimum"


def _prizes(game, info):
    if game == model.LOTTO_MAX:
        extra = f" + {info['maxmillions_count']} x $1M" if info.get("maxmillions_count") else ""
        return f"${info['jackpot'] / 1e6:.0f}M jackpot{extra}"
    return f"${info['gold_ball_amount'] / 1e6:.0f}M Gold Ball, {info['balls_remaining']} balls left"
