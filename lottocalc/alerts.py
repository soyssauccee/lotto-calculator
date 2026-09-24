"""Deciding when to tell the owner something: stale data, or a value worth knowing about.

Everything here compares the next.json a run started with to the one it wrote.
"""
from . import model

# Warnings that mean a source is degrading even though the data is still current.
DEGRADED_MARKERS = ("backup source", "unreadable")
CRASHED = "The scraper stopped before writing new data. The run log has the details."
DEFAULT_VALUE_THRESHOLD = 0.50


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


def value_alerts(previous, current, threshold=DEFAULT_VALUE_THRESHOLD):
    """Messages for a change of better buy, and for a draw worth `threshold` or more per $1."""
    if not current:
        return []
    previous = previous or {}
    alerts = []
    now = (current.get("recommendation") or {}).get("top_prizes")
    before = (previous.get("recommendation") or {}).get("top_prizes")
    if now and before and now["game"] != before["game"]:
        info = current[now["game"]]
        alerts.append(
            f"{model.GAME_NAMES[now['game']]} is now the better buy: ${now['per_dollar']:.2f} vs "
            f"${now['runner_up_per_dollar']:.2f} back per $1 for the {info['draw_date']} draw ({_prizes(now['game'], info)})."
        )
    for game in model.GAMES:
        info = current.get(game) or {}
        worth = (info.get("value") or {}).get("per_dollar")
        if worth is None or worth < threshold:
            continue
        earlier = previous.get(game) or {}
        earlier_worth = (earlier.get("value") or {}).get("per_dollar")
        if earlier.get("draw_number") == info.get("draw_number") and earlier_worth is not None and earlier_worth >= threshold:
            continue  # already alerted for this draw
        alerts.append(
            f"{model.GAME_NAMES[game]} is worth ${worth:.2f} back per $1 for the {info['draw_date']} draw "
            f"({_prizes(game, info)}), above your ${threshold:.2f} alert."
        )
    return alerts


def _prizes(game, info):
    if game == model.LOTTO_MAX:
        extra = f" + {info['maxmillions_count']} x $1M" if info.get("maxmillions_count") else ""
        return f"${info['jackpot'] / 1e6:.0f}M jackpot{extra}"
    return f"${info['gold_ball_amount'] / 1e6:.0f}M Gold Ball, {info['balls_remaining']} balls left"
