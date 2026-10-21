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
const CHART_MONTHS = 12;
const REFRESH_AFTER_MS = 5 * 60 * 1000; // when the page comes back into view
const RELOAD_OPEN_MS = 15 * 60 * 1000; // while it stays open and visible
const TICK_MS = 60 * 1000; // keeps "Updated … ago" current
const BASIS_KEY = "lotto-calculator.basis";
const MAX_TICKET_PLAYS = { lottomax: 5, lotto649: 10 }; // the most plays one ticket holds: $30 either way
const DEFAULT_MINIMUM = 0.4; // MIN_WORTH_PLAYING in lottocalc/value.py, for the chart while next.json has no recommendation
const WHOLE_TICKET_MINIMUM = 0.55; // the whole-ticket guide: the dashed line on its chart and bars (WHOLE_TICKET_ALERT in lottocalc/alerts.py)
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
  if (next.errors.length) {
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
  return next.recommendation?.min_per_dollar ?? DEFAULT_MINIMUM;
}

// Both games as bars from $0, with the minimum for the prizes counted marked across them.
function barsHtml(first, firstValue, secondValue, minimum, highlightFirst) {
  const top = Math.max(firstValue, secondValue, minimum) * 1.15;
  const pct = (v) => `${Math.min(100, (100 * v) / top).toFixed(1)}%`;
  const bar = (game, v, best) => `
    <div class="vs-row${best ? " is-best" : ""}">
      <span class="vs-name"><i class="dot ${GAMES[game].css}"></i>${GAMES[game].name}</span>
      <span class="vs-track"><span class="vs-fill ${GAMES[game].css}" style="width:${pct(v)}"></span></span>
      <span class="vs-num">${perDollar(v)}</span>
    </div>`;
  const min = `<span class="vs-min" style="left:${pct(minimum)}"><span>${perDollar(minimum)} min</span></span>`;
  return `
    <div class="vs">
      ${bar(first, firstValue, highlightFirst)}${bar(otherGame(first), secondValue, false)}
      <div class="vs-min-layer" aria-hidden="true">${min}</div>
    </div>`;
}

// "$0.04 short", or "just short" when it rounds to under a cent.
function shortBy(gap) {
  return gap < 0.005 ? "just short" : `${perDollar(gap)} short`;
}

// The pick goes by big prizes; the All prizes view shows where the games stand against the
// whole-ticket minimum.
function skipHtml(next, basis) {
  const top = next.recommendation.top_prizes;
  const minimum = minimumToPlay(next);
  const title = `<p class="kicker">Recommendation</p><h1 class="verdict-title">Skip for now</h1>`;
  if (basis === "top_prizes") {
    return `${title}
    <p class="verdict-sub">Neither game reaches the ${perDollar(minimum)} minimum back per $1 in big prizes.</p>
    ${barsHtml(top.game, top.per_dollar, top.runner_up_per_dollar, minimum, false)}
    <p class="verdict-foot">The closer one, ${GAMES[top.game].name}, is <strong>${shortBy(minimum - top.per_dollar)}</strong>.</p>`;
  }
  const all = next.recommendation.all_prizes;
  const name = GAMES[all.game].name;
  const bars = barsHtml(all.game, all.per_dollar, all.runner_up_per_dollar, WHOLE_TICKET_MINIMUM, false);
  if (all.per_dollar < WHOLE_TICKET_MINIMUM) {
    return `${title}
    <p class="verdict-sub">Counting all prizes, neither game reaches the ${perDollar(WHOLE_TICKET_MINIMUM)} minimum back per $1.</p>
    ${bars}
    <p class="verdict-foot">The closer one, ${name}, is <strong>${shortBy(WHOLE_TICKET_MINIMUM - all.per_dollar)}</strong>.</p>`;
  }
  return `${title}
    <p class="verdict-sub">Counting all prizes, ${name} reaches the ${perDollar(WHOLE_TICKET_MINIMUM)} minimum back per $1, but the pick goes by big prizes.</p>
    ${bars}
    <p class="verdict-foot">In big prizes the closer one, ${GAMES[top.game].name}, is <strong>${shortBy(minimum - top.per_dollar)}</strong> of the ${perDollar(minimum)} minimum.</p>`;
}

