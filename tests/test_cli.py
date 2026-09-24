import json

import forecast as forecast_cli
import recommend
import scrape
from lottocalc import store
from test_scrape import FIXTURES, LISTINGS, NOW, FakeSession


def write_data(tmp_path):
    """data/ as a run would leave it: real history through 6/49 #4452 and Lotto Max #1272."""
    draws = store.load_draws(FIXTURES / "draws_history.json")
    next_doc, _ = scrape.update(FakeSession(LISTINGS), draws, None, NOW)
    store.write_if_changed(tmp_path / "draws.json", store.dumps_draws(draws))
    store.write_if_changed(tmp_path / "next.json", store.dumps_next(next_doc))
    return next_doc


def test_recommend_prints_the_pick_and_the_breakdown(tmp_path, capsys):
    write_data(tmp_path)
    assert recommend.main(["--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Play Lotto Max: $0.3" in out
    assert "Smaller prizes $0.1" in out  # same wording as the page
    assert "odds per play: jackpot 1 in 33,446,140" in out


def test_recommend_with_all_prizes(tmp_path, capsys):
    write_data(tmp_path)
    recommend.main(["--data-dir", str(tmp_path), "--all-prizes"])
    assert "back per $1 in all prizes" in capsys.readouterr().out


def test_recommend_says_skip_below_the_minimum(tmp_path, capsys):
    next_doc = write_data(tmp_path)
    next_doc["recommendation"]["play"] = False
    (tmp_path / "next.json").write_text(json.dumps(next_doc), encoding="utf-8")
    assert recommend.main(["--data-dir", str(tmp_path)]) == 0
    assert "Skip for now: neither game reaches $0.30" in capsys.readouterr().out


def test_forecast_report(tmp_path, capsys):
    write_data(tmp_path)
    assert forecast_cli.main(["--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Lotto 6/49: backtest over 320 draws" in out
    assert "next draw #4453 on 2026-09-23" in out
    assert "Lotto Max: backtest over 31 draws" in out
