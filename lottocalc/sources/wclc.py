"""WCLC (wclc.com), the primary source.

Plain server-rendered HTML with national results. Each game's listing page
carries the next-draw sidebar for both games and the eight latest draws; the
prize breakdown of any draw sits at a stable URL keyed by its sequential number.
"""
import re
from collections import Counter
from datetime import datetime

from bs4 import BeautifulSoup

from .. import model
from . import ParseError, money, text

BASE_URL = "https://www.wclc.com"
LISTING_URLS = {
    model.LOTTO_649: f"{BASE_URL}/winning-numbers/lotto-649-extra.htm",
    model.LOTTO_MAX: f"{BASE_URL}/winning-numbers/lotto-max-extra.htm",
}
DETAILS_URLS = {
    model.LOTTO_649: BASE_URL + "/lotto-649-prize-details.htm?drawNumber={}",
    model.LOTTO_MAX: BASE_URL + "/lotto-max-prize-details.htm?drawNumber={}",
}
_DETAILS_HEADINGS = {model.LOTTO_649: "LOTTO 6/49", model.LOTTO_MAX: "LOTTO MAX"}


def parse_next(html):
    """Next-draw info for both games from the sidebar of either listing page."""
    soup = BeautifulSoup(html, "html.parser")
    gold = soup.select_one(".nextJackpotDetailsL649gold")
    lmax = soup.select_one(".nextJackpotDetailsLmax")
    if gold is None or lmax is None:
        raise ParseError("next-jackpot sidebar not found")

    balls = re.search(r"(\d+)\s*Balls?\s+Remaining", text(gold), re.IGNORECASE)
    lotto649 = {
        "draw_date": _date(gold.select_one(".nextJackpotDateDate")),
        "jackpot": model.CLASSIC_JACKPOT,
        "gold_ball_amount": _sidebar_amount(gold),
        "balls_remaining": int(balls[1]) if balls else None,
    }

    jackpot = _sidebar_amount(lmax)
    maxmillions = re.search(r"\d+", text(lmax.select_one(".nextJackpotMaxMillions")))
    if maxmillions:
        maxmillions = int(maxmillions[0])
    elif jackpot < model.MAXMILLIONS_FROM:
        maxmillions = 0
    maxplus = re.search(r"(\d+)\s*x\s*\$\s*([\d,]+)", text(lmax.select_one(".nextJackpotmaxplusDraw")))
    lottomax = {
        "draw_date": _date(lmax.select_one(".nextJackpotDateDate")),
        "jackpot": jackpot,
        "maxmillions_count": maxmillions,
        "maxplus_count": int(maxplus[1]) if maxplus else None,
        "maxplus_prize": int(maxplus[2].replace(",", "")) if maxplus else None,
    }
    return {model.LOTTO_649: lotto649, model.LOTTO_MAX: lottomax}


def parse_draw_list(html):
    """[{'draw_number', 'draw_date'}] for the draws shown on a listing page, newest first."""
    soup = BeautifulSoup(html, "html.parser")
    draws = []
    for block in soup.select("div.pastWinNum"):
        link = block.select_one(".pastWinNumPrizeBreakdown")
        rel = link.get("rel") if link else None
        rel = " ".join(rel) if isinstance(rel, list) else rel or ""
        number = re.search(r"drawNumber=(\d+)", rel)
        if not number:
            raise ParseError("draw without a prize-breakdown link")
        draws.append({"draw_number": int(number[1]), "draw_date": _date(block.select_one(".pastWinNumDate"))})
    if not draws:
        raise ParseError("no draws found on the listing page")
    return draws


def parse_prize_details(html, game, draw_number):
    """Draw record from a prize-breakdown page. Gold Ball state is filled in later."""
    soup = BeautifulSoup(html, "html.parser")
    heading = text(soup.find("h2"))
    if _DETAILS_HEADINGS[game] not in heading.upper():
        raise ParseError(f"expected a {_DETAILS_HEADINGS[game]} prize breakdown, got {heading!r}")
    numbers, bonus = _winning_numbers(soup.select_one("ul.pastWinNumbers"))
    record = {
        "game": game,
        "draw_number": draw_number,
        "draw_date": _date(soup.select_one(".pastWinNumDate h4")),
        "numbers": numbers,
        "bonus": bonus,
    }
    winners, prizes = _prize_tiers(soup, game)

    if game == model.LOTTO_649:
        ball, prize = _gold_ball(soup)
        super_prizes = _super_draw_prizes(soup)
        record.update(
            jackpot=model.CLASSIC_JACKPOT,
            gold_ball_drawn=ball,
            gold_ball_prize=prize,
            gold_ball_amount=None,
            balls_remaining=None,
            super_draw=bool(super_prizes),
            super_draw_prizes=super_prizes,
        )
    else:
        maxmillions_count, maxmillions_won, _ = _series(soup.select_one("table.prizeBreakdownLottoMaxMaximillions"))
        maxplus_count, maxplus_won, maxplus_prize = _series(soup.select_one("table.prizeBreakdownLottoMaxMaxplus"))
        record.update(
            jackpot=money(text(soup.select_one(".pastWinNumJackpot"))),
            maxmillions_count=maxmillions_count,
            maxmillions_won=maxmillions_won,
            maxplus_count=maxplus_count,
            maxplus_won=maxplus_won,
            maxplus_prize=maxplus_prize,
            super_draw=False,
        )
    record.update(tier_winners=winners, tier_prizes=prizes)
    return record