function verdictHtml(next, basis) {
  const rec = next.recommendation?.[basis];
  if (!rec) {
    // Between a draw and the posting of the next jackpot, the source still lists the finished draw.
    const waiting = Object.keys(GAMES).some((g) => next[g] && !next[g].draw_number);
    const message = waiting
      ? "Waiting for the next jackpot to be posted after the last draw. Check back in an hour or two."
      : "Not enough data to compare the games yet.";
    return `<p class="kicker">Recommendation</p><p class="verdict-sub">${message}</p>`;
  }
  if (!next.recommendation.play) return skipHtml(next, basis);
  const best = rec.game;
  const other = otherGame(best);
  const counted = basis === "all_prizes" ? "all prizes" : "big prizes";
  const minimum = basis === "top_prizes" ? minimumToPlay(next) : WHOLE_TICKET_MINIMUM;
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
  if (!value) {
    return `<section class="card game">${head(when)}${jackpot}<p class="note">No sales forecast yet, so no value.</p></section>`;
  }

  const all = basis === "all_prizes";
  const worth = all ? value.per_dollar_all_prizes : value.per_dollar;
  const [low, high] = all ? value.per_dollar_all_prizes_range : value.per_dollar_range;
  const parts = Object.entries(value.parts).filter(([key, v]) => v > 0 && (all || key !== "lower_tiers"));
  const total = parts.reduce((sum, [, v]) => sum + v, 0);
  const shades = [1, 0.7, 0.5, 0.35]; // a game has at most four parts
  const bar = parts
    .map(([, v], i) => `<span style="width:${(100 * v) / total}%;background:var(--${g.css});opacity:${shades[i]}"></span>`)
    .join("");
  const legend = parts
    .map(([key, v], i) => `<li><span><i style="background:var(--${g.css});opacity:${shades[i]}"></i>${esc(PARTS[key])}</span><b>${perDollar(v)}</b></li>`)
    .join("");
  const rangeText = perDollar(low) !== perDollar(high)
    ? `${perDollar(low)}–${perDollar(high)} across the sales forecast`
    : "Barely moves with sales";

  // Odds for one play at the game's own price, and for a full ticket: a ticket's plays carry
  // different numbers (and Gold Ball Draw Numbers), so n plays have n times the chance.
  const odds = value.odds_one_in;
  const price = value.price;
  const plays = MAX_TICKET_PLAYS[game];
  const ticket = `max $${plays * price} ticket`;
  const row = (label, main, detail) => `<li><span>${label}</span><b>${main}</b>${detail ? `<small>${detail}</small>` : ""}</li>`;
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
        ${row("Jackpot odds", oneIn(odds.jackpot), `One $${price} play`)}
        ${row("Jackpot odds", oneIn(odds.jackpot / plays), `A ${ticket} (${plays} plays)`)}
        ${row("$1M or more", oneIn(odds.million_plus), `One $${price} play`)}
        ${row("$1M or more", oneIn(odds.million_plus / plays), `A ${ticket} (${plays} plays)`)}
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
  const start = new Date(dates[dates.length - 1] + "T00:00:00Z"); // the newest draw...
  start.setUTCMonth(start.getUTCMonth() - CHART_MONTHS); // ...and the same day a year earlier
  // ...but not before both games have draws (Lotto Max's are stored from its current game's
  // start), so neither line starts partway along
  const firsts = Object.keys(GAMES).map((game) => draws.filter((d) => d.game === game).map((d) => d.draw_date).sort()[0]);
  const from = [start.toISOString().slice(0, 10), ...firsts].sort().pop();
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
  const readout = document.getElementById(chart.readout);
  readout.textContent = "Tap the chart for a draw's details.";
  const series = chartSeries(draws, next, chart);
  const all = series.flatMap((s) => s.points.concat(s.next ? [s.next] : []));
  // Drawn at the chart's own width, one unit per CSS pixel, so labels keep their size in a
  // narrow column.
  const W = Math.max(150, Math.round(el.clientWidth || 360));
  const H = Math.round(Math.min(240, Math.max(150, W * 0.62)));
  const L = 34, R = 6, T = 8, B = 22;
  const t0 = Math.min(...all.map((p) => p.t));
  const t1 = Math.max(...all.map((p) => p.t));
  const step = 0.1;
  const minimum = chart.minimum ?? minimumToPlay(next);
  const vMax = Math.max(step * 2, Math.ceil((Math.max(minimum, ...all.map((p) => p.v)) * 1.05) / step) * step);
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
  for (let d = new Date(start.getFullYear(), start.getMonth() + 1, 1); d.getTime() <= t1; d.setMonth(d.getMonth() + 1)) {
    if (everyOther && d.getMonth() % 2) continue; // keep January, March, May...
    // January shows the year instead, for a chart that spans two
    const label = d.getMonth() ? d.toLocaleDateString("en-CA", { month: "short" }) : String(d.getFullYear());
    months.push(`<text class="axis" x="${x(d.getTime())}" y="${H - 6}" text-anchor="middle">${label}</text>`);
  }
  // Each game draws twice a week. As the charts reach back toward a year, a phone's narrow
  // columns pack the draws closer: the dots shrink, then are left out once they'd merge into
  // a blob (the line still bends at every draw).
  const drawGap = ((W - L - R) / Math.max(1, (t1 - t0) / 864e5)) * 3.5;
  const dotRadius = drawGap >= 2 ? 2 : drawGap >= 1.3 ? 1.3 : 0;

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
      const dots = dotRadius
        ? s.points.map((p) => `<circle class="${css} ${side(p.v)}" cx="${x(p.t).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${dotRadius}"/>`).join("")
        : "";
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

  const minimumLine = `<line class="minline" x1="${L}" x2="${W - R}" y1="${y(minimum)}" y2="${y(minimum)}"/>`;
  const minimumKey = `<span class="key-min">${perDollar(minimum)} minimum</span>`;
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
    // in words that agree with both figures as shown: $0.3996 is "just below" a $0.40 minimum
    const sameCents = perDollar(best.v) === perDollar(minimum);
    const where = best.v >= minimum ? (sameCents ? "at" : "above") : sameCents ? "just below" : "below";
    readout.textContent = `${readoutText(best, chart)} That's ${where} the ${perDollar(minimum)} minimum.`;
  };
  svg.addEventListener("pointerdown", pick);
  svg.addEventListener("pointermove", (event) => {
    if (event.pointerType === "mouse" || event.buttons) pick(event);
  });
}

