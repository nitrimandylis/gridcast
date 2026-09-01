// gridcast scorecard. Fetches JSON written by scripts/score.py and
// scripts/predict.py and renders it. No maths here beyond formatting: every
// score on this page was computed in Python and committed.

const REPO_URL = "";  // filled in at publication, e.g. "https://github.com/nitrimandylis/gridcast"

// Team palette from apex (lib/colors.ts), keyed by FastF1 team name.
const TEAM_COLORS = {
  "Mercedes": "#00D2BE", "Ferrari": "#E8002D", "McLaren": "#FF8000",
  "Red Bull Racing": "#3671C6", "Alpine": "#0090FF", "Racing Bulls": "#6692FF",
  "Haas F1 Team": "#B6BABD", "Williams": "#64C4FF", "Audi": "#F50537",
  "Aston Martin": "#229971", "Cadillac": "#C5A253",
};
const MODEL_LABEL = { direct: "DIRECT · PLACKETT-LUCE", sim: "SIM · MONTE CARLO" };
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

// ---- circuit outline and countdown ----------------------------------------

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
  const box = (v, l, accent) => `<div class="box ${accent ? "accent" : ""}"><div class="v">${String(v).padStart(2, "0")}</div><div class="l">${l}</div></div>`;
  return () => {
    let left = Math.floor((target - Date.now()) / 1000);
    if (left <= 0) return `<div class="done">Lights out has passed. The result is scored the evening after the race.</div>`;
    const d = Math.floor(left / 86400); left -= d * 86400;
    const h = Math.floor(left / 3600); left -= h * 3600;
    const m = Math.floor(left / 60), s = left - m * 60;
    return box(d, "DAYS") + box(h, "HRS") + box(m, "MIN") + box(s, "SEC", true);
  };
}

// ---- hero -----------------------------------------------------------------

// The latest call is the highest round, and within it Saturday beats Thursday.
function latestCall(manifest) {
  const order = { thursday: 0, saturday: 1 };
  let best = null;
  for (const m of manifest) {
    if (!best || m.round > best.round || (m.round === best.round && order[m.call] > order[best.call])) best = m;
  }
  return best ? manifest.filter(m => m.round === best.round && m.call === best.call) : [];
}

function stamp(entry) {
  if (!entry) return `<li><b>${MODEL_LABEL.direct.split(" ")[0]}</b> no file</li>`;
  const key = modelKey(entry.model);
  if (!entry.commit) return `<li><b>${key}</b> <span class="bad">not yet committed</span></li>`;
  const short = entry.commit.slice(0, 7);
  const link = REPO_URL ? `<a href="${REPO_URL}/commit/${entry.commit}"><code>${short}</code></a>` : `<code>${short}</code>`;
  return `<li><b>${key}</b> committed ${when(entry.committed_at)} · ${link}</li>`;
}

