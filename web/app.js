"use strict";

// Reads data/next.json and data/draws.json, written by scrape.py, and renders the page.

const GAMES = {
  lottomax: { name: "Lotto Max", css: "max" },
  lotto649: { name: "Lotto 6/49", css: "g649" },
};
const PARTS = {
  jackpot: "Jackpot",
  maxplus: "MAXPLUS",
  maxmillions: "MAXMILLIONS",
  gold_ball: "Gold Ball draw",
  classic_jackpot: "Classic $5M",
  super_draw: "Super Draw",
  lower_tiers: "Smaller prizes",
};
const STALE_HOURS = 30; // runs happen after every draw and each morning
const CHART_WEEKS = 26;
const CHART_FROM = "2026-04-14"; // Lotto Max's current format started then
const REFRESH_AFTER_MS = 5 * 60 * 1000;
const BASIS_KEY = "lotto-calculator.basis";
const DEFAULT_MINIMUM = 0.3; // matches MIN_WORTH_PLAYING in lottocalc/value.py

const state = { next: null, draws: [], basis: readBasis(), loadedAt: 0, loading: false };

function readBasis() {
  try {
    return localStorage.getItem(BASIS_KEY) === "all_prizes" ? "all_prizes" : "top_prizes";
  } catch {
    return "top_prizes";
  }
}

function saveBasis(basis) {
  try {
    localStorage.setItem(BASIS_KEY, basis);
  } catch {
    // private browsing: the choice just isn't remembered
  }
}

// ---------- formatting ----------

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const oneDecimal = (x) => String(Math.round(x * 10) / 10);

function money(n) {
  if (n >= 1e6) return "$" + oneDecimal(n / 1e6) + "M";
  if (n >= 1e3) return "$" + oneDecimal(n / 1e3) + "K";
  return "$" + n;
}

function perDollar(v) {
  return "$" + v.toFixed(2);
}

function oneIn(n) {
  let s;
  if (n >= 1e8) s = Math.round(n / 1e6) + "M";
  else if (n >= 1e6) s = oneDecimal(n / 1e6) + "M";
  else if (n >= 1e4) s = Math.round(n / 1e3) + "K";
  else s = Math.round(n).toLocaleString("en-CA");
  return "1 in " + s;
}

function playsText(n) {
  return (n / 1e6).toFixed(2) + "M";
}

function dayText(isoDate) {
  return new Date(isoDate + "T12:00:00").toLocaleDateString("en-CA", { weekday: "short", month: "short", day: "numeric" });
}

function agoText(iso) {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return minutes + " min ago";
  const hours = Math.round(minutes / 60);
  if (hours < 48) return hours + " h ago";
  return Math.round(hours / 24) + " days ago";
}

function todayInToronto() {
  // en-CA formats as YYYY-MM-DD, the same shape as draw dates
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Toronto", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function otherGame(game) {
  return game === "lottomax" ? "lotto649" : "lottomax";
}

function prizeLine(game, info) {
  if (game === "lottomax") {
    const extra = info.maxmillions_count ? ` + ${info.maxmillions_count} × $1M` : "";
    return `${money(info.jackpot)} jackpot${extra}`;
  }
  return `${money(info.gold_ball_amount)} Gold Ball, ${info.balls_remaining} balls left`;
}

// ---------- page sections ----------

function noticesHtml(next) {
  const notes = [];
  if (next.errors && next.errors.length) {
    const more = next.errors.length > 1 ? ` (and ${next.errors.length - 1} more)` : "";
    notes.push(["error", `The last update ran into a problem: ${next.errors[0]}${more}`]);
  }
  if ((Date.now() - Date.parse(next.scraped_at)) / 36e5 > STALE_HOURS) {
    notes.push(["warn", `These numbers were last checked ${agoText(next.scraped_at)}, so a jackpot may have changed.`]);
  }
  const today = todayInToronto();
  for (const game of Object.keys(GAMES)) {
    const info = next[game];
    if (!info) continue;
    if (info.stale) notes.push(["warn", `${GAMES[game].name} couldn't be refreshed; showing data from ${agoText(info.as_of)}.`]);
    else if (info.draw_date < today) notes.push(["warn", `${GAMES[game].name}'s ${dayText(info.draw_date)} draw is over; the next jackpot isn't posted yet.`]);
  }
  return notes.map(([level, text]) => `<p class="notice ${level}">${esc(text)}</p>`).join("");
}

