import json
from datetime import datetime, timezone
from pathlib import Path

import scrape
from lottocalc import model, store
from lottocalc.http import FetchError
from lottocalc.sources import lotterycanada, wclc

FIXTURES = Path(__file__).parent / "fixtures"
LISTINGS = {
    wclc.LISTING_URLS[model.LOTTO_649]: "wclc_649_listing.html",
    wclc.LISTING_URLS[model.LOTTO_MAX]: "wclc_max_listing.html",
}
DETAILS = {
    **{wclc.DETAILS_URLS[model.LOTTO_649].format(n): f"wclc_649_{n}.html" for n in range(4446, 4453)},
    **{wclc.DETAILS_URLS[model.LOTTO_MAX].format(n): f"wclc_max_{n}.html" for n in (1270, 1271, 1272)},
}
BACKUP = {
    lotterycanada.NEXT_URLS[model.LOTTO_649]: "lc_649.html",
    lotterycanada.NEXT_URLS[model.LOTTO_MAX]: "lc_max.html",
}
NOW = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)  # 8 PM Eastern, before Wednesday's 6/49 draw
STAMP = "2026-09-24T00:00:00Z"


class FakeSession:
    """Serves saved pages by URL; any other URL fails like a missing page."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    @property
    def requests_made(self):
        return len(self.requested)

    def get(self, url):
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError(f"{url}: HTTP 404")
        return (FIXTURES / self.pages[url]).read_text(encoding="utf-8")


def stored(game, number):
    prefix = "wclc_649" if game == model.LOTTO_649 else "wclc_max"
    html = (FIXTURES / f"{prefix}_{number}.html").read_text(encoding="utf-8")
    return dict(wclc.parse_prize_details(html, game, number), source="wclc", scraped_at="2026-09-20T12:00:00Z")


def numbers(draws, game):
    return sorted(d["draw_number"] for d in draws if d["game"] == game)


def test_first_run_stores_the_latest_draws_and_the_next_draw():
    session = FakeSession(LISTINGS | DETAILS)
    draws = []
    next_doc, report = scrape.update(session, draws, None, NOW, first_run_draws=3)

    assert (report.errors, report.warnings) == ([], [])
    assert numbers(draws, model.LOTTO_649) == [4450, 4451, 4452]
    assert numbers(draws, model.LOTTO_MAX) == [1270, 1271, 1272]
    assert session.requests_made == 2 + 6  # two listing pages, then one breakdown per draw
    assert all(d["source"] == "wclc" and d["scraped_at"] == STAMP for d in draws)

    gold = {d["draw_number"]: (d["gold_ball_amount"], d["balls_remaining"]) for d in draws if d["game"] == model.LOTTO_649}
    assert gold == {4450: (28_000_000, 21), 4451: (30_000_000, 20), 4452: (32_000_000, 19)}

    assert next_doc["scraped_at"] == STAMP
    assert next_doc[model.LOTTO_649] == {
        "draw_number": 4453,
        "draw_date": "2026-09-23",
        "jackpot": 5_000_000,
        "gold_ball_amount": 10_000_000,
        "balls_remaining": 30,
        "source": "wclc",
        "as_of": STAMP,
    }
    assert next_doc[model.LOTTO_MAX] == {
        "draw_number": 1273,
        "draw_date": "2026-09-25",
        "jackpot": 60_000_000,
        "maxmillions_count": 6,
        "maxplus_count": 60,
        "maxplus_prize": 100_000,
        "source": "wclc",
        "as_of": STAMP,
    }
    assert (next_doc["errors"], next_doc["warnings"]) == ([], [])


def test_later_run_fetches_only_missing_draws_and_fills_gaps():
    session = FakeSession(LISTINGS | DETAILS)
    draws = [stored(model.LOTTO_649, 4446), stored(model.LOTTO_649, 4452), stored(model.LOTTO_MAX, 1272)]
    _, report = scrape.update(session, draws, None, NOW)

    assert report.errors == []
    assert [n for _, n, _ in report.added] == [4447, 4448, 4449, 4450, 4451]
    assert session.requests_made == 2 + 5
    super_draw = next(d for d in draws if d["draw_number"] == 4446)
    assert (super_draw["gold_ball_amount"], super_draw["balls_remaining"]) == (20_000_000, 25)


def test_nothing_new_costs_two_requests():
    session = FakeSession(LISTINGS)
    draws = [stored(model.LOTTO_649, 4452), stored(model.LOTTO_MAX, 1272)]
    _, report = scrape.update(session, draws, None, NOW)
    assert session.requests_made == 2
    assert (report.added, report.errors) == ([], [])


def test_wclc_outage_takes_the_next_draw_from_the_backup():
    draws = [stored(model.LOTTO_649, 4452), stored(model.LOTTO_MAX, 1272)]
    next_doc, report = scrape.update(FakeSession(BACKUP), draws, None, NOW)

    assert next_doc[model.LOTTO_649]["source"] == "lotterycanada"
    assert next_doc[model.LOTTO_649]["draw_number"] == 4453
    assert next_doc[model.LOTTO_649]["gold_ball_amount"] == 10_000_000
    assert next_doc[model.LOTTO_MAX]["jackpot"] == 60_000_000
    assert len(report.errors) == 2  # no new draws without WCLC's results pages
    assert any("backup" in w for w in report.warnings)
    assert next_doc["errors"] == report.errors


def test_total_outage_keeps_the_previous_next_draw_marked_stale():
    previous = {
        model.LOTTO_649: {"draw_number": 4453, "draw_date": "2026-09-23", "as_of": "2026-09-23T12:00:00Z"},
        model.LOTTO_MAX: None,
    }
    next_doc, report = scrape.update(FakeSession({}), [], previous, NOW)
    assert next_doc[model.LOTTO_649]["stale"] is True
    assert next_doc[model.LOTTO_649]["as_of"] == "2026-09-23T12:00:00Z"
    assert next_doc[model.LOTTO_MAX] is None
    assert report.errors


def test_unreadable_draw_is_reported_and_not_stored():
    pages = LISTINGS | {wclc.DETAILS_URLS[model.LOTTO_649].format(4452): "wclc_max_1272.html"}
    draws = [stored(model.LOTTO_649, 4451), stored(model.LOTTO_MAX, 1272)]
    next_doc, report = scrape.update(FakeSession(pages), draws, None, NOW)

    assert numbers(draws, model.LOTTO_649) == [4451]
    assert any("draw 4452" in e for e in report.errors)
    assert next_doc[model.LOTTO_649]["draw_number"] == 4453
    assert any("2026-09-19 not stored yet" in w for w in report.warnings)


def test_main_updates_both_files_for_the_latest_draw(tmp_path, monkeypatch):
    draws_path, next_path = tmp_path / "draws.json", tmp_path / "next.json"
    store.write_if_changed(draws_path, store.dumps_draws([stored(model.LOTTO_649, 4451), stored(model.LOTTO_MAX, 1271)]))
    monkeypatch.setattr(scrape, "PoliteSession", lambda: FakeSession(LISTINGS | DETAILS))

    assert scrape.main(["--data-dir", str(tmp_path)]) == 0
    draws = store.load_draws(draws_path)
    assert [(d["game"], d["draw_number"]) for d in draws] == [
        (model.LOTTO_649, 4451), (model.LOTTO_649, 4452), (model.LOTTO_MAX, 1271), (model.LOTTO_MAX, 1272),
    ]
    next_doc = json.loads(next_path.read_text(encoding="utf-8"))
    assert (next_doc[model.LOTTO_649]["draw_number"], next_doc[model.LOTTO_MAX]["draw_number"]) == (4453, 1273)
    assert next_doc["errors"] == []

    before = draws_path.read_bytes()
    assert scrape.main(["--data-dir", str(tmp_path)]) == 0
    assert draws_path.read_bytes() == before


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "PoliteSession", lambda: FakeSession(LISTINGS | DETAILS))
    scrape.main(["--data-dir", str(tmp_path), "--dry-run"])
    assert list(tmp_path.iterdir()) == []
