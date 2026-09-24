# Lotto Calculator

Which Ontario lottery is the better buy for the next draw, **Lotto 6/49** or **Lotto Max**,
based on real jackpots, real sales and real odds.

## Status

| Milestone | What | State |
|---|---|---|
| M0 | Data source audit | done |
| M1 | Scraper and data model | done |
| M2 | Backfill history (6/49 from #4033, Lotto Max 7/52 from #1226) | done |
| M3 | Sales estimator (exact, from the Pools Fund) | done |
| M4 | Sales forecast model | next |
| M5 | Value engine | |
| M6 | Phone web page | |
| M7 | Scheduled runs and alerts | |

## Setup

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## Usage

```
.venv\Scripts\python scrape.py             # fetch next-draw info and any new draws
.venv\Scripts\python scrape.py --backfill  # also fetch every draw of the current formats (~15 min)
.venv\Scripts\python scrape.py --dry-run   # fetch and report, write nothing
.venv\Scripts\python -m pytest             # offline tests against saved pages
```

`scrape.py` exits with status 1 if anything could not be fetched or parsed. The data files
then keep their last good values and `next.json` lists the errors.

## Data

**`data/next.json`**: the upcoming draw for each game.

| Field | Meaning |
|---|---|
| `draw_number`, `draw_date` | the draw being sold now |
| `jackpot` | 6/49: the fixed $5M Classic jackpot; Lotto Max: the main jackpot |
| `gold_ball_amount`, `balls_remaining` | 6/49 Gold Ball jackpot and balls in the drum (odds of gold = 1/balls) |
| `maxmillions_count`, `maxplus_count`, `maxplus_prize` | Lotto Max extra prizes |
| `source`, `as_of` | where and when it was read; `stale: true` if every source failed |

Top-level `errors` and `warnings` list what went wrong in the last run.

**`data/draws.json`**: every stored draw, one per line, sorted by game and draw number.
Records hold the winning numbers, `tier_winners` and `tier_prizes` per prize category
(national counts; `null` prize = free play or not won), plus:

- 6/49: `gold_ball_drawn` (`gold`/`white`), `gold_ball_prize`, the derived `gold_ball_amount` and
  `balls_remaining` at that draw, and `super_draw` / `super_draw_prizes`.
- Lotto Max: `jackpot`, `maxmillions_count`/`_won`, `maxplus_count`/`_won`, `maxplus_prize`.
- Both: `est_plays`, the plays sold (a $3 6/49 play or a $6 four-line Lotto Max play), and
  `est_plays_check`, a rough cross-check from winners ÷ odds.

`est_plays` is recovered exactly from the prizes (`lottocalc/sales.py`). The game conditions
send a fixed amount per play to a Prize Fund ($0.55 for 6/49, $1.19 for Lotto Max). The fixed
prizes are paid from it, with free plays counted at $1.44 and $2.88, and the rest is shared
between the pooled categories by fixed percentages. So each pooled prize reveals the Pools
Fund, and plays = (Pools Fund + fixed prizes paid) ÷ Prize Fund per play. It matches Lottery
Canada's published sales to 0.01%. The winners ÷ odds cross-check swings ±15% on 6/49 because
players favour certain numbers, so it only raises a warning when it is far off.

Past 6/49 draws don't show their Gold Ball jackpot. It is derived: each gold-ball win's prize
anchors a chain, each white ball adds $2M, and a gold ball resets to $10M with 30 balls. Any
disagreement shows up as a warning.

## Sources

| Source | Used for | Notes |
|---|---|---|
| [WCLC](https://www.wclc.com) | everything | Server-rendered HTML with national results. Draw breakdowns are keyed by sequential draw number. |
| [Lottery Canada](https://www.lotterycanada.com) | next-draw info, only if WCLC fails | Prizes rounded to whole dollars, so never used for history. |

OLG's own site loads its data from a private keyed API, and BCLC/ALC render client-side, so
none of them is scraped.

Etiquette: an identifiable User-Agent, at least 1.5 s between requests to a host, retries
only on timeouts/429/5xx. A normal run makes 2 requests, plus 1 per new draw.
