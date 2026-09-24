# Lotto Calculator

Which Ontario lottery is the better buy for the next draw, **Lotto 6/49** or **Lotto Max**,
based on real jackpots, real sales and real odds.

**Live page: https://soyssauccee.github.io/lotto-calculator/** (on an iPhone, Share → Add to Home
Screen makes it an app).

## Status

| Milestone | What | State |
|---|---|---|
| M0 | Data source audit | done |
| M1 | Scraper and data model | done |
| M2 | Backfill history (6/49 from #4033, Lotto Max 7/52 from #1226) | done |
| M3 | Sales estimator (exact, from the Pools Fund) | done |
| M4 | Sales forecast model | done |
| M5 | Value engine | done |
| M6 | Phone web page | done |
| M7 | Scheduled runs and alerts | next |

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
.venv\Scripts\python forecast.py           # backtest the sales forecasts, show next-draw forecasts
.venv\Scripts\python recommend.py          # which game to play next, with the full breakdown
.venv\Scripts\python recommend.py --all-prizes   # same, counting the lower prize categories too
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
| `forecast` | predicted `plays` with an 80% range (`low`–`high`), and the model's backtest error |
| `value` | expected payout per $1 in big prizes (`per_dollar`, with a range from the sales forecast), with all prizes (`per_dollar_all_prizes`), the parts, and the odds per play |
| `source`, `as_of` | where and when it was read; `stale: true` if every source failed |

Top-level `recommendation` names the better buy on big prizes (`top_prizes`) and on all prizes
(`all_prizes`), with the `margin` per $1 and `close_call: true` when the runner-up could come out
ahead within the forecast ranges. Top-level `errors` and `warnings` list what went wrong in the last run.

**`data/draws.json`**: every stored draw, one per line, sorted by game and draw number.
Records hold the winning numbers, `tier_winners` and `tier_prizes` per prize category
(national counts; `null` prize = free play or not won), plus:

- 6/49: `gold_ball_drawn` (`gold`/`white`), `gold_ball_prize`, the derived `gold_ball_amount` and
  `balls_remaining` at that draw, and `super_draw` / `super_draw_prizes`.
- Lotto Max: `jackpot`, `maxmillions_count`/`_won`, `maxplus_count`/`_won`, `maxplus_prize`.
- Both: `est_plays`, the plays sold (a $3 6/49 play or a $6 four-line Lotto Max play), and
  `est_plays_check`, a rough cross-check from winners ÷ odds; `value_per_dollar`, what a
  ticket for that draw was worth in big prizes, given the plays actually sold.

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

## Sales forecast

`lottocalc/forecast.py` predicts plays for the next draw. For each game, log(plays) is
fitted on what is known before the draw:

- 6/49: the Gold Ball jackpot and its square, 1/balls, whether the jackpot is guaranteed
  (1 ball left), Saturday, Super Draw prize money, the Dec 15–Jan 1 holidays, a slow trend
  (about −4.5% a year), and a launch dummy for the format's first week.
- Lotto Max: the jackpot and its square, and Friday.

The fit is then nudged by 0.7 × the average miss on the last 4 draws, because sales drift
in runs.

Walk-forward backtest, where each draw is predicted only from the draws before it:

| | Draws | Avg error | Median | Within ±15% | 80% range held |
|---|---|---|---|---|---|
| Lotto 6/49 | 321 | 2.8% | 2.1% | 98.8% | 82% |
| Lotto Max | 31 | 2.2% | 1.7% | 100% | 91% |

6/49 errors are larger on special draws (5.0% with ≤5 balls, a Super Draw or the holidays,
vs 2.3% otherwise), so those draws get their own, wider range. Upcoming Super Draws are not
announced anywhere this project can read, so forecasts assume a normal draw.

## Value

`lottocalc/value.py` values a ticket as its expected payout per $1: each prize times its odds,
times the share you keep if others win it too.

- **Lotto Max** ($6, 4 lines). A play matches the main jackpot or any MAXPLUS or MAXMILLIONS
  series with p = 1 in 33,446,140. Other winning lines are Poisson with mean λ = N·p (N = forecast
  plays), so the expected share is s = (1 − e^−λ)/λ.
  Value = s × (jackpot + MAXPLUS prizes + MAXMILLIONS prizes) × p ÷ $6.
- **Lotto 6/49** ($3). One play's number out of N wins the Gold Ball Draw: the jackpot with
  probability 1/balls, otherwise $1M, never shared. The Classic $5M is shared like above.
  Value = [(J/balls + $1M × (1 − 1/balls)) ÷ N + s × $5M ÷ C(49,6)] ÷ $3.
  Example: $40M with 15 balls and 4.5M plays gives $0.369.
- **Lower categories** (the `--all-prizes` toggle) add about $0.18 (6/49) and $0.20 (Lotto Max)
  per $1: fixed prizes at their odds, free plays at the game conditions' deemed value, and each
  pool's expected share.

Checked against history: the model expects 27.1 Gold Ball jackpots, 124 Classic wins and 151
MAXPLUS wins, and history shows 24, 126 and 165. All three are within 1.2 standard deviations.

Rule of thumb from the stored draws (median value per $1 in big prizes):

| 6/49 balls left | 30–26 | 25–21 | 20–16 | 15–11 | 10–6 | 5–3 | 2–1 |
|---|---|---|---|---|---|---|---|
| 6/49 | $0.22 | $0.25 | $0.30 | $0.36 | $0.51 | $0.79 | $1.62 |

| Lotto Max jackpot | $10M | $20M | $30M | $40M | $50M | $55M | $60M | $65M | $70M |
|---|---|---|---|---|---|---|---|---|---|
| Lotto Max | $0.05 | $0.10 | $0.16 | $0.21 | $0.27 | $0.30 | $0.33 | $0.37 | $0.39 |

## Web page

`index.html` and `web/` make up a single static page with no build step. It reads
`data/next.json` and `data/draws.json` and shows:

- the verdict and the value gap, with a Big prizes / All prizes toggle
- a card per game: prizes, value per $1 with its range and parts, odds for $6, and the sales
  forecast
- a chart of value per $1 over recent draws (tap a point for details)
- when the data was last updated, with warnings for failed or stale updates

`.github/workflows/pages.yml` publishes `index.html`, `web/` and `data/` to GitHub Pages. To
preview locally, run `.venv\Scripts\python -m http.server 8000` and open http://localhost:8000.

## Sources

| Source | Used for | Notes |
|---|---|---|
| [WCLC](https://www.wclc.com) | everything | Server-rendered HTML with national results. Draw breakdowns are keyed by sequential draw number. |
| [Lottery Canada](https://www.lotterycanada.com) | next-draw info, only if WCLC fails | Prizes rounded to whole dollars, so never used for history. |

OLG's own site loads its data from a private keyed API, and BCLC/ALC render client-side, so
none of them is scraped.

Etiquette: an identifiable User-Agent, at least 1.5 s between requests to a host, retries
only on timeouts/429/5xx. A normal run makes 2 requests, plus 1 per new draw.
