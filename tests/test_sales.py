import pytest

from lottocalc import model, sales
from lottocalc.sources import wclc


def draw(page, game, number):
    prefix = "wclc_649" if game == model.LOTTO_649 else "wclc_max"
    return wclc.parse_prize_details(page(f"{prefix}_{number}.html"), game, number)


# "1 in N" per play, as printed in OLG's odds tables.
@pytest.mark.parametrize(
    "game, tier, one_in",
    [
        (model.LOTTO_649, "6/6", 13_983_816),
        (model.LOTTO_649, "5/6+B", 2_330_636),
        (model.LOTTO_649, "5/6", 55_492),
        (model.LOTTO_649, "4/6", 1_033),
        (model.LOTTO_649, "3/6", 56.7),
        (model.LOTTO_649, "2/6+B", 81.2),
        (model.LOTTO_649, "2/6", 8.3),
        (model.LOTTO_MAX, "7/7", 33_446_140),
        (model.LOTTO_MAX, "6/7+B", 4_778_020),
        (model.LOTTO_MAX, "6/7", 108_591),
        (model.LOTTO_MAX, "5/7+B", 36_197),
        (model.LOTTO_MAX, "5/7", 1_684),
        (model.LOTTO_MAX, "4/7+B", 1_010),
        (model.LOTTO_MAX, "4/7", 72.2),
        (model.LOTTO_MAX, "3/7+B", 72.2),
        (model.LOTTO_MAX, "3/7", 7.0),
    ],
)
def test_tier_odds_match_olgs_tables(game, tier, one_in):
    per_play = sales.tier_probability(game, tier) * sales.LINES_PER_PLAY[game]
    assert 1 / per_play == pytest.approx(one_in, rel=0.006)


@pytest.mark.parametrize(
    "game, number, plays",
    [
        (model.LOTTO_649, 4452, 4_382_708),
        (model.LOTTO_649, 4033, 3_510_848),  # 5/6+B not won: Pools Fund from the other two shares
        (model.LOTTO_MAX, 1272, 4_496_096),
        (model.LOTTO_MAX, 1271, 4_663_666),
        (model.LOTTO_MAX, 1270, 3_668_063),  # 6/7+B not won
    ],
)
def test_plays_from_prizes(page, game, number, plays):
    assert sales.plays_from_prizes(draw(page, game, number)) == pytest.approx(plays, abs=1_000)


def test_sales_match_lottery_canadas_published_figure(page):
    # lotterycanada.com lists "$13,149,300 ticket sales" for the 2026-09-19 draw.
    plays = sales.plays_from_prizes(draw(page, model.LOTTO_649, 4452))
    assert plays * sales.PRICE[model.LOTTO_649] == pytest.approx(13_149_300, rel=0.0005)


def test_odds_cross_check_is_close_but_noisy(page):
    record = draw(page, model.LOTTO_MAX, 1272)
    assert sales.plays_from_odds(record) / sales.plays_from_prizes(record) == pytest.approx(1, abs=0.03)


def test_annotate_sets_estimates_without_warnings(page):
    records = [draw(page, model.LOTTO_649, n) for n in (4446, 4452)]
    assert sales.annotate(records) == []
    assert records[1]["est_plays"] == sales.plays_from_prizes(records[1])
    assert records[1]["est_plays_check"] == sales.plays_from_odds(records[1])


def test_annotate_flags_inconsistent_shared_prizes(page):
    record = draw(page, model.LOTTO_649, 4452)
    record["tier_prizes"] = dict(record["tier_prizes"], **{"5/6": 800.0})  # was $731.80
    warnings = sales.annotate([record])
    assert len(warnings) == 1 and "Pools Funds" in warnings[0]


def test_annotate_without_any_shared_winner(page):
    record = draw(page, model.LOTTO_649, 4452)
    record["tier_winners"] = dict(record["tier_winners"], **{"5/6+B": 0, "5/6": 0, "4/6": 0})
    warnings = sales.annotate([record])
    assert record["est_plays"] is None and "unknown" in warnings[0]