function heatmap(pred, key) {
  const rows = [...pred.drivers].sort((a, b) => b.p_win - a.p_win);
  const max = Math.max(...rows.flatMap(d => d.p_position));
  const n = rows[0].p_position.length;
  let h = `<div class="heat"><p class="label">${MODEL_LABEL[key]}</p><div class="scroll"><table><thead><tr><th></th>`;
  for (let p = 1; p <= n; p++) h += `<th>${p}</th>`;
  h += `<th class="n first">WIN</th><th class="n">PODIUM</th><th class="n">POINTS</th></tr></thead><tbody>`;
  for (const d of rows) {
    h += `<tr><td class="d"><i class="stripe" style="background:${teamColor(d.team)}"></i>${esc(d.driver)}</td>`;
    for (const p of d.p_position) {
      h += `<td class="c" title="${esc(d.driver)} P${d.p_position.indexOf(p) + 1}: ${(p * 100).toFixed(1)}%"><div style="background:rgba(225,6,0,${(p / max).toFixed(3)})"></div></td>`;
    }
    h += `<td class="n first">${pct(d.p_win)}</td><td class="n">${pct(d.p_podium)}</td><td class="n">${pct(d.p_points)}</td></tr>`;
  }
  h += `</tbody></table></div><p class="scale">rows sorted by P(win) · brightest cell ${pct(max)}</p></div>`;
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
      <span class="code"><i class="stripe" style="background:${teamColor(d.team)}"></i>${esc(c)}</span>
      <span class="track">
        <span class="bar direct" style="width:${(100 * d[metric] / max).toFixed(1)}%"></span>
        <span class="bar sim" style="width:${(100 * s[metric] / max).toFixed(1)}%"></span>
      </span>
      <span class="nums"><b>${pct(d[metric])}</b> direct<br><b>${pct(s[metric])}</b> sim</span>
    </div>`;
  }
  return h;
}

function renderHero(entries, preds, circuits) {
  const hero = document.getElementById("hero");
  if (!entries.length) { hero.innerHTML = `<p class="muted">No prediction committed yet.</p>`; return; }
  const any = preds.direct || preds.sim;
  const trained = any.trained_on_rounds;
  const byKey = Object.fromEntries(entries.map(e => [modelKey(e.model), e]));
  const outline = circuitSvg(circuits[CIRCUIT_ALIAS[any.circuit] || any.circuit]);
  const when = any.race_start ? new Date(any.race_start).toLocaleString("en-GB",
    { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "";
  let h = `<div class="event">
      ${outline || "<span></span>"}
      <div>
        <p class="kicker">NEXT UP · ROUND ${any.round} · ${any.call.toUpperCase()} CALL</p>
        <h2>${esc(any.event)}</h2>
        <p class="sub">${esc(any.circuit)}${when ? " · lights out " + when : ""} · both models trained on rounds ${trained[0]}–${trained[trained.length - 1]}</p>
      </div>
      <div class="clock" id="clock"></div>
    </div>
    <ul class="stamps">${stamp(byKey.direct)}${stamp(byKey.sim)}</ul>`;
  if (preds.direct && preds.sim) {
    h += `<div class="heatmaps">${heatmap(preds.direct, "direct")}${heatmap(preds.sim, "sim")}</div>`;
    h += `<div class="bars">
      <div class="seg" role="group" aria-label="Metric">${Object.entries(METRICS).map(([k, v]) =>
        `<button type="button" data-metric="${k}" aria-pressed="${k === "p_win"}">${v}</button>`).join("")}</div>
      <div class="legend"><span class="direct"><i></i>direct</span><span class="sim"><i></i>sim</span></div>
      <div id="bar-list">${bars(preds, "p_win")}</div></div>`;
  } else {
    const key = preds.direct ? "direct" : "sim";
    h += `<div class="heatmaps" style="grid-template-columns:1fr">${heatmap(preds[key], key)}</div>`;
  }
  hero.innerHTML = h;
  if (any.race_start) {
    const tick = countdown(any.race_start), clock = document.getElementById("clock");
    clock.innerHTML = tick();
    setInterval(() => { clock.innerHTML = tick(); }, 1000);
  }
  for (const btn of hero.querySelectorAll(".seg button")) {
    btn.addEventListener("click", () => {
      for (const b of hero.querySelectorAll(".seg button")) b.setAttribute("aria-pressed", b === btn);
      document.getElementById("bar-list").innerHTML = bars(preds, btn.dataset.metric);
    });
  }
}

// ---- record strip ---------------------------------------------------------

function renderRecord(summary) {
  const el = document.getElementById("record");
  if (!summary.length) {
    el.innerHTML = `<div class="empty">No race scored yet. The record starts the evening after the next Grand Prix, and it only ever grows.</div>`;
    return;
  }
  let h = "";
  for (const call of ["thursday", "saturday"]) {
    const rows = summary.filter(s => s.call === call);
    if (!rows.length) continue;
    const by = Object.fromEntries(rows.map(s => [modelKey(s.model), s]));
    const n = rows[0].n, base = rows[0].baseline_rps;
    const best = Math.min(...rows.map(s => s.rps));
    h += `<div class="cell"><p class="label">${call.toUpperCase()} CALL · ${n} RACE${n === 1 ? "" : "S"}</p>`;
    for (const key of ["direct", "sim"]) {
      if (!by[key]) continue;
      const cls = (by[key].rps === best ? "win " : "") + (by[key].rps > base ? "bad" : "");
      h += `<div class="row ${cls}"><span>${key}</span><b>${rps(by[key].rps)}</b></div>`;
    }
    h += `<div class="row"><span>baseline, grid order</span><b>${rps(base)}</b></div></div>`;
  }
  el.innerHTML = h;
}

// ---- race table -----------------------------------------------------------

function renderRaces(results, summary) {
  const el = document.getElementById("races");
  if (!results.length) { el.innerHTML = ""; el.hidden = true; return; }
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
  let h = `<p class="label">SCORED RACES · RPS, LOWER IS BETTER</p>
    <div class="head"><span>RND</span><span>RACE</span><span>DIRECT</span><span>SIM</span><span>BASELINE</span></div>`;
  for (const g of rows) {
    const best = Math.min(...[g.direct, g.sim].filter(x => x != null));
    h += `<details class="race"><summary>
      <span class="rnd">${g.round}</span>
      <span>${esc(g.event)}<span class="call">${g.call}</span></span>
      ${mark(g.direct, g.baseline, best)}${mark(g.sim, g.baseline, best)}<span>${rps(g.baseline)}</span>
    </summary><div class="drivers">
      <div class="drv hd"><span class="code">DRIVER</span><span>GRID</span><span>FINISH</span><span>DIRECT</span><span>SIM</span></div>`;
    const drivers = Object.entries(g.drivers).sort((a, b) => a[1].finish - b[1].finish);
    for (const [code, d] of drivers) {
      h += `<div class="drv"><span class="code"><i class="stripe" style="background:${teamColor(d.team)}"></i>${esc(code)}</span>
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
    h += `<div class="total"><span></span><span>mean, ${call} call, ${rowsFor[0].n} races</span>
      ${mark(by.direct, base, best)}${mark(by.sim, base, best)}<span>${rps(base)}</span></div>`;
  }
  el.hidden = false;
  el.innerHTML = h;
}

// ---- boot -----------------------------------------------------------------

async function main() {
  if (REPO_URL) {
    const link = document.getElementById("repo-link");
    link.href = REPO_URL; link.hidden = false;
    document.getElementById("foot-repo").innerHTML = `Code and every prediction file: <a href="${REPO_URL}">${REPO_URL.replace("https://", "")}</a>.`;
  }
  const [manifest, scores, circuits] = await Promise.all([
    getJSON("manifest.json"), getJSON("results.json"), getJSON("circuits.json").catch(() => ({}))]);
  const entries = latestCall(manifest);
  const preds = {};
  await Promise.all(entries.map(async e => { preds[modelKey(e.model)] = await getJSON(`predictions/${e.file}`); }));
  renderHero(entries, preds, circuits);
  renderRecord(scores.summary);
  renderRaces(scores.results, scores.summary);
}

main().catch(err => {
  document.getElementById("hero").innerHTML = `<p class="muted bad">Could not load the data: ${esc(err.message)}</p>`;
});
