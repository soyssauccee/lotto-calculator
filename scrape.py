"""Refresh data/next.json and data/draws.json from the lottery sites.

    python scrape.py             fetch next-draw info and any draws not stored yet
    python scrape.py --dry-run   fetch and report, but write nothing

Exits with status 1 when data could not be fetched or parsed. The files then
keep the last good data and next.json lists the errors, so a scheduled run can
raise an alert and the page can show that its numbers are stale.
"""
import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from lottocalc import model, store
from lottocalc.http import FetchError, PoliteSession
from lottocalc.sources import ParseError, lotterycanada, wclc

DATA_DIR = Path(__file__).resolve().parent / "data"
EASTERN = ZoneInfo("America/Toronto")
FIRST_RUN_DRAWS = 8  # with no history stored yet, take the draws on the listing page
MAX_CATCH_UP = 30  # a longer gap is a job for the backfill


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    added: list = field(default_factory=list)  # (game, draw_number, draw_date)


def update(session, draws, previous_next, now, first_run_draws=FIRST_RUN_DRAWS):
    """Fetch new data and merge it into draws, in place. Returns (next_doc, report)."""
    report = Report()
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    listings, upcoming, sidebar_problem = {}, {}, None
    for game in model.GAMES:
        name = model.GAME_NAMES[game]
        try:
            html = session.get(wclc.LISTING_URLS[game])
        except FetchError as exc:
            report.errors.append(f"{name}: WCLC results page unavailable, no new draws ({exc})")
            continue
        try:
            listings[game] = wclc.parse_draw_list(html)
        except ParseError as exc:
            report.errors.append(f"{name}: WCLC results page unreadable, no new draws ({exc})")
        if not upcoming:
            try:
                upcoming = {g: dict(info, source="wclc") for g, info in wclc.parse_next(html).items()}
            except ParseError as exc:
                sidebar_problem = f"WCLC next-draw sidebar unreadable ({exc})"

    for game in model.GAMES:
        if game in upcoming:
            continue
        name = model.GAME_NAMES[game]
        try:
            info = lotterycanada.parse_next(session.get(lotterycanada.NEXT_URLS[game]), game)
        except (FetchError, ParseError) as exc:
            report.errors.append(f"{name}: next draw unavailable from WCLC and Lottery Canada ({exc})")
            continue
        upcoming[game] = dict(info, source="lotterycanada")
        report.warnings.append(f"{name}: next draw taken from the backup source, Lottery Canada")
    if sidebar_problem:
        report.warnings.append(sidebar_problem)

    for game, listing in listings.items():
        _catch_up(session, game, listing, draws, stamp, report, first_run_draws)

    next_doc = {"scraped_at": stamp}
    today = now.astimezone(EASTERN).date()
    for game in model.GAMES:
        records = sorted((d for d in draws if d["game"] == game), key=lambda d: d["draw_number"])
        info = upcoming.get(game)
        if info is None:
            previous = (previous_next or {}).get(game)
            next_doc[game] = dict(previous, stale=True) if previous else None
            if game == model.LOTTO_649:
                report.warnings += model.derive_gold_ball(records)
            continue
        info = {"draw_number": _next_draw_number(game, info, records, report), **info}
        if date.fromisoformat(info["draw_date"]) < today:
            report.warnings.append(
                f"{model.GAME_NAMES[game]}: the {info['draw_date']} draw has passed "
                "but the source hasn't moved on to the next one yet"
            )
        errors, warnings = model.check_next(game, info)
        report.errors += errors
        report.warnings += warnings
        if game == model.LOTTO_649:
            report.warnings += model.derive_gold_ball(records, info)
        next_doc[game] = dict(info, as_of=stamp)
    next_doc["errors"] = report.errors
    next_doc["warnings"] = report.warnings
    return next_doc, report


