import json

from lottocalc import store


def draw(game, number, **fields):
    return {"game": game, "draw_number": number, "draw_date": "2026-09-19", **fields}


def test_draws_file_has_one_draw_per_line_in_game_order(tmp_path):
    draws = [draw("lottomax", 1272), draw("lotto649", 4452), draw("lotto649", 4451)]
    content = store.dumps_draws(draws)
    lines = content.splitlines()
    assert lines[0] == '{"schema_version":1,"draws":['
    assert [json.loads(line.rstrip(","))["draw_number"] for line in lines[1:-1]] == [4451, 4452, 1272]

    path = tmp_path / "draws.json"
    store.write_if_changed(path, content)
    assert store.load_draws(path) == [draws[2], draws[1], draws[0]]


def test_empty_history_round_trips(tmp_path):
    path = tmp_path / "draws.json"
    assert store.load_draws(path) == []
    store.write_if_changed(path, store.dumps_draws([]))
    assert store.load_draws(path) == []


def test_merge_ignores_a_new_scrape_time_but_takes_real_changes():
    draws = [draw("lotto649", 1, x=1, scraped_at="first")]
    assert store.merge_draw(draws, draw("lotto649", 1, x=1, scraped_at="second")) is False
    assert draws[0]["scraped_at"] == "first"
    assert store.merge_draw(draws, draw("lotto649", 1, x=2, scraped_at="third")) is True
    assert draws == [draw("lotto649", 1, x=2, scraped_at="third")]
    assert store.merge_draw(draws, draw("lotto649", 2)) is True and len(draws) == 2


def test_write_if_changed(tmp_path):
    path = tmp_path / "data" / "next.json"
    assert store.write_if_changed(path, "{}\n") is True
    assert store.write_if_changed(path, "{}\n") is False
    assert path.read_bytes() == b"{}\n"
    assert not path.with_name("next.json.tmp").exists()
