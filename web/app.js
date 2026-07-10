// Should They Have Gone For It? — all decision math runs client-side.
"use strict";

const TEAM_COLORS = {
  ARI: "#97233F",
  ATL: "#A71930",
  BAL: "#241773",
  BUF: "#00338D",
  CAR: "#0085CA",
  CHI: "#0B162A",
  CIN: "#FB4F14",
  CLE: "#311D00",
  DAL: "#041E42",
  DEN: "#FB4F14",
  DET: "#0076B6",
  GB: "#203731",
  HOU: "#03202F",
  IND: "#002C5F",
  JAX: "#006778",
  KC: "#E31837",
  LAC: "#0080C6",
  LA: "#003594",
  LV: "#000000",
  MIA: "#008E97",
  MIN: "#4F2683",
  NE: "#002244",
  NO: "#D3BC8D",
  NYG: "#0B2265",
  NYJ: "#125740",
  PHI: "#004C54",
  PIT: "#FFB612",
  SEA: "#002244",
  SF: "#AA0000",
  TB: "#D50A0A",
  TEN: "#0C2340",
  WAS: "#5A1414",
  OAK: "#000000",
  SD: "#0080C6",
  STL: "#003594",
};

let G = null,
  T = null,
  C = null; // wp_grid, tables, coaches
const state = { togo: 3, yl: 45, sd: 0, qtr: 3, clk: 480 };

const $ = (s) => document.querySelector(s);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

// game_seconds_remaining from quarter + clock-in-quarter
function gameSeconds() {
  if (state.qtr === 5) return 0; // OT -> treat as 0s left in regulation
  return (4 - state.qtr) * 900 + state.clk;
}

// WP for a 1st-and-10 state, interpolated on the time axis
function wp1st10(sd, sec, yl) {
  sd = clamp(Math.round(sd), G.score_min, G.score_max);
  yl = clamp(Math.round(yl), 1, 99);
  sec = clamp(sec, 0, 3600);
  const plane = G.grid[String(sd)];
  const step = G.sec_step;
  const i = Math.floor(sec / step);
  const lo = i * step;
  const frac = (sec - lo) / step;
  const a = plane[i][yl - 1];
  const b = plane[Math.min(i + 1, plane.length - 1)][yl - 1];
  return a + (b - a) * frac;
}

const conv = (t) => T.conversion[clamp(Math.round(t), 1, 15)] ?? 0.5;
const fgPct = (d) =>
  T.fg_make[clamp(Math.round(d), 15, 70)] ?? (d > 66 ? 0.02 : 0.85);
const puntEnd = (y) =>
  T.punt_result[clamp(Math.round(y), 1, 99)] ?? Math.min(80, 100 - y + 42);

// the three lotteries, priced in win probability for the team with the ball
function options() {
  const sec = gameSeconds();
  const { sd, yl, togo } = state;

  // GO
  const pc = conv(togo);
  const newYl = yl - togo;
  const wpSucceed =
    newYl <= 0
      ? 1 - wp1st10(-(sd + 7), sec, 75) // touchdown
      : wp1st10(sd, sec, newYl);
  const wpFail = 1 - wp1st10(-sd, sec, 100 - yl); // turnover on downs
  const go = pc * wpSucceed + (1 - pc) * wpFail;

  // FIELD GOAL
  const dist = yl + 17;
  const pm = fgPct(dist);
  const wpMake = 1 - wp1st10(-(sd + 3), sec, 75);
  const wpMiss = 1 - wp1st10(-sd, sec, Math.min(80, 100 - (yl + 7)));
  const fg = pm * wpMake + (1 - pm) * wpMiss;

  // PUNT
  const punt = 1 - wp1st10(-sd, sec, puntEnd(yl));

  return {
    go,
    fg,
    punt,
    meta: { pc, pm, dist, fgReachable: dist <= 66, tooCloseToPunt: yl <= 8 },
  };
}

