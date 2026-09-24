"""Which game is the better buy for the next draw, and why.

    python recommend.py                 compare on the big prizes (jackpots, Gold Ball, MAXPLUS, MAXMILLIONS)
    python recommend.py --all-prizes    include the lower prize categories too

Neither game is recommended when both are under $0.30 back per $1 in big prizes.

Reads data/next.json as written by the last `python scrape.py`.
"""
import argparse
import sys
from pathlib import Path

from lottocalc import model, store

DATA_DIR = Path(__file__).resolve().parent / "data"
PART_NAMES = {
    "gold_ball": "Gold Ball draw",
    "classic_jackpot": "Classic $5M",
    "super_draw": "Super Draw prizes",
    "jackpot": "Main jackpot",
    "maxplus": "MAXPLUS prizes",
    "maxmillions": "MAXMILLIONS prizes",
    "lower_tiers": "Smaller prizes",
}


def one_in(n):
    return f"1 in {n:,.0f}"


def describe(game, info):
    name = model.GAME_NAMES[game]
    if not info or not info.get("value"):
        return f"{name}: no value available (missing next-draw data or sales forecast)"
    worth, forecast = info["value"], info["forecast"]
    price = worth["price"]
    if game == model.LOTTO_649:
        prize = f"Gold Ball ${info['gold_ball_amount'] / 1e6:.0f}M with {info['balls_remaining']} balls, Classic $5M"
    else:
        prize = (f"jackpot ${info['jackpot'] / 1e6:.0f}M, {info['maxmillions_count']} MAXMILLIONS, "
                 f"{info['maxplus_count']} MAXPLUS")
    lines = [
        f"{name}, draw #{info['draw_number']} on {info['draw_date']} (${price} play): {prize}",
        f"  forecast sales {forecast['plays'] / 1e6:.2f}M plays (80% range {forecast['low'] / 1e6:.2f}M-{forecast['high'] / 1e6:.2f}M)",
        f"  value per $1: ${worth['per_dollar']:.3f} in big prizes "
        f"(${worth['per_dollar_range'][0]:.3f}-${worth['per_dollar_range'][1]:.3f}), "
        f"${worth['per_dollar_all_prizes']:.3f} with all prizes",
        "    " + ", ".join(f"{PART_NAMES[k]} ${v:.3f}" for k, v in worth["parts"].items() if v),
    ]
    odds = worth["odds_one_in"]
    per_6 = 6 / price  # plays that $6 buys
    lines.append(
        f"  odds per play: jackpot {one_in(odds['jackpot'])}, $1M or more {one_in(odds['million_plus'])}"
        + (f"; per $6: {one_in(odds['jackpot'] / per_6)} and {one_in(odds['million_plus'] / per_6)}" if per_6 != 1 else "")
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Which game is the better buy for the next draw.")
    parser.add_argument("--all-prizes", action="store_true", help="include the lower prize categories")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder with next.json")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    upcoming = store.load_json(args.data_dir / "next.json", default={})
    for game in model.GAMES:
        print(describe(game, upcoming.get(game)))
    recommendation = upcoming.get("recommendation") or {}
    verdict = recommendation.get("all_prizes" if args.all_prizes else "top_prizes")
    if not verdict:
        print("\nNo recommendation: one of the games has no value yet.")
        return 1
    if not recommendation.get("play", True):
        top = recommendation["top_prizes"]
        print(
            f"\nSkip for now: neither game reaches ${recommendation['min_per_dollar']:.2f} back per $1 in big prizes. "
            f"The better one, {model.GAME_NAMES[top['game']]}, is at ${top['per_dollar']:.3f}."
        )
        return 0
    basis = "all prizes" if args.all_prizes else "big prizes"
    print(
        f"\nPlay {model.GAME_NAMES[verdict['game']]}: ${verdict['per_dollar']:.3f} vs ${verdict['runner_up_per_dollar']:.3f} "
        f"back per $1 in {basis}, ${verdict['margin']:.3f} better"
        + (". Close call: within the sales forecasts' ranges the other game could come out ahead." if verdict["close_call"] else ".")
    )
    if upcoming.get("lotto649", {}).get("forecast", {}).get("assumes_no_super_draw"):
        print("6/49 assumes a normal draw; a Super Draw would add value and sales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