def _catch_up(session, game, listing, draws, stamp, report, first_run_draws):
    """Fetch every draw up to the newest listed one that isn't stored, filling gaps too."""
    name = model.GAME_NAMES[game]
    have = {d["draw_number"] for d in draws if d["game"] == game}
    latest = max(item["draw_number"] for item in listing)
    if have:
        wanted = [n for n in range(min(have), latest + 1) if n not in have]
    else:
        wanted = sorted(item["draw_number"] for item in listing)[-first_run_draws:]
    if len(wanted) > MAX_CATCH_UP:
        report.warnings.append(
            f"{name}: {len(wanted)} draws missing; fetching the newest {MAX_CATCH_UP}, backfill the rest"
        )
        wanted = wanted[-MAX_CATCH_UP:]
    for number in wanted:
        try:
            html = session.get(wclc.DETAILS_URLS[game].format(number))
            record = wclc.parse_prize_details(html, game, number)
        except (FetchError, ParseError) as exc:
            report.errors.append(f"{name} draw {number}: {exc}")
            continue
        problems = model.check_draw(record)
        if problems:
            report.errors.append(f"{name} draw {number} rejected: {'; '.join(problems)}")
            continue
        record.update(source="wclc", scraped_at=stamp)
        store.merge_draw(draws, record)
        report.added.append((game, number, record["draw_date"]))


def _next_draw_number(game, info, records, report):
    """Number of the advertised draw, counting scheduled draws since the newest stored one."""
    if not records:
        return None
    name, last = model.GAME_NAMES[game], records[-1]
    pending = model.draws_between(game, date.fromisoformat(last["draw_date"]), date.fromisoformat(info["draw_date"]))
    if not pending:
        report.warnings.append(f"{name}: next draw listed as {info['draw_date']}, which already has results")
        return None
    if len(pending) > 1:
        missing = ", ".join(d.isoformat() for d in pending[:-1])
        report.warnings.append(f"{name}: results for {missing} not stored yet")
    return last["draw_number"] + len(pending)


def summarize(next_doc, report, requests_made):
    def dollars(value):
        return f"${value:,}" if isinstance(value, (int, float)) else "?"

    def origin(info):
        return f"[{info.get('source')}{', STALE' if info.get('stale') else ''}]"

    lines = []
    info = next_doc.get(model.LOTTO_649)
    if info:
        lines.append(
            f"Lotto 6/49  next {info['draw_date']} (#{info['draw_number']}): Gold Ball "
            f"{dollars(info['gold_ball_amount'])} with {info['balls_remaining']} balls  {origin(info)}"
        )
    info = next_doc.get(model.LOTTO_MAX)
    if info:
        lines.append(
            f"Lotto Max   next {info['draw_date']} (#{info['draw_number']}): jackpot {dollars(info['jackpot'])}, "
            f"{info['maxmillions_count']} MAXMILLIONS, {info['maxplus_count']} MAXPLUS  {origin(info)}"
        )
    for game in model.GAMES:
        added = sorted(n for g, n, _ in report.added if g == game)
        if added:
            lines.append(f"{model.GAME_NAMES[game]}: added {len(added)} draw(s), #{added[0]}-#{added[-1]}")
    if not report.added:
        lines.append("No new draws.")
    lines += [f"WARNING: {w}" for w in report.warnings]
    lines += [f"ERROR: {e}" for e in report.errors]
    lines.append(f"{requests_made} request(s) made.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh next.json and draws.json from the lottery sites.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder with draws.json and next.json")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, but write nothing")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    draws_path, next_path = args.data_dir / "draws.json", args.data_dir / "next.json"
    draws = store.load_draws(draws_path)
    session = PoliteSession()
    next_doc, report = update(session, draws, store.load_json(next_path), datetime.now(timezone.utc))
    print(summarize(next_doc, report, session.requests_made))
    if not args.dry_run:
        store.write_if_changed(draws_path, store.dumps_draws(draws))
        store.write_if_changed(next_path, store.dumps_next(next_doc))
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
