"""Lottery Canada (lotterycanada.com), the backup source for next-draw info only.

Used only when WCLC fails, and never polled: its robots.txt calls out a bot
that did. Its prize amounts are rounded to whole dollars, so draw history always
comes from WCLC, which keeps every draw by number for a later run to fill a gap.
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .. import model
from . import ParseError, money, text

BASE_URL = "https://www.lotterycanada.com"
NEXT_URLS = {
    model.LOTTO_649: f"{BASE_URL}/lotto-649",
    model.LOTTO_MAX: f"{BASE_URL}/lotto-max",
}


def parse_next(html, game):
    """Next-draw info for one game, in the same shape as wclc.parse_next."""
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("section.lx-next[data-draw-at]")
    if section is None:
        raise ParseError("next-draw section not found")
    try:
        draw_date = datetime.fromisoformat(section["data-draw-at"]).date().isoformat()
    except ValueError:
        raise ParseError(f"unrecognised draw time {section['data-draw-at']!r}") from None
    items = {
        text(item.select_one(".lx-next__jackpot-label")).lower(): text(item.select_one(".lx-next__jackpot"))
        for item in section.select(".lx-next__jackpot-item")
    }

    def amount(label):
        value = next((money(v) for k, v in items.items() if label in k), None)
        if value is None:
            raise ParseError(f"no {label!r} amount in the next-draw section")
        return value

    if game == model.LOTTO_649:
        gold = amount("gold ball")
        return {
            "draw_date": draw_date,
            "jackpot": amount("classic"),
            "gold_ball_amount": gold,
            "balls_remaining": model.balls_for_jackpot(gold),
        }

    jackpot = amount("jackpot")
    maxplus = re.search(r"(\d+)\s*[×x]\s*\$\s*([\d,]+)", next((v for k, v in items.items() if "maxplus" in k), ""))
    return {
        "draw_date": draw_date,
        "jackpot": jackpot,
        "maxmillions_count": 0 if jackpot < model.MAXMILLIONS_FROM else None,  # count isn't shown
        "maxplus_count": int(maxplus[1]) if maxplus else None,
        "maxplus_prize": int(maxplus[2].replace(",", "")) if maxplus else None,
    }
