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
const REFRESH_AFTER_MS = 5 * 60 * 1000; // when the page comes back into view
const RELOAD_OPEN_MS = 15 * 60 * 1000; // while it stays open and visible
const TICK_MS = 60 * 1000; // keeps "Updated … ago" current
const BASIS_KEY = "lotto-calculator.basis";
const DEFAULT_MINIMUM = 0.3; // matches MIN_WORTH_PLAYING in lottocalc/value.py
const WHOLE_TICKET_MINIMUM = 0.45; // the dashed line on the whole-ticket chart
const GOLD_BALL_STEP = 2e6; // each white ball adds $2M (GOLD_BALL_STEP in lottocalc/model.py)
const DRAW_DAYS = { lotto649: [3, 6], lottomax: [2, 5] }; // Wed/Sat, Tue/Fri

const state = { next: null, draws: [], basis: readBasis(), loadedAt: 0, loading: false, failed: false };

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

// Both games as bars from $0, with the play minimum marked when judging big prizes.
function barsHtml(first, firstValue, secondValue, minimum, highlightFirst) {
  const top = Math.max(firstValue, secondValue, minimum ?? 0) * 1.15 || 1;
  const pct = (v) => `${Math.min(100, (100 * v) / top).toFixed(1)}%`;
  const bar = (game, v, best) => `
    <div class="vs-row${best ? " is-best" : ""}">
      <span class="vs-name"><i class="dot ${GAMES[game].css}"></i>${GAMES[game].name}</span>
      <span class="vs-track"><span class="vs-fill ${GAMES[game].css}" style="width:${pct(v)}"></span></span>
      <span class="vs-num">${perDollar(v)}</span>
    </div>`;
  const min = minimum == null
    ? ""
    : `<span class="vs-min" style="left:${pct(minimum)}"><span>${perDollar(minimum)} min</span></span>`;
  return `
    <div class="vs">
      ${bar(first, firstValue, highlightFirst)}${bar(otherGame(first), secondValue, false)}
      <div class="vs-min-layer" aria-hidden="true">${min}</div>
    </div>`;
}

function skipHtml(next) {
  const top = next.recommendation.top_prizes; // the minimum is judged on big prizes
  const best = top.game;
  const minimum = minimumToPlay(next);
  return `
    <p class="kicker">Recommendation</p>
    <h1 class="verdict-title">Skip for now</h1>
    <p class="verdict-sub">Neither game reaches the ${perDollar(minimum)} minimum back per $1 in big prizes.</p>
    ${barsHtml(best, top.per_dollar, top.runner_up_per_dollar, minimum, false)}
    <p class="verdict-foot">The closer one, ${GAMES[best].name}, is <strong>${perDollar(minimum - top.per_dollar)} short</strong>.</p>`;
}

function verdictHtml(next, basis) {
  const rec = next.recommendation && next.recommendation[basis];
  if (!rec) {
    // Between a draw and the posting of the next jackpot, the source still lists the finished draw.
    const waiting = Object.keys(GAMES).some((g) => next[g] && !next[g].draw_number);
    const message = waiting
      ? "Waiting for the next jackpot to be posted after the last draw. Check back in an hour or two."
      : "Not enough data to compare the games yet.";
    return `<p class="kicker">Recommendation</p><p class="verdict-sub">${message}</p>`;
  }
  if (!worthPlaying(next)) return skipHtml(next);
  const best = rec.game;
  const other = otherGame(best);
  const counted = basis === "all_prizes" ? "all prizes" : "big prizes";
  const minimum = basis === "top_prizes" ? minimumToPlay(next) : null;
  return `
    <p class="kicker">Recommendation</p>
    <h1 class="verdict-title">Play <span class="${GAMES[best].css}">${GAMES[best].name}</span></h1>
    <p class="verdict-sub">${esc(dayText(next[best].draw_date))} · ${esc(prizeLine(best, next[best]))}</p>
    ${barsHtml(best, rec.per_dollar, rec.runner_up_per_dollar, minimum, true)}
    <p class="verdict-foot"><strong>${perDollar(rec.margin)} more back per $1</strong> than ${GAMES[other].name}, counting ${counted}.</p>
    ${rec.close_call ? `<p class="verdict-foot"><span class="badge">Close call</span> The sales forecasts leave room for ${GAMES[other].name} to come out ahead.</p>` : ""}`;
}

