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

function skipHtml(next) {
  const top = next.recommendation.top_prizes; // the minimum is judged on big prizes
  const best = top.game;
  const minimum = minimumToPlay(next);
  return `
    <p class="kicker">Recommendation</p>
    <h1 class="verdict-title">Skip for now</h1>
    <p class="verdict-sub">Neither game reaches the ${perDollar(minimum)} minimum back per $1 in big prizes.</p>
    ${barsHtml(best, top.per_dollar, top.runner_up_per_dollar, minimum, false)}
    <p class="verdict-foot">The closer one, ${GAMES[best].name}, is <strong>${shortBy(minimum - top.per_dollar)}</strong>.</p>`;
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
  if (!next.recommendation.play) return skipHtml(next);
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
// range, which would favour the small numbers, are thrown away and drawn again.
function randomInt(n) {
  const limit = 2 ** 32 - (2 ** 32 % n);
  const value = new Uint32Array(1);
  do crypto.getRandomValues(value);
  while (value[0] >= limit);
  return value[0] % n;
}

// `count` different numbers from 1 to `highest`, in the order drawn.
function drawNumbers(count, highest) {
  const left = Array.from({ length: highest }, (_, i) => i + 1);
  return Array.from({ length: count }, () => left.splice(randomInt(left.length), 1)[0]);
}

const sorted = (numbers) => [...numbers].sort((a, b) => a - b);
const quickPick = (g) => sorted(drawNumbers(g.pick, g.highest));
const goldNumber = () => `${String(randomInt(1e8)).padStart(8, "0")}-${String(randomInt(100)).padStart(2, "0")}`;
const cash = (n) => (n >= 1e4 ? money(n) : "$" + (Number.isInteger(n) ? n.toLocaleString("en-CA") : n.toFixed(2)));

const sim = { game: "lottomax", picking: false, plays: { lottomax: 1, lotto649: 1 }, picks: { lottomax: quickPick(SIM.lottomax), lotto649: quickPick(SIM.lotto649) } };
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
  return { label, amount: state.draws.filter((d) => d.game === game && d.tier_prizes[key] != null).at(-1).tier_prizes[key], note: "as the last draw paid" };
}

function playTicket(game) {
  const g = SIM[game];
  const info = state.next[game];
  const plays = sim.plays[game];
  // your numbers are the first line; every other line on the ticket is a Quick Pick
  const lines = [sim.picks[game], ...Array.from({ length: g.lines * plays - 1 }, () => quickPick(g))];
  const drawn = drawNumbers(g.pick + 1, g.highest); // the main numbers, then the bonus
  const r = { game, plays, lines, drawn, main: drawn.slice(0, g.pick), bonus: drawn[g.pick] };
  r.lineWins = lines.map((line) => {
    const hits = line.filter((n) => r.main.includes(n)).length;
    return hits < g.minHits ? null : prize(game, `${hits}/${g.pick}${g.plus.includes(hits) && line.includes(r.bonus) ? "+B" : ""}`, info);
  });
  r.wins = r.lineWins.filter(Boolean);
  if (game === "lottomax") {
    const mine = new Set(lines.map((line) => line.join()));
    const series = (count, amount, label) =>
      Array.from({ length: count }, () => {
        const set = quickPick(g);
        if (mine.has(set.join())) r.wins.push({ label, amount, note: "win or share" });
        return set;
      });
    r.maxplus = series(info.maxplus_count, info.maxplus_prize, "MAXPLUS");
    r.maxmillions = series(info.maxmillions_count, 1e6, "MAXMILLIONS");
  } else {
    // the numbers sold, which only the forecast knows before the draw
    r.issued = info.forecast?.plays ?? state.draws.filter((d) => d.game === game).at(-1).est_plays;
    r.yours = Array.from({ length: plays }, goldNumber); // one per play
    const pick = randomInt(r.issued); // yours are `plays` of the numbers sold
    r.winning = r.yours[pick] ?? goldNumber();
    r.balls = info.balls_remaining;
    r.gold = randomInt(r.balls) === 0;
    if (pick < plays) r.wins.push(r.gold ? { label: "Gold Ball jackpot", amount: info.gold_ball_amount } : { label: "Gold Ball draw", amount: 1e6 });
  }
  return r;
}