function worthText(chart, big, all) {
  if (!chart.allPrizes) return `${perDollar(big)} per $1`;
  const cents = (v) => Math.round(v * 100);
  const smaller = (cents(all) - cents(big)) / 100; // so the shown parts add up to the shown total
  return `${perDollar(all)} per $1 with all prizes (${perDollar(big)} big + ${perDollar(smaller)} smaller)`;
}

// A past draw's day: the charts reach back up to a year, so draws from an earlier year say which.
function pastDayText(isoDate) {
  const year = isoDate.slice(0, 4);
  return year === todayInToronto().slice(0, 4) ? dayText(isoDate) : `${dayText(isoDate)}, ${year}`;
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
    return `${name}, ${pastDayText(d.draw_date)}: ${money(d.jackpot)} jackpot${won}, ${plays}. Worth ${worth}.`;
  }
  const ball = d.gold_ball_drawn === "gold" ? ", gold ball drawn" : "";
  const extra = d.super_draw ? ", Super Draw" : "";
  return `${name}, ${pastDayText(d.draw_date)}: ${money(d.gold_ball_amount)} Gold Ball with ${d.balls_remaining} balls${ball}${extra}, ${plays}. Worth ${worth}.`;
}

// ---------- draw simulator ----------

// One ticket against the upcoming draw, drawn as ILC's game conditions describe: Lotto Max's
// main draw, then one MAXPLUS series per $1M of jackpot, then the MAXMILLIONS series; 6/49's
// Classic draw, then one Gold Ball number from all those sold, then one prize ball. ILC has
// drawn with a random number generator since May 2019; this uses the device's cryptographic
// one (never Math.random), each number drawn from those left, all equally likely.
const SIM = {
  lottomax: { price: 6, lines: 4, pick: 7, highest: 52, minHits: 3, plus: [3, 4, 5, 6], fixed: { "4/7": 20, "3/7+B": 20 }, top: "7/7", free: "3/7" },
  lotto649: { price: 3, lines: 1, pick: 6, highest: 49, minHits: 2, plus: [2, 5], fixed: { "3/6": 10, "2/6+B": 5 }, top: "6/6", free: "2/6" },
};
const SIM_KEY = "lotto-calculator.sim";