def _date(element):
    label = text(element)
    try:
        return datetime.strptime(label, "%A, %B %d, %Y").date().isoformat()
    except ValueError:
        raise ParseError(f"unrecognised draw date {label!r}") from None


def _sidebar_amount(block):
    """'$ 10 Million', laid out across several divs, -> 10_000_000."""
    amount = re.search(r"[\d.,]+", text(block.select_one(".nextJackpotPrizeAmount")))
    if not amount:
        raise ParseError("next jackpot amount not found")
    value = float(amount[0].replace(",", ""))
    if "million" in text(block.select_one(".nextJackpotAmountMillion")).lower():
        value *= 1_000_000
    return round(value)


def _winning_numbers(ul):
    if ul is None:
        raise ParseError("winning numbers not found")
    try:
        numbers = [int(text(li)) for li in ul.select("li.pastWinNumber")]
        bonus = ul.select_one("li.pastWinNumberBonus")
        return numbers, int(re.findall(r"\d+", text(bonus))[-1]) if bonus else None
    except (ValueError, IndexError):
        raise ParseError(f"unreadable winning numbers {text(ul)!r}") from None


def _winner_count(cell):
    """Sum of '4,707' or of per-region entries like '1 - Ontario', '1 - Quebec'."""
    entries = [text(li) for li in cell.select("li")] or [text(cell)]
    total = 0
    for entry in entries:
        count = re.match(r"([\d,]+)", entry)
        if not count:
            raise ParseError(f"unreadable winner count {entry!r}")
        total += int(count[1].replace(",", ""))
    return total


def _rows(table):
    """Cells of each data row (rows with <td>, not header rows)."""
    return [cells for row in table.find_all("tr") if (cells := row.find_all("td", recursive=False))]


def _prize_tiers(soup, game):
    winners, prizes = {}, {}
    for table in soup.find_all("table"):
        for cells in _rows(table):
            key = model.tier_key(text(cells[0])) if len(cells) == 3 else None
            if key not in model.TIERS[game]:
                continue
            if key in winners:
                raise ParseError(f"prize category {key} listed twice")
            winners[key] = _winner_count(cells[1])
            prizes[key] = money(text(cells[2]))  # None for FREE PLAY, NOT WON, CARRIED OVER
    order = [t for t in model.TIERS[game] if t in winners]
    return {t: winners[t] for t in order}, {t: prizes[t] for t in order}


def _table_after(soup, title):
    heading = soup.find(lambda tag: tag.name == "h3" and title in text(tag).upper())
    return heading.find_next("table") if heading else None


def _gold_ball(soup):
    ball = text(soup.select_one(".pastWinNumLogoGPD")).lower()
    if ball not in ("gold", "white"):
        raise ParseError(f"Gold Ball Draw result {ball!r}")
    table = _table_after(soup, "GOLD BALL DRAW")
    rows = _rows(table) if table else []
    if len(rows) != 1:
        raise ParseError(f"expected one Gold Ball Draw winner row, found {len(rows)}")
    return ball, money(text(rows[0][-1]))


def _super_draw_prizes(soup):
    """[{'prize', 'count'}] of a Super Draw's additional prizes; [] on a normal draw."""
    table = _table_after(soup, "SUPER DRAW")
    if table is None:
        return []
    amounts = [money(text(cells[-1])) for cells in _rows(table)]
    if not amounts or None in amounts:
        raise ParseError("unreadable Super Draw prize table")
    return [{"prize": p, "count": c} for p, c in sorted(Counter(amounts).items(), reverse=True)]


def _series(table):
    """(prizes offered, prizes won, full prize) for a MAXPLUS or MAXMILLIONS table."""
    if table is None:
        return 0, 0, None
    rows = _rows(table)
    won = sum(1 for cells in rows if _winner_count(cells[1]))
    prizes = [p for cells in rows if (p := money(text(cells[-1])))]
    return len(rows), won, max(prizes) if prizes else None