function prizeFacts(game, info) {
  if (game === "lottomax") {
    const tags = [];
    if (info.maxmillions_count) tags.push(`${info.maxmillions_count} × $1M MAXMILLIONS`);
    if (info.maxplus_count) tags.push(`${info.maxplus_count} × ${money(info.maxplus_prize)} MAXPLUS`);
    return { label: "Jackpot", amount: money(info.jackpot), tags };
  }
  const balls = `${info.balls_remaining} ${info.balls_remaining === 1 ? "ball" : "balls"} left, 1 gold`;
  return { label: "Gold Ball jackpot", amount: money(info.gold_ball_amount), tags: [balls, "White ball pays $1M", "Classic $5M"] };
}

// The date `count` draws after `isoDate`, on the game's draw days.
function drawDateAfter(game, isoDate, count) {
  const date = new Date(isoDate + "T12:00:00");
  for (let left = count; left > 0; ) {
    date.setDate(date.getDate() + 1);
    if (DRAW_DAYS[game].includes(date.getDay())) left--;
  }
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`; // local, not UTC
}

// Whether each game is sure to pay out. Every 6/49 draw pays one ticket $1M or the Gold Ball
// jackpot, and white balls leave the drum, so the gold ball must come out by the draw where
// it's the only ball left. Lotto Max has no must-win rule.
function guaranteeHtml(game, info) {
  if (game === "lottomax") {
    return `<div class="guarantee"><p class="guarantee-title">No guaranteed winner</p><p>Lotto Max has no must-win draw: the jackpot rolls over until a ticket matches all 7 numbers.</p></div>`;
  }
  const balls = info.balls_remaining;
  if (!balls) return "";
  const title = `<p class="guarantee-title is-sure">A winner every draw</p>`;
  const every = "Each draw, one ticket wins $1M (white ball) or the Gold Ball jackpot (gold ball).";
  if (balls === 1) {
    return `<div class="guarantee">${title}<p>${every} Only the gold ball is left, so <strong>this draw's ${money(info.gold_ball_amount)} Gold Ball jackpot will be won</strong>.</p></div>`;
  }
  const ahead = balls - 1;
  const lastDraw = info.draw_number ? `Draw ${info.draw_number + ahead}, ` : "";
  const lastDate = dayText(drawDateAfter(game, info.draw_date, ahead));
  const lastAmount = money(info.gold_ball_amount + ahead * GOLD_BALL_STEP);
  return `
    <div class="guarantee">${title}
      <p>${every} The jackpot is <strong>guaranteed to be won by ${esc(lastDraw)}${esc(lastDate)}</strong> at ${lastAmount}, when the gold ball would be the last one left. Chance it comes out this draw: 1 in ${balls}.</p>
    </div>`;
}