// A whole number from 0 to n - 1, each equally likely: values from the top of the 32-bit
// range, which would favour the small numbers, are thrown away and drawn again. The generator
// fills 1,024 random words per call, as one call per number made a $30 ticket 4x slower.
const randomWords = new Uint32Array(1024);
let wordsUsed = randomWords.length;
function randomInt(n) {
  const limit = 2 ** 32 - (2 ** 32 % n);
  let word;
  do {
    if (wordsUsed === randomWords.length) {
      crypto.getRandomValues(randomWords);
      wordsUsed = 0;
    }
    word = randomWords[wordsUsed++];
  } while (word >= limit);
  return word % n;
}

// `count` different numbers from 1 to `highest`, in the order drawn.
function drawNumbers(count, highest) {
  const left = Array.from({ length: highest }, (_, i) => i + 1);
  return Array.from({ length: count }, () => left.splice(randomInt(left.length), 1)[0]);
}

const sorted = (numbers) => [...numbers].sort((a, b) => a - b);
const quickPick = (g) => sorted(drawNumbers(g.pick, g.highest));
const cash = (n) => (n >= 1e4 ? money(n) : "$" + (Number.isInteger(n) ? n.toLocaleString("en-CA") : n.toFixed(2)));

// A ticket is your own sets of numbers, one per play, then any Quick Pick plays, up to $30.
// `editing` is the set whose numbers are being picked, if any.
const sim = {
  game: "lottomax",
  sets: { lottomax: [quickPick(SIM.lottomax)], lotto649: [quickPick(SIM.lotto649)] },
  quick: { lottomax: 0, lotto649: 0 },
  editing: { lottomax: null, lotto649: null },
};
try {
  sim.tally = JSON.parse(localStorage.getItem(SIM_KEY)) || {};
} catch {
  sim.tally = {};
}

function prize(game, key, info) {
  const g = SIM[game];
  const label = key.replace("+B", " + bonus");
  if (key === g.top) return { label, amount: game === "lottomax" ? info.jackpot : 5e6, note: "win or share" };
  if (key === g.free) return { label, amount: g.price, free: true };
  if (g.fixed[key]) return { label, amount: g.fixed[key] };
  // a shared pool: what the last real draw paid in it
  return { label, amount: state.draws.findLast((d) => d.game === game && d.tier_prizes[key] != null).tier_prizes[key], note: "as the last draw paid" };
}