function minimumToPlay(next) {
  return (next.recommendation && next.recommendation.min_per_dollar) || DEFAULT_MINIMUM;
}

function worthPlaying(next) {
  const recommendation = next.recommendation;
  if (!recommendation) return false;
  // next.json files written before the minimum existed lack "play"
  return recommendation.play ?? recommendation.top_prizes.per_dollar >= minimumToPlay(next);
}

function skipHtml(next) {
  const top = next.recommendation.top_prizes; // the minimum is judged on big prizes
  const best = top.game;
  const minimum = minimumToPlay(next);
  return `
    <p class="eyebrow">Next draws</p>
    <h1>Skip for now</h1>
    <p class="when">Neither game reaches your ${perDollar(minimum)} minimum back per $1 in big prizes</p>
    <div class="compare">
      <div><span class="big">${perDollar(top.per_dollar)}</span><span class="label">${GAMES[best].name}</span></div>
      <div class="vs">vs</div>
      <div><span class="big">${perDollar(top.runner_up_per_dollar)}</span><span class="label">${GAMES[otherGame(best)].name}</span></div>
    </div>
    <p class="margin">The better one, ${GAMES[best].name}, is ${perDollar(minimum - top.per_dollar)} short.</p>`;
}

function verdictHtml(next, basis) {
  const rec = next.recommendation && next.recommendation[basis];
  if (!rec) {
    // Between a draw and the posting of the next jackpot, the source still lists the finished draw.
    const waiting = Object.keys(GAMES).some((g) => next[g] && !next[g].draw_number);
    const message = waiting
      ? "Waiting for the next jackpot to be posted after the last draw. Check back in an hour or two."
      : "Not enough data to compare the games yet.";
    return `<p class="eyebrow">Better buy for the next draw</p><p class="loading">${message}</p>`;
  }
  if (!worthPlaying(next)) return skipHtml(next);
  const best = rec.game;
  const other = otherGame(best);
  const counted = basis === "all_prizes" ? "all prizes" : "big prizes";
  return `
    <p class="eyebrow">Better buy for the next draw</p>
    <h1 class="${GAMES[best].css}">Play ${GAMES[best].name}</h1>
    <p class="when">${esc(dayText(next[best].draw_date))} · ${esc(prizeLine(best, next[best]))}</p>
    <div class="compare">
      <div><span class="big ${GAMES[best].css}">${perDollar(rec.per_dollar)}</span><span class="label">${GAMES[best].name}</span></div>
      <div class="vs">vs</div>
      <div><span class="big">${perDollar(rec.runner_up_per_dollar)}</span><span class="label">${GAMES[other].name}</span></div>
    </div>
    <p class="margin">back per $1 in ${counted}: <strong>${perDollar(rec.margin)} more</strong> with ${GAMES[best].name}</p>
    ${rec.close_call ? `<p class="margin"><span class="badge">Close call</span> the sales forecasts leave room for ${GAMES[other].name} to come out ahead</p>` : ""}`;
}

