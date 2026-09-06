// gridcast. Fetches JSON written by scripts/score.py and scripts/predict.py
// and renders it. No maths here beyond formatting: every score on this site
// was computed in Python and committed.
//
// Four pages share this file. `document.body.dataset.page` picks which
// renderer runs, so each page only fetches what it needs.

const REPO_URL = "https://github.com/nitrimandylis/gridcast";

// Team palette from apex (lib/colors.ts), keyed by FastF1 team name. These are
// each constructor's own colours, so they are data, not design tokens.
const TEAM_COLORS = {
  "Mercedes": "#00D2BE", "Ferrari": "#E8002D", "McLaren": "#FF8000",
  "Red Bull Racing": "#3671C6", "Alpine": "#0090FF", "Racing Bulls": "#6692FF",
  "Haas F1 Team": "#B6BABD", "Williams": "#64C4FF", "Audi": "#F50537",
  "Aston Martin": "#229971", "Cadillac": "#C5A253",
};
const MODEL_LABEL = { direct: "Direct · Plackett-Luce", sim: "Sim · Monte Carlo" };
// FastF1 location names that differ from the keys in circuits.json (apex's outlines).
const CIRCUIT_ALIAS = { "Montréal": "Montreal", "Spa-Francorchamps": "Spa", "Yas Island": "Abu Dhabi",
  "Yas Marina": "Abu Dhabi", "Singapore": "Marina Bay", "Monaco": "Monte Carlo", "Sakhir": "Bahrain" };
const METRICS = { p_win: "win", p_podium: "podium", p_points: "points" };