function playTicket(game) {
  const g = SIM[game];
  const info = state.next[game];
  const own = sim.sets[game];
  const plays = own.length + sim.quick[game];
  // each play's first line is one of your sets or a Quick Pick; Lotto Max adds 3 Quick Pick
  // lines to every play, as on a real ticket
  const lines = Array.from({ length: plays }, (_, p) => [own[p] ?? quickPick(g), ...Array.from({ length: g.lines - 1 }, () => quickPick(g))]).flat();
  const drawn = drawNumbers(g.pick + 1, g.highest); // the main numbers, then the bonus
  const r = { game, plays, lines, drawn, main: drawn.slice(0, g.pick), bonus: drawn[g.pick] };
  r.lineWins = lines.map((line) => {
    const hits = line.filter((n) => r.main.includes(n)).length;
    return hits < g.minHits ? null : prize(game, `${hits}/${g.pick}${g.plus.includes(hits) && line.includes(r.bonus) ? "+B" : ""}`, info);
  });
  r.wins = r.lineWins.filter(Boolean);
  if (game === "lottomax") {
    // each MAXPLUS and MAXMILLIONS series wins on an exact match with one of your lines
    const mine = new Set(lines.map((line) => line.join()));
    const series = (count, amount, label) => {
      for (let i = 0; i < count; i++) if (mine.has(quickPick(g).join())) r.wins.push({ label, amount, note: "win or share" });
    };
    series(info.maxplus_count, info.maxplus_prize, "MAXPLUS");
    series(info.maxmillions_count, 1e6, "MAXMILLIONS");
  } else {
    // one Gold Ball number from all those sold (the forecast's count), of which `plays` are yours
    const issued = info.forecast?.plays ?? state.draws.findLast((d) => d.game === game).est_plays;
    r.goldBall = randomInt(issued) < plays;
    r.gold = randomInt(info.balls_remaining) === 0;
    if (r.goldBall) r.wins.push(r.gold ? { label: "Gold Ball jackpot", amount: info.gold_ball_amount } : { label: "Gold Ball draw", amount: 1e6 });
  }
  return r;
}

const prizeAmount = (w) => (w.free ? "Free Play" : cash(w.amount));

// "You won $20 and a Free Play"
function wonText(wins) {
  const total = wins.reduce((sum, w) => sum + (w.free ? 0 : w.amount), 0);
  const free = wins.filter((w) => w.free).length;
  const parts = [total && cash(total), free && (free > 1 ? `${free} Free Plays` : "a Free Play")].filter(Boolean);
  return parts.length ? `You won ${parts.join(" and ")}` : "No prize this time";
}