function prizesHtml(game, info) {
  if (game === "lottomax") {
    const chips = [];
    if (info.maxmillions_count) chips.push(`${info.maxmillions_count} × $1M MAXMILLIONS`);
    if (info.maxplus_count) chips.push(`${info.maxplus_count} × ${money(info.maxplus_prize)} MAXPLUS`);
    return `
      <div class="prize"><span class="prize-main">${money(info.jackpot)}</span><span class="muted">jackpot</span></div>
      <ul class="chips">${chips.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;
  }
  return `
    <div class="prize"><span class="prize-main">${money(info.gold_ball_amount)}</span><span class="muted">Gold Ball jackpot</span></div>
    <ul class="chips">
      <li>${info.balls_remaining} ${info.balls_remaining === 1 ? "ball" : "balls"} left, 1 gold</li>
      <li>$1M if the drawn ticket gets a white ball</li>
      <li>Classic $5M</li>
    </ul>`;
}

function gameHtml(game, info, basis) {
  const g = GAMES[game];
  if (!info) {
    return `<section class="card"><div class="game-head"><h2 class="${g.css}">${g.name}</h2></div><p class="muted">No data for the next draw.</p></section>`;
  }
  const head = `
    <div class="game-head">
      <h2 class="${g.css}">${g.name}</h2>
      <span class="muted small">${esc(dayText(info.draw_date))} · #${info.draw_number ?? "?"}</span>
    </div>`;
  const value = info.value;
  const forecast = info.forecast;
  if (!value || !forecast) {
    return `<section class="card">${head}${prizesHtml(game, info)}<p class="note">No sales forecast yet, so no value.</p></section>`;
  }

  const all = basis === "all_prizes";
  const perDollarValue = all ? value.per_dollar_all_prizes : value.per_dollar;
  const [low, high] = all ? value.per_dollar_all_prizes_range : value.per_dollar_range;
  const parts = Object.entries(value.parts).filter(([key, v]) => v > 0 && (all || key !== "lower_tiers"));
  const total = parts.reduce((sum, [, v]) => sum + v, 0);
  const shades = [1, 0.7, 0.5, 0.35, 0.22];
  const bar = parts
    .map(([, v], i) => `<span style="width:${(100 * v) / total}%;background:var(--${g.css});opacity:${shades[i] ?? 0.2}"></span>`)
    .join("");
  const legend = parts
    .map(([key, v], i) => `<li><i style="background:var(--${g.css});opacity:${shades[i] ?? 0.2}"></i>${esc(PARTS[key] ?? key)} ${perDollar(v)}</li>`)
    .join("");
  const rangeText = perDollar(low) !== perDollar(high)
    ? `${perDollar(low)}–${perDollar(high)} across the sales forecast`
    : "barely moves with sales";

  const plays6 = 6 / value.price;
  const odds = value.odds_one_in;
  const oddsRow = (label, n) =>
    `<div><dt>${label}</dt><dd>${oneIn(n / plays6)}${plays6 > 1 ? `<small>${oneIn(n)} per $${value.price} play</small>` : ""}</dd></div>`;

  const notes = [];
  if (forecast.assumes_no_super_draw) notes.push("Assumes a regular draw: Super Draws aren't announced where this page can read them.");

  return `
    <section class="card">
      ${head}
      ${prizesHtml(game, info)}
      <div class="value">
        <div class="value-row"><span class="value-num">${perDollar(perDollarValue)}</span><span class="muted">back per $1${all ? "" : " in big prizes"}</span></div>
        <p class="muted small">${rangeText}</p>
        <div class="bar">${bar}</div>
        <ul class="legend">${legend}</ul>
      </div>
      <dl class="stats">
        ${oddsRow("Jackpot odds for $6", odds.jackpot)}
        ${oddsRow("$1M or more for $6", odds.million_plus)}
        <div><dt>Sales forecast</dt><dd>${playsText(forecast.plays)} plays<small>${playsText(forecast.low)}–${playsText(forecast.high)}, typical miss ${(forecast.backtest_mape * 100).toFixed(1)}%</small></dd></div>
      </dl>
      ${notes.map((n) => `<p class="note">${esc(n)}</p>`).join("")}
    </section>`;
}

// ---------- charts ----------

// What a ticket was worth per $1 at each draw: in big prizes (with the play minimum), and
// counting every prize. `draw` and `next` name the value fields in draws.json and next.json.
const CHARTS = [
  { el: "chart", readout: "readout", draw: "value_per_dollar", next: "per_dollar", allPrizes: false },
  { el: "chart-all", readout: "readout-all", draw: "value_per_dollar_all_prizes", next: "per_dollar_all_prizes", allPrizes: true },
];

function chartSeries(draws, next, chart) {
  const dates = draws.map((d) => d.draw_date).sort();
  const latest = dates[dates.length - 1];
  const cutoff = new Date(Date.parse(latest) - CHART_WEEKS * 7 * 864e5).toISOString().slice(0, 10);
  const from = cutoff > CHART_FROM ? cutoff : CHART_FROM;
  return Object.keys(GAMES).map((game) => ({
    game,
    points: draws
      .filter((d) => d.game === game && d.draw_date >= from && d[chart.draw] != null)
      .map((d) => ({ t: Date.parse(d.draw_date), v: d[chart.draw], draw: d })),
    next: typeof next[game]?.value?.[chart.next] === "number"
      ? { t: Date.parse(next[game].draw_date), v: next[game].value[chart.next], info: next[game] }
      : null,
  }));
}

function renderChart(chart, draws, next) {
  const el = document.getElementById(chart.el);
  if (!el) return; // a cached older index.html without this chart
  const readout = document.getElementById(chart.readout);
  readout.textContent = "Tap the chart for a draw's details.";
  const series = draws.length ? chartSeries(draws, next, chart) : [];
  const all = series.flatMap((s) => s.points.concat(s.next ? [s.next] : []));
  if (!all.length) {
    el.innerHTML = `<p class="muted small">No history yet.</p>`;
    return;
  }
  const W = 360, H = 220, L = 38, R = 8, T = 8, B = 22; // about 1 unit per CSS pixel on a phone
  const t0 = Math.min(...all.map((p) => p.t));
  const t1 = Math.max(...all.map((p) => p.t));
  const step = 0.1;
  const minimum = chart.allPrizes ? null : minimumToPlay(next); // the minimum is judged on big prizes
  const vMax = Math.max(step * 2, Math.ceil((Math.max(minimum ?? 0, ...all.map((p) => p.v)) * 1.05) / step) * step);
  const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - v / vMax) * (H - T - B);

  const grid = [];
  const gridStep = vMax > 1 ? 0.5 : vMax > 0.5 ? 0.2 : 0.1;
  for (let v = 0; v <= vMax + 1e-9; v += gridStep) {
    grid.push(`<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`);
    grid.push(`<text class="axis" x="${L - 5}" y="${y(v) + 3.5}" text-anchor="end">$${v.toFixed(2)}</text>`);
  }
  const months = [];
  const start = new Date(t0);
  for (let d = new Date(start.getFullYear(), start.getMonth() + 1, 1); d.getTime() <= t1; d.setMonth(d.getMonth() + 1)) {
    months.push(`<text class="axis" x="${x(d.getTime())}" y="${H - 6}" text-anchor="middle">${d.toLocaleDateString("en-CA", { month: "short" })}</text>`);
  }

  const shapes = series
    .map((s) => {
      const css = GAMES[s.game].css;
      const line = s.points.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
      const dots = s.points.map((p) => `<circle class="${css}" cx="${x(p.t).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2"/>`).join("");
      let upcoming = "";
      if (s.next) {
        const last = s.points[s.points.length - 1];
        if (last) upcoming += `<line class="${css}" x1="${x(last.t)}" y1="${y(last.v)}" x2="${x(s.next.t)}" y2="${y(s.next.v)}" stroke-dasharray="3 3" stroke-width="1.2"/>`;
        upcoming += `<circle class="${css} next" cx="${x(s.next.t)}" cy="${y(s.next.v)}" r="3.8"/>`;
      }
      return `<polyline class="line ${css}" points="${line}" fill="none"/>${dots}${upcoming}`;
    })
    .join("");

  const minimumLine = minimum == null ? "" : `<line class="minline" x1="${L}" x2="${W - R}" y1="${y(minimum)}" y2="${y(minimum)}"/>`;
  const minimumKey = minimum == null ? "" : `<span class="minkey">${perDollar(minimum)} minimum</span>`;
  const described = chart.allPrizes ? "with all prizes" : "in big prizes";

  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Value per dollar ${described} of each game's recent draws">
      ${grid.join("")}${months.join("")}${minimumLine}${shapes}
      <circle class="focus" r="6" cx="-20" cy="-20"/>
    </svg>
    <div class="chart-legend">${Object.keys(GAMES).map((g) => `<span class="${GAMES[g].css}">${GAMES[g].name}</span>`).join("")}${minimumKey}</div>`;

  const svg = el.querySelector("svg");
  const focus = el.querySelector(".focus");
  const targets = series.flatMap((s) =>
    s.points.map((p) => ({ ...p, game: s.game })).concat(s.next ? [{ ...s.next, game: s.game, upcoming: true }] : []),
  );
  const pick = (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    const py = ((event.clientY - box.top) / box.height) * H;
    let best = null;
    let bestDistance = Infinity;
    for (const p of targets) {
      const distance = Math.hypot(x(p.t) - px, (y(p.v) - py) * 0.6);
      if (distance < bestDistance) [best, bestDistance] = [p, distance];
    }
    if (!best) return;
    focus.setAttribute("cx", x(best.t));
    focus.setAttribute("cy", y(best.v));
    readout.textContent = readoutText(best, chart);
  };
  svg.addEventListener("pointerdown", pick);
  svg.addEventListener("pointermove", (event) => {
    if (event.pointerType === "mouse" || event.buttons) pick(event);
  });
}

function worthText(chart, big, all) {
  if (!chart.allPrizes) return `${perDollar(big)} per $1`;
  return `${perDollar(all)} per $1 with all prizes (${perDollar(big)} big + ${perDollar(all - big)} smaller)`;
}

function readoutText(p, chart) {
  const name = GAMES[p.game].name;
  if (p.upcoming) {
    const worth = worthText(chart, p.info.value.per_dollar, p.info.value.per_dollar_all_prizes);
    return `${name}, next draw ${dayText(p.info.draw_date)}: ${prizeLine(p.game, p.info)}. Forecast ${worth}.`;
  }
  const d = p.draw;
  const plays = `${playsText(d.est_plays)} plays sold`;
  const worth = worthText(chart, d.value_per_dollar, d.value_per_dollar_all_prizes);
  if (p.game === "lottomax") {
    const won = d.tier_winners["7/7"] ? ", jackpot won" : "";
    return `${name}, ${dayText(d.draw_date)}: ${money(d.jackpot)} jackpot${won}, ${plays}. Worth ${worth}.`;
  }
  const ball = d.gold_ball_drawn === "gold" ? ", gold ball drawn" : "";
  const extra = d.super_draw ? ", Super Draw" : "";
  return `${name}, ${dayText(d.draw_date)}: ${money(d.gold_ball_amount)} Gold Ball with ${d.balls_remaining} balls${ball}${extra}, ${plays}. Worth ${worth}.`;
}

// ---------- loading and events ----------

function render() {
  const { next, draws, basis } = state;
  document.getElementById("refresh").textContent = `Updated ${agoText(next.scraped_at)}`;
  document.getElementById("notices").innerHTML = noticesHtml(next);
  const verdict = document.getElementById("verdict");
  const rec = next.recommendation && next.recommendation[basis];
  const accent = !rec ? "" : worthPlaying(next) ? " accent-" + GAMES[rec.game].css : " accent-skip";
  verdict.className = "card verdict" + accent;
  verdict.innerHTML = verdictHtml(next, basis);
  const order = rec ? [rec.game, otherGame(rec.game)] : Object.keys(GAMES);
  document.getElementById("games").innerHTML = order.map((g) => gameHtml(g, next[g], basis)).join("");
  for (const button of document.querySelectorAll("#basis button")) {
    button.setAttribute("aria-pressed", String(button.dataset.basis === basis));
  }
}

// Draws the page; the charts only when the data changed (they don't depend on the prize toggle).
function show(withCharts) {
  try {
    render();
    if (withCharts) for (const chart of CHARTS) renderChart(chart, state.draws, state.next);
  } catch (error) {
    console.error(error);
    showProblem(`Something went wrong showing the numbers (${error.message}). Tap the Updated button to try again.`);
  }
}

function showProblem(text) {
  document.getElementById("notices").innerHTML = `<p class="notice error">${esc(text)}</p>`;
}

async function fetchJson(path) {
  const response = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

async function load() {
  if (state.loading) return;
  state.loading = true;
  document.getElementById("refresh").textContent = "Updating…";
  try {
    const [next, draws] = await Promise.all([fetchJson("data/next.json"), fetchJson("data/draws.json")]);
    Object.assign(state, { next, draws: draws.draws, loadedAt: Date.now() });
  } catch (error) {
    showProblem(`Couldn't load the data (${error.message}). Tap Retry, or try again in a few minutes.`);
    document.getElementById("refresh").textContent = "Retry";
    return;
  } finally {
    state.loading = false;
  }
  show(true);
}

document.getElementById("basis").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-basis]");
  if (!button || !state.next) return;
  state.basis = button.dataset.basis;
  saveBasis(state.basis);
  show(false);
});
document.getElementById("refresh").addEventListener("click", load);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - state.loadedAt > REFRESH_AFTER_MS) load();
});
load();