// One card per game: the jackpot, what $1 is worth and why, then the odds and the forecast.
function gameHtml(game, info, basis) {
  const g = GAMES[game];
  const head = (when) => `
    <div class="game-head">
      <h2><i class="dot ${g.css}"></i>${g.name}</h2>
      ${when ? `<span class="game-when">${when}</span>` : ""}
    </div>`;
  if (!info) return `<section class="card game">${head("")}<p class="caption">No data for the next draw.</p></section>`;

  const when = `${esc(dayText(info.draw_date))} · Draw ${info.draw_number ?? "?"}`;
  const facts = prizeFacts(game, info);
  const jackpot = `
    <p class="kicker">${facts.label}</p>
    <p class="jackpot">${facts.amount}</p>
    ${facts.tags.length ? `<ul class="tags">${facts.tags.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${guaranteeHtml(game, info)}`;
  const value = info.value;
  const forecast = info.forecast;
  if (!value || !forecast) {
    return `<section class="card game">${head(when)}${jackpot}<p class="note">No sales forecast yet, so no value.</p></section>`;
  }

  const all = basis === "all_prizes";
  const worth = all ? value.per_dollar_all_prizes : value.per_dollar;
  const [low, high] = all ? value.per_dollar_all_prizes_range : value.per_dollar_range;
  const parts = Object.entries(value.parts).filter(([key, v]) => v > 0 && (all || key !== "lower_tiers"));
  const total = parts.reduce((sum, [, v]) => sum + v, 0);
  const shades = [1, 0.7, 0.5, 0.35, 0.22];
  const bar = parts
    .map(([, v], i) => `<span style="width:${(100 * v) / total}%;background:var(--${g.css});opacity:${shades[i] ?? 0.2}"></span>`)
    .join("");
  const legend = parts
    .map(([key, v], i) => `<li><span><i style="background:var(--${g.css});opacity:${shades[i] ?? 0.2}"></i>${esc(PARTS[key] ?? key)}</span><b>${perDollar(v)}</b></li>`)
    .join("");
  const rangeText = perDollar(low) !== perDollar(high)
    ? `${perDollar(low)}–${perDollar(high)} across the sales forecast`
    : "Barely moves with sales";

  const plays6 = 6 / value.price;
  const odds = value.odds_one_in;
  const perPlay = (n) => (plays6 > 1 ? `${oneIn(n)} per $${value.price} play` : `One $${value.price} play`);
  const row = (label, main, detail) => `<li><span>${label}</span><b>${main}</b><small>${detail}</small></li>`;
  const notes = [];
  if (forecast.assumes_no_super_draw) notes.push("Assumes a regular draw: Super Draws aren't announced where this page can read them.");

  return `
    <section class="card game">
      ${head(when)}
      ${jackpot}
      <div class="value">
        <div class="value-head">
          <span class="kicker">Value per $1</span>
          <span class="value-num ${g.css}">${perDollar(worth)}</span>
        </div>
        <p class="caption">${rangeText}</p>
        <div class="bar">${bar}</div>
        <ul class="list parts">${legend}</ul>
      </div>
      <ul class="list facts">
        ${row("Jackpot odds for $6", oneIn(odds.jackpot / plays6), perPlay(odds.jackpot))}
        ${row("$1M or more for $6", oneIn(odds.million_plus / plays6), perPlay(odds.million_plus))}
        ${row("Sales forecast", `${playsText(forecast.plays)} plays`, `${playsText(forecast.low)}–${playsText(forecast.high)} likely`)}
        ${row("Forecast accuracy", `±${(forecast.backtest_mape * 100).toFixed(1)}%`, "Typical miss, backtested")}
      </ul>
      ${notes.map((n) => `<p class="note">${esc(n)}</p>`).join("")}
    </section>`;
}

// ---------- charts ----------

// What a ticket was worth per $1 at each draw: in big prizes (with the play minimum), and
// counting every prize (with its own minimum). `draw` and `next` name the value fields in
// draws.json and next.json; a chart without `minimum` uses the play minimum in next.json.
const CHARTS = [
  { el: "chart", readout: "readout", draw: "value_per_dollar", next: "per_dollar", allPrizes: false },
  { el: "chart-all", readout: "readout-all", draw: "value_per_dollar_all_prizes", next: "per_dollar_all_prizes", allPrizes: true, minimum: WHOLE_TICKET_MINIMUM },
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
    el.innerHTML = `<p class="caption">No history yet.</p>`;
    return;
  }
  // Drawn at the chart's own width, one unit per CSS pixel, so labels keep their size in a
  // narrow column.
  const W = Math.max(150, Math.round(el.clientWidth || 360));
  const H = Math.round(Math.min(240, Math.max(150, W * 0.62)));
  const L = 34, R = 6, T = 8, B = 22;
  const t0 = Math.min(...all.map((p) => p.t));
  const t1 = Math.max(...all.map((p) => p.t));
  const step = 0.1;
  const minimum = chart.minimum ?? minimumToPlay(next);
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
  const monthCount = Math.max(1, Math.round((t1 - t0) / (30.4 * 864e5)));
  const everyOther = (W - L - R) / monthCount < 30; // too narrow for every month's name
  let index = 0;
  for (let d = new Date(start.getFullYear(), start.getMonth() + 1, 1); d.getTime() <= t1; d.setMonth(d.getMonth() + 1)) {
    if (everyOther && index++ % 2) continue;
    months.push(`<text class="axis" x="${x(d.getTime())}" y="${H - 6}" text-anchor="middle">${d.toLocaleDateString("en-CA", { month: "short" })}</text>`);
  }

  // Each game's line is drawn twice, clipped at the minimum: its bright shade above the line,
  // its faded shade below, so the colour changes exactly where the line crosses. Dots take
  // the shade of their own side.
  const clipAbove = `${chart.el}-above`;
  const clipBelow = `${chart.el}-below`;
  const yMin = y(minimum);
  const side = (v) => (v >= minimum ? "hi" : "lo");
  const both = (shape) =>
    `${shape.replace("SIDE", "hi").replace("CLIP", clipAbove)}${shape.replace("SIDE", "lo").replace("CLIP", clipBelow)}`;
  const shapes = series
    .map((s) => {
      const css = GAMES[s.game].css;
      const line = s.points.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
      const dots = s.points.map((p) => `<circle class="${css} ${side(p.v)}" cx="${x(p.t).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2"/>`).join("");
      let upcoming = "";
      if (s.next) {
        const last = s.points[s.points.length - 1];
        if (last) upcoming += both(`<line class="${css} SIDE" clip-path="url(#CLIP)" x1="${x(last.t)}" y1="${y(last.v)}" x2="${x(s.next.t)}" y2="${y(s.next.v)}" stroke-dasharray="3 3" stroke-width="1.2"/>`);
        upcoming += `<circle class="${css} ${side(s.next.v)} next" cx="${x(s.next.t)}" cy="${y(s.next.v)}" r="3.8"/>`;
      }
      return `${both(`<polyline class="line ${css} SIDE" clip-path="url(#CLIP)" points="${line}" fill="none"/>`)}${dots}${upcoming}`;
    })
    .join("");
  const clips = `
    <defs>
      <clipPath id="${clipAbove}"><rect x="0" y="0" width="${W}" height="${yMin}"/></clipPath>
      <clipPath id="${clipBelow}"><rect x="0" y="${yMin}" width="${W}" height="${H - yMin}"/></clipPath>
    </defs>`;

  const minimumLine = minimum == null ? "" : `<line class="minline" x1="${L}" x2="${W - R}" y1="${y(minimum)}" y2="${y(minimum)}"/>`;
  const minimumKey = minimum == null ? "" : `<span class="key-min">${perDollar(minimum)} minimum</span>`;
  const described = chart.allPrizes ? "with all prizes" : "in big prizes";

  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Value per dollar ${described} of each game's recent draws">
      ${clips}${grid.join("")}${months.join("")}${minimumLine}${shapes}
      <circle class="focus" r="6" cx="-20" cy="-20"/>
    </svg>
    <div class="chart-legend">${Object.keys(GAMES).map((g) => `<span class="key-${GAMES[g].css}"><i class="hi"></i><i class="lo"></i>${GAMES[g].name}</span>`).join("")}${minimumKey}</div>
    <p class="chart-key-note">Brighter above the minimum, softer below it.</p>`;

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
    const where = best.v >= minimum ? "above" : "below";
    readout.textContent = `${readoutText(best, chart)} That's ${where} the ${perDollar(minimum)} minimum.`;
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

// The pill in the top corner: green when fresh, amber when stale, red after an error.
function setStatus(text, kind) {
  const button = document.getElementById("refresh");
  button.className = `status is-${kind}`;
  button.querySelector(".status-text").textContent = text;
  button.setAttribute("aria-label", `${text}. Tap to refresh`);
}

function showUpdated(next) {
  const hoursOld = (Date.now() - Date.parse(next.scraped_at)) / 36e5;
  const health = next.errors && next.errors.length ? "error" : hoursOld > STALE_HOURS ? "stale" : "ok";
  setStatus(`Updated ${agoText(next.scraped_at)}`, health);
}

function render() {
  const { next, basis } = state;
  showUpdated(next);
  document.getElementById("notices").innerHTML = noticesHtml(next);
  document.getElementById("verdict").innerHTML = verdictHtml(next, basis);
  const rec = next.recommendation && next.recommendation[basis];
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
    showProblem(`Something went wrong showing the numbers (${error.message}). Tap the status button at the top to try again.`);
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
  setStatus("Updating", "busy");
  try {
    const [next, draws] = await Promise.all([fetchJson("data/next.json"), fetchJson("data/draws.json")]);
    Object.assign(state, { next, draws: draws.draws, loadedAt: Date.now(), failed: false });
  } catch (error) {
    state.failed = true;
    showProblem(`Couldn't load the data (${error.message}). Tap Retry, or try again in a few minutes.`);
    setStatus("Retry", "error");
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
// The charts are drawn to their width, so redraw them when it changes (rotating a phone).
let chartWidth = 0;
let resizeTimer = 0;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const width = document.getElementById("chart")?.clientWidth;
    if (!state.next || !width || width === chartWidth) return;
    chartWidth = width;
    for (const chart of CHARTS) renderChart(chart, state.draws, state.next);
  }, 150);
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && (state.failed || Date.now() - state.loadedAt > REFRESH_AFTER_MS)) load();
});
// A page left open (say on a desktop) keeps its age label current, picks up new data, and
// retries a failed load rather than leaving "Retry" up.
setInterval(() => {
  if (document.visibilityState !== "visible" || state.loading) return;
  if (state.failed || Date.now() - state.loadedAt > RELOAD_OPEN_MS) load();
  else if (state.next) showUpdated(state.next);
}, TICK_MS);
load();