// "2 × 3/7: Free Play · 4/7: $20"
function prizesText(wins) {
  const counts = new Map();
  for (const w of wins) {
    const text = `${w.label}: ${prizeAmount(w)}${w.note ? ` (${w.note})` : ""}`;
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  return [...counts].map(([text, n]) => (n > 1 ? `${n} × ${text}` : text)).join(" · ");
}

function simTicketHtml() {
  const g = SIM[sim.game];
  const sets = sim.sets[sim.game];
  const editing = sim.editing[sim.game];
  if (editing !== null) {
    const set = sets[editing];
    const done = set.length === g.pick; // the rest of the grid is then disabled
    const grid = Array.from({ length: g.highest }, (_, i) => {
      const on = set.includes(i + 1);
      return `<button type="button" data-num="${i + 1}" aria-pressed="${on}"${done && !on ? " disabled" : ""}>${i + 1}</button>`;
    });
    return `
      <p class="kicker">Pick ${g.pick} numbers · ${set.length} picked</p>
      <div class="sim-grid">${grid.join("")}</div>
      <div class="sim-actions">
        <button type="button" data-act="done" class="primary"${done ? "" : " disabled"}>Done</button>
        <button type="button" data-act="fill">Quick Pick this set</button>
      </div>`;
  }
  const quick = sim.quick[sim.game];
  const plays = sets.length + quick;
  const full = plays === MAX_TICKET_PLAYS[sim.game];
  const stepper = (label, count, kind) => `
    <div class="sim-size">
      <span>${label}</span>
      <button type="button" data-act="less" data-kind="${kind}" aria-label="${label}: one fewer"${count === 0 || plays === 1 ? " disabled" : ""}>−</button>
      <b>${count}</b>
      <button type="button" data-act="add" data-kind="${kind}" aria-label="${label}: one more"${full ? " disabled" : ""}>+</button>
    </div>`;
  const rows = sets.map((set, i) => `
    <div class="sim-set"><span class="sim-nums">${set.map((n) => `<span>${n}</span>`).join("")}</span><button type="button" data-act="change" data-set="${i}">Change</button></div>`);
  return `
    <p class="kicker">Your ticket · $${g.price * plays}</p>
    ${stepper("Your numbers", sets.length, "own")}
    ${stepper("Quick Picks", quick, "quick")}
    ${rows.join("")}
    ${sim.game === "lottomax" ? `<p class="caption">Each play also comes with 3 Quick Pick lines.</p>` : ""}
    <div class="sim-actions">
      <button type="button" data-act="draw" class="primary">Draw</button>
      <button type="button" data-act="draw100">Play 100 draws</button>
    </div>`;
}

function simResultHtml(r) {
  const g = SIM[r.game];
  const info = state.next[r.game]; // the draw just played
  const drawn = r.drawn.map((n, i) => `<span class="ball drawn${i === g.pick ? " bonus" : ""}" style="--i:${i}">${n}</span>`).join("");
  const mark = (n) => `<span class="ball ${r.main.includes(n) ? "hit" : n === r.bonus ? "bonus" : ""}">${n}</span>`;
  const lines = r.lines.map((line, i) => {
    const play = r.game === "lottomax" && r.plays > 1 && i % g.lines === 0 ? `<p class="sim-play">Play ${i / g.lines + 1}</p>` : "";
    const won = r.lineWins[i];
    return `${play}<div class="sim-line"><span class="balls small">${line.map(mark).join("")}</span>${won ? `<b>${won.label} · ${prizeAmount(won)}</b>` : ""}</div>`;
  });
  const ball = r.gold ? `the gold ball (the ${money(info.gold_ball_amount)} jackpot)` : "a $1M white ball";
  // MAXPLUS always has a series per $1M of jackpot; MAXMILLIONS only from $50M
  const extra = r.game === "lottomax"
    ? `${info.maxplus_count} MAXPLUS${info.maxmillions_count ? ` and ${info.maxmillions_count} MAXMILLIONS` : ""} sets drawn too: ${
        r.wins.some((w) => w.label.startsWith("MAX")) ? "you matched one!" : "no match."}`
    : r.goldBall ? `Gold Ball draw: your number came up, with ${ball}!` : `Gold Ball draw: ${r.plays > 1 ? "none of your numbers" : "not your number"}; ${ball} went to another ticket.`;
  return `
    <div class="sim-draw" data-act="skip">
      <div class="balls">${drawn}</div>
      <div class="sim-after" style="--i:${r.drawn.length}">
        <p class="sim-won">${wonText(r.wins)}</p>
        ${r.wins.length ? `<p class="caption">${prizesText(r.wins)}</p>` : ""}
        <p class="sim-numbers">${extra}</p>
        <details${r.lines.length <= 4 ? " open" : ""}><summary>Your ${r.lines.length > 1 ? `${r.lines.length} lines` : "line"}</summary>
          <div class="sim-lines">${lines.join("")}</div></details>
      </div>
    </div>`;
}

function simSummaryHtml(results) {
  const wins = results.flatMap((r) => r.wins);
  const won = wins.reduce((sum, w) => sum + w.amount, 0);
  const ticket = SIM[sim.game].price * results[0].plays;
  const spent = results.length * ticket;
  const best = wins.reduce((top, w) => (top && top.amount >= w.amount ? top : w), null);
  return `
    <p class="sim-won">${cash(spent)} spent, ${cash(won)} back</p>
    <p class="caption">${results.length} draws of this $${ticket} ticket: ${perDollar(won / spent)} back per $1${best ? `. Best prize: ${best.label}, ${prizeAmount(best)}` : ""}.</p>`;
}

function renderSim() {
  const t = sim.tally[sim.game];
  document.getElementById("sim-ticket").innerHTML = simTicketHtml();
  document.getElementById("sim-tally").innerHTML = t
    ? `So far: ${t.tickets.toLocaleString("en-CA")} ticket${t.tickets === 1 ? "" : "s"}, ${cash(t.spent)} spent, ${cash(t.won)} won <button type="button" data-act="reset">Reset</button>`
    : "";
}

function saveTally() {
  try {
    localStorage.setItem(SIM_KEY, JSON.stringify(sim.tally));
  } catch {
    // private browsing: the tally just isn't remembered
  }
}

document.getElementById("sim").addEventListener("click", (event) => {
  const el = event.target.closest("[data-game], [data-num], [data-act]");
  if (!el) return;
  const g = SIM[sim.game];
  const result = document.getElementById("sim-result");
  const act = el.dataset.act;
  if (act === "skip") return el.classList.add("skip");
  const sets = sim.sets[sim.game];
  if (el.dataset.game) {
    sim.game = el.dataset.game; // each game keeps its own ticket, mid-pick included
    // the game's colours and the switch only change here; index.html starts on Lotto Max
    document.getElementById("sim").className = `card sim ${GAMES[sim.game].css}`;
    for (const button of document.querySelectorAll("#sim [data-game]")) button.setAttribute("aria-pressed", String(button === el));
    result.innerHTML = "";
  } else if (el.dataset.num) {
    const n = Number(el.dataset.num);
    const i = sim.editing[sim.game];
    sets[i] = sets[i].includes(n) ? sets[i].filter((x) => x !== n) : sorted([...sets[i], n]);
  } else if (act === "add") {
    // the + buttons are disabled at $30, the − ones at none left or the last play
    if (el.dataset.kind === "own") sim.editing[sim.game] = sets.push([]) - 1; // then pick its numbers
    else sim.quick[sim.game]++;
  } else if (act === "less") {
    if (el.dataset.kind === "own") sets.pop();
    else sim.quick[sim.game]--;
  } else if (act === "change") {
    sim.editing[sim.game] = Number(el.dataset.set);
  } else if (act === "done" || act === "fill") {
    if (act === "fill") sets[sim.editing[sim.game]] = quickPick(g);
    sim.editing[sim.game] = null;
  } else if (act === "reset") {
    delete sim.tally[sim.game];
    saveTally();
  } else if (!state.next?.[sim.game]) {
    result.innerHTML = `<p class="caption">The next draw hasn't loaded yet. Try again in a moment.</p>`;
  } else {
    const results = Array.from({ length: act === "draw" ? 1 : 100 }, () => playTicket(sim.game));
    const t = (sim.tally[sim.game] ??= { tickets: 0, spent: 0, won: 0 });
    t.tickets += results.length;
    t.spent += results.length * g.price * results[0].plays;
    t.won += results.flatMap((r) => r.wins).reduce((sum, w) => sum + w.amount, 0);
    saveTally();
    result.innerHTML = act === "draw" ? simResultHtml(results[0]) : simSummaryHtml(results);
  }
  renderSim();
});
renderSim();

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
  const health = next.errors.length ? "error" : hoursOld > STALE_HOURS ? "stale" : "ok";
  setStatus(`Updated ${agoText(next.scraped_at)}`, health);
}

function render() {
  const { next, basis } = state;
  showUpdated(next);
  document.getElementById("notices").innerHTML = noticesHtml(next);
  document.getElementById("verdict").innerHTML = verdictHtml(next, basis);
  const rec = next.recommendation?.[basis];
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
    if (withCharts) drawCharts();
  } catch (error) {
    console.error(error);
    showProblem(`Something went wrong showing the numbers (${error.message}). Tap the status button at the top to try again.`);
  }
}

let chartWidth = 0; // the width the charts were last drawn at

function drawCharts() {
  for (const chart of CHARTS) renderChart(chart, state.draws, state.next);
  chartWidth = document.getElementById("chart").clientWidth;
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
// Only width counts: iOS also fires resize when Safari's toolbar hides on scroll.
let resizeTimer = 0;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.next && document.getElementById("chart").clientWidth !== chartWidth) drawCharts();
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
document.getElementById("whole-minimum").textContent = perDollar(WHOLE_TICKET_MINIMUM); // in the whole-ticket chart's caption
load();
