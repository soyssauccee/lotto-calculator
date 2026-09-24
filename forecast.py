"""Backtest the sales forecasts and show the forecast for each game's next draw.

    python forecast.py

Every stored draw after the first few is predicted from earlier draws only,
so the errors shown are what the forecast would really have achieved.
"""
import argparse
import sys
from pathlib import Path

from lottocalc import forecast, model, store

DATA_DIR = Path(__file__).resolve().parent / "data"


def report(game, draws, upcoming):
    name = model.GAME_NAMES[game]
    predictions = forecast.backtest(game, draws)
    if len(predictions) < forecast.MIN_REGIME_ERRORS:
        return f"{name}: not enough history to backtest ({len(predictions)} predictions)"
    stats = forecast.accuracy(predictions)
    worst = stats["worst"]
    lines = [
        f"{name}: backtest over {stats['draws']} draws, each predicted from earlier draws only",
        f"  average error {stats['mape']:.1%}, median {stats['median_ape']:.1%}, "
        f"90% of draws within {stats['p90_ape']:.1%}, bias {stats['bias']:+.1%}",
        f"  within +/-15%: {stats['within_15pct']:.1%} of draws; "
        f"worst {worst['ape']:.1%} (#{worst['draw_number']}, {worst['draw_date']})",
        f"  80% ranges built from earlier errors held {stats['range_coverage']:.0%} of the time",
    ]
    if stats["mape_special"] is not None:
        lines.append(
            f"  ordinary draws {stats['mape_ordinary']:.1%}; special draws "
            f"(<=5 balls, Super Draw or holidays) {stats['mape_special']:.1%}"
        )
    if upcoming and upcoming.get("draw_number"):
        result = forecast.forecast_next(game, draws, upcoming)
        if result:
            lines.append(
                f"  next draw #{upcoming['draw_number']} on {upcoming['draw_date']}: "
                f"{result['plays'] / 1e6:.2f}M plays (80% range {result['low'] / 1e6:.2f}M-{result['high'] / 1e6:.2f}M)"
                + (", assuming no Super Draw" if result["assumes_no_super_draw"] else "")
            )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backtest the sales forecasts.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder with draws.json and next.json")
    args = parser.parse_args(argv)
    draws = store.load_draws(args.data_dir / "draws.json")
    upcoming = store.load_json(args.data_dir / "next.json", default={})
    for game in model.GAMES:
        records = [d for d in draws if d["game"] == game]
        print(report(game, records, upcoming.get(game)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