function modelKey(name) { return name.startsWith("sim") ? "sim" : "direct"; }
function teamColor(team) { return TEAM_COLORS[team] || "#B6BABD"; }
function pct(p) { return p < 0.005 ? "<1%" : p < 0.095 ? (p * 100).toFixed(1) + "%" : Math.round(p * 100) + "%"; }
function rps(x) { return x == null ? "–" : x.toFixed(4); }
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function when(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

async function getJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// The latest call is the highest round, and within it Saturday beats Thursday.
function latestCall(manifest) {
  const order = { thursday: 0, saturday: 1 };
  let best = null;
  for (const m of manifest) {
    if (!best || m.round > best.round || (m.round === best.round && order[m.call] > order[best.call])) best = m;
  }
  return best ? manifest.filter(m => m.round === best.round && m.call === best.call) : [];
}

// Both the home page and the probabilities page need the same bundle.
async function loadCall(withCircuits) {
  const [manifest, circuits] = await Promise.all([
    getJSON("manifest.json"),
    withCircuits ? getJSON("circuits.json").catch(() => ({})) : Promise.resolve({}),
  ]);
  const entries = latestCall(manifest);
  const preds = {};
  await Promise.all(entries.map(async e => { preds[modelKey(e.model)] = await getJSON(`predictions/${e.file}`); }));
  return { entries, preds, circuits };
}

// ---- shared fragments ------------------------------------------------------

// One lap of real car position data, fitted into a 100x100 box (apex's TrackMap).
function circuitSvg(points) {
  if (!points) return "";
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 8, scale = (100 - 2 * pad) / Math.max(maxX - minX, maxY - minY);
  const ox = (100 - (maxX - minX) * scale) / 2, oy = (100 - (maxY - minY) * scale) / 2;
  const d = points.map(([x, y], i) =>
    `${i ? "L" : "M"}${(ox + (x - minX) * scale).toFixed(1)},${(100 - (oy + (y - minY) * scale)).toFixed(1)}`).join(" ") + " Z";
  return `<svg class="circuit" viewBox="0 0 100 100" aria-hidden="true"><path class="glow" d="${d}"/><path d="${d}"/></svg>`;
}

function countdown(iso) {
  const target = new Date(iso).getTime();
  const unit = (v, l) => `<div class="unit"><div class="v">${String(v).padStart(2, "0")}</div><div class="l">${l}</div></div>`;
  return () => {
    let left = Math.floor((target - Date.now()) / 1000);
    if (left <= 0) return `<p class="done">Lights out has passed. The result is scored the evening after the race.</p>`;
    const d = Math.floor(left / 86400); left -= d * 86400;
    const h = Math.floor(left / 3600); left -= h * 3600;
    const m = Math.floor(left / 60), s = left - m * 60;
    return unit(d, "days") + unit(h, "hrs") + unit(m, "min") + unit(s, "sec");
  };
}

function startClock(iso) {
  const clock = document.getElementById("clock");
  if (!clock || !iso) return;
  const tick = countdown(iso);
  clock.innerHTML = tick();
  setInterval(() => { clock.innerHTML = tick(); }, 1000);
}

function stamp(entry) {
  if (!entry) return "";
  const key = modelKey(entry.model);
  if (!entry.commit) return `<li><b>${key}</b> <span class="bad">not yet committed</span></li>`;
  const short = entry.commit.slice(0, 7);
  const link = REPO_URL ? `<a href="${REPO_URL}/commit/${entry.commit}"><code>${short}</code></a>` : `<code>${short}</code>`;
  return `<li><b>${key}</b> committed ${when(entry.committed_at)} · ${link}</li>`;
}

function entryHead(any, circuits) {
  const outline = circuitSvg(circuits[CIRCUIT_ALIAS[any.circuit] || any.circuit]);
  const at = any.race_start ? new Date(any.race_start).toLocaleString("en-GB",
    { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "";
  const trained = any.trained_on_rounds;
  // The title leads. Putting the outline in a left column ahead of the heading
  // is the tag-left/heading-right silhouette, so it sits at the far end instead.
  return `<div class="entry-head">
    <div>
      <h2 class="entry-title">${esc(any.event)}</h2>
      <p class="entry-sub">${esc(any.circuit)}${at ? " · lights out " + at : ""} · both models trained on rounds ${trained[0]}–${trained[trained.length - 1]}</p>
    </div>
    <div class="clock" id="clock" aria-hidden="true"></div>
    ${outline || "<span></span>"}
  </div>`;
}

// ---- home ------------------------------------------------------------------

// Top five by combined P(win), so the home page shows who both models like
// without repeating the whole matrix.
function leaders(preds) {
  const both = preds.direct && preds.sim;
  const rows = (preds.direct || preds.sim).drivers.map(d => d.driver);
  const get = (key, code) => preds[key]?.drivers.find(x => x.driver === code);
  const score = code => (get("direct", code)?.p_win ?? 0) + (get("sim", code)?.p_win ?? 0);
  const top = [...rows].sort((a, b) => score(b) - score(a)).slice(0, 5);
  let h = `<table><caption>Probability of winning. The full matrix, and podium and points, are on the probabilities page.</caption>
    <thead><tr><th>Driver</th>${both ? "<th>Direct</th><th>Sim</th>" : "<th>P(win)</th>"}</tr></thead><tbody>`;
  for (const code of top) {
    const d = get("direct", code), s = get("sim", code);
    const team = (d || s).team;
    h += `<tr><td><i class="stripe" style="--team:${teamColor(team)}"></i>${esc(code)}</td>`;
    h += both ? `<td>${pct(d.p_win)}</td><td>${pct(s.p_win)}</td>` : `<td>${pct((d || s).p_win)}</td>`;
    h += `</tr>`;
  }
  return h + `</tbody></table>`;
}

// One line per call: who is ahead so far, and by how much. No number is
// invented — with nothing scored, the slot says so.
function tally(summary) {
  if (!summary.length) {
    return `<p class="empty">No race scored yet. The record opens the evening after the next Grand Prix.</p>`;
  }
  let h = `<div class="tally">`;
  for (const call of ["thursday", "saturday"]) {
    const rows = summary.filter(s => s.call === call);
    if (!rows.length) continue;
    const by = Object.fromEntries(rows.map(s => [modelKey(s.model), s]));
    const base = rows[0].baseline_rps;
    const best = Math.min(...rows.map(s => s.rps));
    for (const key of ["direct", "sim"]) {
      if (!by[key]) continue;
      const cls = by[key].rps > base ? "bad" : by[key].rps === best ? "win" : "";
      h += `<div><span class="n ${cls}">${rps(by[key].rps)}</span><span class="k">${key}, ${call}, ${by[key].n} race${by[key].n === 1 ? "" : "s"}</span></div>`;
    }
    h += `<div><span class="n">${rps(base)}</span><span class="k">baseline, ${call}</span></div>`;
  }
  return h + `</div>`;
}

// The fold's card. Stacked, not spread: it sits in a half-width column beside
// the headline, and it carries the commit stamps because "committed before
// lights out" is the claim the headline is making.
function callCard(any, circuits, entries) {
  const outline = circuitSvg(circuits[CIRCUIT_ALIAS[any.circuit] || any.circuit]);
  const at = any.race_start ? new Date(any.race_start).toLocaleString("en-GB",
    { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "";
  return `<div class="call">
    <p class="strap"><span class="accent">Next up</span><span>Round ${any.round}</span><span>${esc(any.call)} call</span></p>
    <div class="call-body">
      <div>
        <h2 class="entry-title">${esc(any.event)}</h2>
        <p class="entry-sub">${esc(any.circuit)}${at ? " · lights out " + at : ""}</p>
      </div>
      ${outline}
    </div>
    <div class="clock" id="clock" aria-hidden="true"></div>
    <ul class="stamps">${entries.map(stamp).join("")}</ul>
  </div>`;
}

async function renderHome() {
  const fold = document.getElementById("next");
  const board = document.getElementById("board");
  const [{ entries, preds, circuits }, scores] = await Promise.all([loadCall(true), getJSON("results.json")]);
  if (!entries.length) {
    fold.innerHTML = `<p class="empty">No prediction committed yet. The first call lands the Thursday before the next Grand Prix.</p>`;
    board.innerHTML = "";
    return;
  }
  const any = preds.direct || preds.sim;
  const byKey = Object.fromEntries(entries.map(e => [modelKey(e.model), e]));
  fold.innerHTML = callCard(any, circuits, [byKey.direct, byKey.sim].filter(Boolean));
  board.innerHTML = `<div class="board">
    <div class="board-main">
      <h2 class="sec-h">Who both models like · trained on rounds ${any.trained_on_rounds[0]}–${any.trained_on_rounds[any.trained_on_rounds.length - 1]}</h2>
      <div class="leaders">${leaders(preds)}</div>
      <a class="more" href="probabilities.html">Full probability matrices &rarr;</a>
    </div>
    <aside class="board-side">
      <h2 class="sec-h">The record so far</h2>
      ${tally(scores.summary)}
      <a class="more" href="record.html">Every race scored &rarr;</a>
    </aside>
  </div>`;
  startClock(any.race_start);
}

// ---- predicted order (starting-grid formation) ----------------------------

// Combined order: average the two models' p_position arrays per driver, then
// sort by expected finishing position (sum of j * p_j). This is the JS
// equivalent of the Hungarian assignment Python does per model, close enough
// for display and needs no external dependency.
function combinedOrder(preds) {
  const direct = Object.fromEntries(preds.direct.drivers.map(d => [d.driver, d]));
  const sim = Object.fromEntries(preds.sim.drivers.map(d => [d.driver, d]));
  const drivers = preds.direct.drivers.map(d => {
    const dp = direct[d.driver].p_position;
    const sp = sim[d.driver].p_position;
    const avg = dp.map((v, i) => (v + sp[i]) / 2);
    const expected = avg.reduce((sum, p, j) => sum + (j + 1) * p, 0);
    return { driver: d.driver, team: d.team, expected };
  });
  drivers.sort((a, b) => a.expected - b.expected);
  return drivers.map(d => d.driver);
}

function gridFormation(order, teamByDriver, label) {
  let h = `<div class="grid-col"><p class="grid-label">${label}</p><div class="grid-slots">`;
  for (let i = 0; i < order.length; i++) {
    const driver = order[i];
    const team = teamByDriver[driver] || "";
    const side = i % 2 === 0 ? "left" : "right";
    h += `<div class="grid-slot ${side}">
      <span class="grid-pos">P${i + 1}</span>
      <span class="grid-driver"><i class="stripe" style="--team:${teamColor(team)}"></i>${esc(driver)}</span>
    </div>`;
  }
  return h + `</div></div>`;
}

// Fallback when predicted_order is missing from the JSON (pre-existing predictions):
// sort drivers by expected finishing position from p_position.
function orderFromMatrix(pred) {
  if (pred.predicted_order) return pred.predicted_order;
  const rows = pred.drivers.map(d => ({
    driver: d.driver,
    expected: d.p_position.reduce((sum, p, j) => sum + (j + 1) * p, 0),
  }));
  rows.sort((a, b) => a.expected - b.expected);
  return rows.map(r => r.driver);
}

function gridPanel(preds) {
  const teamByDriver = {};
  for (const d of (preds.direct || preds.sim).drivers) teamByDriver[d.driver] = d.team;

  const hasBoth = preds.direct && preds.sim;
  let h = `<div class="grid-panel">`;

  if (hasBoth) {
    const combo = combinedOrder(preds);
    h += `<div class="grid-controls">
      <div class="seg" role="group" aria-label="Grid view">
        <button type="button" data-grid="combined" aria-pressed="true">combined</button>
        <button type="button" data-grid="split" aria-pressed="false">direct / sim</button>
      </div>
    </div>`;
    h += `<div class="grid-view" data-active="combined">`;
    h += `<div class="grid-combined">${gridFormation(combo, teamByDriver, "Combined")}</div>`;
    h += `<div class="grid-split">
      ${gridFormation(orderFromMatrix(preds.direct), teamByDriver, "Direct")}
      ${gridFormation(orderFromMatrix(preds.sim), teamByDriver, "Sim")}
    </div>`;
    h += `</div>`;
  } else {
    const key = preds.direct ? "direct" : "sim";
    h += gridFormation(orderFromMatrix(preds[key]), teamByDriver, MODEL_LABEL[key]);
  }

  return h + `</div>`;
}

// ---- probabilities ---------------------------------------------------------

function heatmap(pred, key) {
  const rows = [...pred.drivers].sort((a, b) => b.p_win - a.p_win);
  const max = Math.max(...rows.flatMap(d => d.p_position));
  const n = rows[0].p_position.length;
  let h = `<figure class="fig"><p class="fig-title">${MODEL_LABEL[key]}</p><div class="scroll"><table><thead><tr><th></th>`;
  for (let p = 1; p <= n; p++) h += `<th>${p}</th>`;
  h += `<th class="n first">win</th><th class="n">podium</th><th class="n">points</th></tr></thead><tbody>`;
  for (const d of rows) {
    h += `<tr><td class="d"><i class="stripe" style="--team:${teamColor(d.team)}"></i>${esc(d.driver)}</td>`;
    // The cell's ink is a fraction of the accent token; CSS does the mixing.
    d.p_position.forEach((p, i) => {
      h += `<td class="c" title="${esc(d.driver)} P${i + 1}: ${(p * 100).toFixed(1)}%"><div style="--f:${(p / max).toFixed(3)}"></div></td>`;
    });
    h += `<td class="n first">${pct(d.p_win)}</td><td class="n">${pct(d.p_podium)}</td><td class="n">${pct(d.p_points)}</td></tr>`;
  }
  h += `</tbody></table></div><figcaption>Rows sorted by P(win). The darkest cell on this table is ${pct(max)}.</figcaption></figure>`;
  return h;
}

function bars(preds, metric) {
  const direct = Object.fromEntries(preds.direct.drivers.map(d => [d.driver, d]));
  const sim = Object.fromEntries(preds.sim.drivers.map(d => [d.driver, d]));
  const codes = Object.keys(direct).filter(c => c in sim);
  codes.sort((a, b) => (direct[b][metric] + sim[b][metric]) - (direct[a][metric] + sim[a][metric]));
  const max = Math.max(...codes.flatMap(c => [direct[c][metric], sim[c][metric]]));
  let h = "";
  for (const c of codes) {
    const d = direct[c], s = sim[c];
    h += `<div class="bar-row">
      <span class="code"><i class="stripe" style="--team:${teamColor(d.team)}"></i>${esc(c)}</span>
      <span class="track">
        <span class="bar direct" style="width:${(100 * d[metric] / max).toFixed(1)}%"></span>
        <span class="bar sim" style="width:${(100 * s[metric] / max).toFixed(1)}%"></span>
      </span>
      <span class="nums"><b>${pct(d[metric])}</b> direct<br><b>${pct(s[metric])}</b> sim</span>
    </div>`;
  }
  return h;
}

async function renderProbabilities() {
  const el = document.getElementById("matrices");
  const { entries, preds, circuits } = await loadCall(true);
  if (!entries.length) {
    el.innerHTML = `<p class="empty">No prediction committed yet. The first call lands the Thursday before the next Grand Prix.</p>`;
    return;
  }
  const any = preds.direct || preds.sim;
  const byKey = Object.fromEntries(entries.map(e => [modelKey(e.model), e]));
  let h = `<div class="panel">
    <p class="strap"><span class="accent">Round ${any.round}</span><span>${esc(any.call)} call</span></p>
    ${entryHead(any, circuits)}
    <ul class="stamps">${stamp(byKey.direct)}${stamp(byKey.sim)}</ul>
    </div>`;
  h += gridPanel(preds);
  if (preds.direct && preds.sim) {
    h += `<div class="figs">${heatmap(preds.direct, "direct")}${heatmap(preds.sim, "sim")}</div>
      <div class="bars">
        <div class="seg" role="group" aria-label="Metric">${Object.entries(METRICS).map(([k, v]) =>
          `<button type="button" data-metric="${k}" aria-pressed="${k === "p_win"}">${v}</button>`).join("")}</div>
        <div class="legend"><span class="direct"><i></i>direct</span><span class="sim"><i></i>sim</span></div>
        <div id="bar-list">${bars(preds, "p_win")}</div>
      </div>`;
  } else {
    const key = preds.direct ? "direct" : "sim";
    h += `<div class="figs">${heatmap(preds[key], key)}</div>`;
  }
  el.innerHTML = h;
  startClock(any.race_start);

  // Grid view toggle (combined / split).
  for (const btn of el.querySelectorAll(".grid-controls .seg button")) {
    btn.addEventListener("click", () => {
      const view = el.querySelector(".grid-view");
      if (!view) return;
      for (const b of el.querySelectorAll(".grid-controls .seg button")) b.setAttribute("aria-pressed", b === btn);
      view.dataset.active = btn.dataset.grid;
    });
  }

  // Metric toggle (win / podium / points).
  for (const btn of el.querySelectorAll(".bars .seg button")) {
    btn.addEventListener("click", () => {
      for (const b of el.querySelectorAll(".bars .seg button")) b.setAttribute("aria-pressed", b === btn);
      document.getElementById("bar-list").innerHTML = bars(preds, btn.dataset.metric);
    });
  }
}

// ---- record ----------------------------------------------------------------

function standings(summary) {
  if (!summary.length) {
    return `<p class="empty">No race scored yet. The record opens the evening after the next Grand Prix, and from then on it only grows.</p>`;
  }
  let h = `<div class="standings">`;
  for (const call of ["thursday", "saturday"]) {
    const rows = summary.filter(s => s.call === call);
    if (!rows.length) continue;
    const by = Object.fromEntries(rows.map(s => [modelKey(s.model), s]));
    const n = rows[0].n, base = rows[0].baseline_rps;
    const best = Math.min(...rows.map(s => s.rps));
    h += `<div class="col"><p class="col-h">${call} call · ${n} race${n === 1 ? "" : "s"}</p>`;
    for (const key of ["direct", "sim"]) {
      if (!by[key]) continue;
      const cls = (by[key].rps === best ? "win " : "") + (by[key].rps > base ? "bad" : "");
      h += `<div class="row ${cls}"><span>${key}</span><b>${rps(by[key].rps)}</b></div>`;
    }
    h += `<div class="row base"><span>baseline, grid order</span><b>${rps(base)}</b></div></div>`;
  }
  return h + `</div>`;
}

function ledger(results, summary) {
  if (!results.length) return "";
  // One row per round and call, with the two model files folded in.
  const groups = {};
  for (const r of results) {
    const id = `${r.round}-${r.call}`;
    groups[id] ||= { round: r.round, event: r.event, call: r.call, baseline: r.baseline_rps, drivers: {} };
    const g = groups[id], key = modelKey(r.model);
    g[key] = r.rps;
    for (const d of r.drivers) {
      g.drivers[d.driver] ||= { team: d.team, grid: d.grid, finish: d.finish_rank };
      g.drivers[d.driver][key] = d.rps;
    }
  }
  const order = { thursday: 0, saturday: 1 };
  const rows = Object.values(groups).sort((a, b) => b.round - a.round || order[b.call] - order[a.call]);

  const mark = (x, base, best) => x == null ? `<span>–</span>`
    : `<span class="${x > base ? "bad" : ""} ${x === best ? "win" : ""}">${rps(x)}</span>`;
  let h = `<div class="ledger-head"><span>rnd</span><span>race</span><span>direct</span><span>sim</span><span>baseline</span></div>`;
  for (const g of rows) {
    const best = Math.min(...[g.direct, g.sim].filter(x => x != null));
    h += `<details class="race"><summary>
      <span class="rnd">${g.round}</span>
      <span><span class="ev">${esc(g.event)}</span><span class="call">${esc(g.call)} call</span></span>
      ${mark(g.direct, g.baseline, best)}${mark(g.sim, g.baseline, best)}<span>${rps(g.baseline)}</span>
    </summary><div class="drivers">
      <div class="drv hd"><span class="code">driver</span><span>grid</span><span>finish</span><span>direct</span><span>sim</span></div>`;
    const drivers = Object.entries(g.drivers).sort((a, b) => a[1].finish - b[1].finish);
    for (const [code, d] of drivers) {
      h += `<div class="drv"><span class="code"><i class="stripe" style="--team:${teamColor(d.team)}"></i>${esc(code)}</span>
        <span>P${d.grid}</span><span>P${d.finish}</span><span>${rps(d.direct)}</span><span>${rps(d.sim)}</span></div>`;
    }
    h += `</div></details>`;
  }
  for (const call of ["saturday", "thursday"]) {
    const rowsFor = summary.filter(s => s.call === call);
    if (!rowsFor.length) continue;
    const by = Object.fromEntries(rowsFor.map(s => [modelKey(s.model), s.rps]));
    const best = Math.min(...Object.values(by));
    const base = rowsFor[0].baseline_rps;
    h += `<div class="ledger-total"><span></span><span>mean, ${call} call, ${rowsFor[0].n} races</span>
      ${mark(by.direct, base, best)}${mark(by.sim, base, best)}<span>${rps(base)}</span></div>`;
  }
  return h;
}

function pending(manifest, predFiles) {
  const unscored = manifest.filter(m => !m.scored);
  if (!unscored.length) return "";

  const groups = {};
  for (const m of unscored) {
    const id = `${m.round}-${m.call}`;
    groups[id] ||= { round: m.round, event: m.event, call: m.call, entries: [] };
    groups[id].entries.push(m);
  }
  const callOrd = { thursday: 0, saturday: 1 };
  const rows = Object.values(groups).sort((a, b) =>
    b.round - a.round || callOrd[b.call] - callOrd[a.call]);

  let h = `<div class="ledger-head" style="margin-top:var(--space-xl)"><span>rnd</span><span>race</span><span>direct</span><span>sim</span><span></span></div>`;
  for (const g of rows) {
    const preds = {};
    for (const e of g.entries) {
      if (predFiles[e.file]) preds[modelKey(e.model)] = predFiles[e.file];
    }
    const any = preds.direct || preds.sim;
    if (!any) continue;
    const order = orderFromMatrix(any);
    const teamMap = Object.fromEntries(any.drivers.map(d => [d.driver, d.team]));

    h += `<details class="race"><summary>
      <span class="rnd">${g.round}</span>
      <span><span class="ev">${esc(g.event)}</span><span class="call">${esc(g.call)} call</span></span>
      <span class="pend">pending</span><span class="pend">pending</span><span></span>
    </summary><div class="drivers">
      <div class="drv hd"><span class="code">driver</span><span></span><span>pred.</span><span>direct</span><span>sim</span></div>`;

    for (let i = 0; i < order.length; i++) {
      const code = order[i];
      const d = preds.direct?.drivers.find(x => x.driver === code);
      const s = preds.sim?.drivers.find(x => x.driver === code);
      h += `<div class="drv"><span class="code"><i class="stripe" style="--team:${teamColor(teamMap[code])}"></i>${esc(code)}</span>
        <span></span><span>P${i + 1}</span><span>${d ? pct(d.p_win) : "–"}</span><span>${s ? pct(s.p_win) : "–"}</span></div>`;
    }
    h += `</div></details>`;
  }
  return h;
}

async function renderRecord() {
  const [scores, manifest] = await Promise.all([
    getJSON("results.json"),
    getJSON("manifest.json").catch(() => []),
  ]);
  document.getElementById("standings").innerHTML = standings(scores.summary);

  const unscored = manifest.filter(m => !m.scored);
  const predFiles = {};
  await Promise.all(unscored.map(async m => {
    predFiles[m.file] = await getJSON(`predictions/${m.file}`).catch(() => null);
  }));
  document.getElementById("pending").innerHTML = pending(manifest, predFiles);
  document.getElementById("ledger").innerHTML = ledger(scores.results, scores.summary);
}

// ---- nav (N12: status banner over a retracting bar) ------------------------

// The banner is not decoration: it carries the live state of the pipeline,
// which is the one genuinely time-bound thing on the site.
async function fillBanner() {
  const el = document.getElementById("banner-text");
  if (!el) return;
  try {
    const entries = latestCall(await getJSON("manifest.json"));
    if (!entries.length) { el.textContent = "No call committed yet"; return; }
    const e = entries[0];
    const models = entries.length > 1 ? "both models" : modelKey(e.model);
    el.innerHTML = `Round ${e.round} <span class="sep">/</span> <b>${esc(e.event)}</b>
      <span class="sep">/</span> ${esc(e.call)} call committed, ${models}`;
  } catch {
    el.textContent = "gridcast";
  }
}

function wireNav() {
  const nav = document.getElementById("nav");
  if (!nav) return;
  let last = window.scrollY;
  addEventListener("scroll", () => {
    const y = window.scrollY;
    // near the top the banner is always shown; otherwise scroll direction decides
    if (y < 48) nav.classList.remove("is-compact");
    else if (y > last) nav.classList.add("is-compact");
    else nav.classList.remove("is-compact");
    last = y;
  }, { passive: true });

  document.getElementById("banner-x").addEventListener("click", () => {
    // zero the height rather than animating it, so main's padding calc reflows
    // with no leftover gap
    document.documentElement.style.setProperty("--banner-h", "0px");
    nav.classList.add("is-dismissed");
  });
}

// ---- boot ------------------------------------------------------------------

const PAGES = { home: renderHome, probabilities: renderProbabilities, record: renderRecord };

function wireRepoLink() {
  if (!REPO_URL) return;
  const link = document.getElementById("repo-link");
  link.href = REPO_URL;
  link.hidden = false;
  document.getElementById("foot-repo").innerHTML =
    `<a href="${REPO_URL}">${REPO_URL.replace("https://", "")}</a>`;
}

async function main() {
  wireRepoLink();
  wireNav();
  fillBanner();
  const render = PAGES[document.body.dataset.page];
  if (render) await render();
}

main().catch(err => {
  const slot = document.getElementById("next") || document.getElementById("matrices")
    || document.getElementById("standings");
  if (slot) slot.innerHTML = `<p class="empty bad">Could not load the data: ${esc(err.message)}</p>`;
});