// ---------- field ----------
function buildTurf() {
  const turf = $("#turf");
  // yard numbers 10..50..10 at 10% steps (skip goal lines)
  for (let i = 1; i < 10; i++) {
    const ln = document.createElement("div");
    ln.style.cssText = `position:absolute;top:6px;left:${i * 10}%;transform:translateX(-50%);
      font-family:var(--mono);font-size:10px;color:rgba(243,239,226,.55);pointer-events:none`;
    const yards = i <= 5 ? i * 10 : (10 - i) * 10; // 10 20 30 40 50 40 30 20 10
    ln.textContent = yards === 50 ? "50" : yards;
    turf.appendChild(ln);
  }
  turf.addEventListener("click", (e) => {
    const r = turf.getBoundingClientRect();
    const frac = clamp((e.clientX - r.left) / r.width, 0, 1); // 0=own goal(left) .. 1=opp goal(right)
    // left is own end zone (yardline_100=99), right is opp end zone (yardline_100=1)
    setState({ yl: clamp(Math.round(99 - frac * 98), 1, 99) });
  });
}

// yardline_100 -> x% across turf. yl=99 (own goal) -> ~1%, yl=1 (opp goal) -> ~99%
const ylToPct = (yl) => 100 - yl;

function spotLabel(yl) {
  if (yl === 50) return "MIDFIELD";
  return yl < 50 ? `OPP ${yl}` : `OWN ${100 - yl}`;
}

// ---------- render ----------
function render() {
  // sliders fill + outputs
  fill("#togo", state.togo, 1, 15);
  $("#togoOut").textContent = state.togo;
  fill("#yl", state.yl, 1, 99);
  $("#ylOut").textContent = state.yl;
  fill("#sd", state.sd, -24, 24);
  $("#sdOut").textContent =
    state.sd === 0 ? "even" : state.sd > 0 ? `+${state.sd}` : state.sd;
  fill("#clk", state.clk, 0, 900);
  $("#clkOut").textContent = state.qtr === 5 ? "OT" : fmtClock(state.clk);

  // field
  $("#ball").style.left = ylToPct(state.yl) + "%";
  const gainYl = clamp(state.yl - state.togo, 0, 99);
  $("#togoMarker").style.left = ylToPct(gainYl) + "%";
  $("#spotLabel").textContent = spotLabel(state.yl);
  $("#spotSub").textContent = `4th & ${state.togo}`;

  // verdict
  const o = options();
  const opts = [
    { key: "go", name: "Go for it", wp: o.go, cls: "go" },
    { key: "fg", name: "Field goal", wp: o.fg, cls: "fg" },
    { key: "punt", name: "Punt", wp: o.punt, cls: "punt" },
  ].sort((a, b) => b.wp - a.wp);

  const best = opts[0],
    second = opts[1];
  const edge = (best.wp - second.wp) * 100;
  const panel = $("#verdict");
  const callTxt = { go: "GO FOR IT", fg: "FIELD GOAL", punt: "PUNT" }[best.key];
  panel.className =
    "verdict " +
    (best.key === "go" ? "" : best.key === "fg" ? "is-fg" : "is-punt");
  $("#vCall").textContent = callTxt;
  $("#vEdge").textContent =
    `+${edge.toFixed(1)} win-prob points vs. ${labelOf(second.key)}`;

  // bars (fixed order go/fg/punt for scan stability, highlight best)
  const order = [
    { key: "go", name: "Go for it", wp: o.go, cls: "go", bc: "go" },
    { key: "fg", name: "Field goal", wp: o.fg, cls: "fg", bc: "fg-c" },
    { key: "punt", name: "Punt", wp: o.punt, cls: "punt", bc: "punt-c" },
  ];
  $("#bars").innerHTML = order
    .map((r) => {
      const isBest = r.key === best.key;
      return `<div class="bar-row ${isBest ? "best " + r.bc : ""}">
      <div class="bar-name">${r.name}</div>
      <div class="bar-track"><div class="bar-fill ${r.cls}" style="width:${(r.wp * 100).toFixed(1)}%"></div></div>
      <div class="bar-val">${(r.wp * 100).toFixed(1)}%</div>
    </div>`;
    })
    .join("");

  $("#vNote").innerHTML = noteFor(best, o);
}

function labelOf(k) {
  return { go: "going for it", fg: "the field goal", punt: "the punt" }[k];
}