const ballHtml = (n, cls = "") => `<span class="ball ${cls}">${n}</span>`;
const prizeAmount = (w) => (w.free ? "Free Play" : cash(w.amount));

// "2 × 3/7: Free Play; 4/7: $20", with the total when there's more than one prize
function prizesText(wins) {
  const counts = new Map();
  for (const w of wins) {
    const text = `${w.label}: ${prizeAmount(w)}${w.note ? ` (${w.note})` : ""}`;
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  const list = [...counts].map(([text, n]) => (n > 1 ? `${n} × ${text}` : text)).join("; ");
  return wins.length > 1 ? `${list}. ${cash(wins.reduce((sum, w) => sum + w.amount, 0))} in all` : list;
}

function simTicketHtml() {
  const g = SIM[sim.game];
  const line = sim.picks[sim.game];
  const plays = sim.plays[sim.game];
  if (sim.picking) {
    const grid = Array.from({ length: g.highest }, (_, i) => `<button type="button" data-num="${i + 1}" aria-pressed="${line.includes(i + 1)}">${i + 1}</button>`);
    return `
      <p class="kicker">Pick ${g.pick} numbers · ${line.length} of ${g.pick}</p>
      <div class="sim-grid">${grid.join("")}</div>
      <div class="sim-actions"><button type="button" data-act="quick">Quick Pick instead</button></div>`;
  }
  const others = g.lines * plays - 1;
  const quick = others ? `${others} Quick Pick line${others > 1 ? "s" : ""}` : "";
  const gold = sim.game === "lotto649" ? (plays > 1 ? `${plays} Gold Ball numbers, one per play` : "a Gold Ball number") : "";
  const extra = `Your numbers, plus ${[quick, gold].filter(Boolean).join(" and ")}, new with each ticket.`;
  return `
    <p class="kicker">Your ticket</p>
    <div class="sim-size">
      <button type="button" data-act="fewer" aria-label="One play fewer"${plays === 1 ? " disabled" : ""}>−</button>
      <span>${plays} play${plays > 1 ? "s" : ""} · $${g.price * plays}</span>
      <button type="button" data-act="more" aria-label="One play more"${plays === MAX_TICKET_PLAYS[sim.game] ? " disabled" : ""}>+</button>
    </div>
    <div class="balls">${line.map((n) => ballHtml(n)).join("")}</div>
    <p class="caption">${extra}</p>
    <div class="sim-actions">
      <button type="button" data-act="draw" class="primary">Draw</button>
      <button type="button" data-act="pick">Pick numbers</button>
      <button type="button" data-act="quick">Quick Pick</button>
      <button type="button" data-act="draw100">Play 100 draws</button>
    </div>`;
}

function simResultHtml(r) {
  const g = SIM[r.game];
  const drawn = r.drawn.map((n, i) => `<span class="ball drawn${i === g.pick ? " bonus" : ""}" style="--i:${i}">${n}</span>`).join("");
  const mark = (n) => ballHtml(n, r.main.includes(n) ? "hit" : n === r.bonus ? "bonus" : "");
  const lines = r.lines.map((line, i) => {
    const play = r.game === "lottomax" && r.plays > 1 && i % g.lines === 0 ? `<p class="sim-play">Play ${i / g.lines + 1}</p>` : "";
    const won = r.lineWins[i];
    return `${play}<div class="sim-line"><span class="balls small">${line.map(mark).join("")}</span>${won ? `<b>${won.label} · ${prizeAmount(won)}</b>` : ""}</div>`;
  });
  const series = (label, sets, each) => {
    const hit = r.wins.some((w) => w.label === label);
    return `<details><summary>${label}: ${sets.length} sets of 7 drawn, ${money(each)} each for an exact match: ${hit ? "you matched one!" : "no match"}</summary>
      <div class="sim-sets">${sets.map((s) => `<span>${s.join(" ")}</span>`).join("")}</div></details>`;
  };
  const extras = r.game === "lottomax"
    ? series("MAXPLUS", r.maxplus, state.next.lottomax.maxplus_prize) + series("MAXMILLIONS", r.maxmillions, 1e6)
    : `<p class="sim-numbers">Gold Ball draw: ${r.winning} drawn from about ${r.issued.toLocaleString("en-CA")} numbers sold; yours ${r.plays > 1 ? "were" : "was"} ${r.yours.join(", ")}.</p>
       <p class="sim-numbers">Prize ball: ${r.gold ? `the gold ball, worth the ${money(state.next.lotto649.gold_ball_amount)} jackpot` : "a $1M ball"}, drawn from ${r.balls}.</p>`;
  const won = r.wins.length ? `You won ${prizesText(r.wins)}.` : "No prize this time.";
  return `
    <div class="sim-draw" data-act="skip">
      <p class="kicker">${r.game === "lottomax" ? "Main draw" : "Classic draw"} · tap to show all</p>
      <div class="balls">${drawn}</div>
      <div class="sim-after" style="--i:${r.drawn.length}">
        <p class="sim-numbers">Winning numbers ${sorted(r.main).join(", ")}, bonus ${r.bonus}</p>
        <p class="kicker">Your lines</p>
        <div class="sim-lines">${lines.join("")}</div>
        ${extras}
        <p class="sim-won">${won}</p>
      </div>
    </div>`;
}

function simSummaryHtml(results) {
  const wins = results.flatMap((r) => r.wins);
  const won = wins.reduce((sum, w) => sum + w.amount, 0);
  const ticket = SIM[sim.game].price * sim.plays[sim.game];
  const spent = results.length * ticket;
  return `
    <p class="kicker">${results.length} draws · a $${ticket} ticket each</p>
    <p class="sim-won">${cash(spent)} spent, ${cash(won)} won back: ${perDollar(won / spent)} per $1.</p>
    <p class="caption">Prizes: ${wins.length ? prizesText(wins) : "none"}. A Free Play counts as one play's price.</p>`;
}

function renderSim() {
  const t = sim.tally[sim.game];
  document.getElementById("sim").className = `card sim ${GAMES[sim.game].css}`;
  for (const button of document.querySelectorAll("#sim [data-game]")) button.setAttribute("aria-pressed", String(button.dataset.game === sim.game));
  document.getElementById("sim-ticket").innerHTML = simTicketHtml();
  document.getElementById("sim-tally").innerHTML = t
    ? `${t.tickets.toLocaleString("en-CA")} ticket${t.tickets === 1 ? "" : "s"} · ${cash(t.spent)} spent · ${cash(t.won)} won · net ${t.won < t.spent ? "−" : "+"}${cash(Math.abs(t.won - t.spent))} <button type="button" data-act="reset">Reset</button>`
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
  if (el.dataset.game) {
    Object.assign(sim, { game: el.dataset.game, picking: false });
    result.innerHTML = "";
  } else if (el.dataset.num) {
    const n = Number(el.dataset.num);
    const line = sim.picks[sim.game];
    sim.picks[sim.game] = line.includes(n) ? line.filter((x) => x !== n) : sorted([...line, n]);
    sim.picking = sim.picks[sim.game].length < g.pick;
  } else if (act === "fewer" || act === "more") {
    sim.plays[sim.game] += act === "more" ? 1 : -1; // the buttons are disabled at 1 play and at $30
  } else if (act === "pick" || act === "quick") {
    sim.picks[sim.game] = act === "pick" ? [] : quickPick(g);
    sim.picking = act === "pick";
  } else if (act === "reset") {
    delete sim.tally[sim.game];
    saveTally();
  } else if (!state.next?.[sim.game]) {
    result.innerHTML = `<p class="caption">The next draw hasn't loaded yet. Try again in a moment.</p>`;
  } else {
    const results = Array.from({ length: act === "draw" ? 1 : 100 }, () => playTicket(sim.game));
    const t = (sim.tally[sim.game] ??= { tickets: 0, spent: 0, won: 0 });
    t.tickets += results.length;
    t.spent += results.length * g.price * sim.plays[sim.game];
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