function noteFor(best, o) {
  const conv = (o.meta.pc * 100).toFixed(0);
  const parts = [];
  if (best.key === "go")
    parts.push(
      `Model converts this <b>${conv}%</b> of the time, and the field position swing on a stop is worth the risk.`,
    );
  else if (best.key === "fg")
    parts.push(
      `A ${o.meta.dist}-yard try makes <b>${(o.meta.pm * 100).toFixed(0)}%</b> of the time — the points beat the gamble here.`,
    );
  else
    parts.push(
      `Too far to convert (<b>${conv}%</b>) and out of comfortable field-goal range. Flip the field.`,
    );
  if (!o.meta.fgReachable)
    parts.push(
      `Field goal is a ${o.meta.dist}-yard kick — realistically off the table.`,
    );
  return parts.join(" ");
}

function fill(sel, v, lo, hi) {
  const el = $(sel);
  if (!el) return;
  el.value = v;
  el.style.setProperty("--fill", ((v - lo) / (hi - lo)) * 100 + "%");
}
function fmtClock(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function setState(patch) {
  Object.assign(state, patch);
  render();
}

// ---------- leaderboard ----------
let boardSort = { key: "wp_burned", dir: -1 };
function renderBoard() {
  if (!C) return;
  $("#boardYears").textContent = `${C.seasons[0]}–${C.seasons[1]}`;
  const rows = [...C.leaderboard].sort((a, b) => {
    const k = boardSort.key;
    if (k === "coach" || k === "team")
      return boardSort.dir * String(a[k]).localeCompare(String(b[k]));
    return boardSort.dir * (a[k] - b[k]);
  });
  const max = Math.max(...C.leaderboard.map((r) => r.wp_burned), 1);
  $("#boardBody").innerHTML = rows
    .map((r, i) => {
      const col = TEAM_COLORS[r.team] || "#182422";
      return `<tr>
      <td class="rank ${i < 3 ? "top" : ""}">${i + 1}</td>
      <td class="coach-name">${r.coach}</td>
      <td><span class="team-chip" style="background:${col}22;color:${lighten(col)}">${r.team}</span></td>
      <td class="num wp-cell"><div class="wp-bar" style="width:${((r.wp_burned / max) * 100).toFixed(0)}%"></div><span>${r.wp_burned.toFixed(1)}</span></td>
      <td class="num">${r.conservative_kicks}</td>
      <td class="num">${r.burn_per_kick.toFixed(3)}</td>
    </tr>`;
    })
    .join("");
  document.querySelectorAll("#boardTable th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.sort === boardSort.key);
  });
}
function lighten(hex) {
  return hex === "#000000" ? "#ccc" : "#fff";
}

// ---------- wiring ----------
function wire() {
  $("#togo").addEventListener("input", (e) =>
    setState({ togo: +e.target.value }),
  );
  $("#yl").addEventListener("input", (e) => setState({ yl: +e.target.value }));
  $("#sd").addEventListener("input", (e) => setState({ sd: +e.target.value }));
  $("#clk").addEventListener("input", (e) =>
    setState({ clk: +e.target.value }),
  );
  $("#qtrSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    $("#qtrSeg")
      .querySelectorAll("button")
      .forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    setState({ qtr: +b.dataset.q });
  });
  // tabs
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => {
      document
        .querySelectorAll(".tab")
        .forEach((x) => x.classList.remove("is-active"));
      document
        .querySelectorAll(".view")
        .forEach((x) => x.classList.remove("is-active"));
      t.classList.add("is-active");
      document
        .querySelector(`.view[data-view="${t.dataset.view}"]`)
        .classList.add("is-active");
      if (t.dataset.view === "board") renderBoard();
    }),
  );
  // board sort
  document.querySelectorAll("#boardTable th").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (k === "rank") return;
      boardSort.dir =
        boardSort.key === k
          ? -boardSort.dir
          : k === "coach" || k === "team"
            ? 1
            : -1;
      boardSort.key = k;
      renderBoard();
    }),
  );
}

async function boot() {
  const [g, t, c] = await Promise.all([
    fetch("wp_grid.json?v=1").then((r) => r.json()),
    fetch("tables.json?v=1").then((r) => r.json()),
    fetch("coaches.json?v=1").then((r) => r.json()),
  ]);
  G = g;
  T = t;
  C = c;
  $("#footData").textContent = `nflverse ${t.seasons[0]}–${t.seasons[1]}`;
  buildTurf();
  wire();
  render();
}
boot();
