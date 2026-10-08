"""
room_view.py
============

Animated "Live Room" view for the Streamlit dashboard.

`room_html(results)` turns simulation results into one self-contained HTML
page (inline SVG + JavaScript, no external files): one illustrated room per
controller, side by side, each with

    * walls tinted from blue (cold) through neutral to red (hot),
    * a window showing the outdoor weather,
    * a wall AC unit whose airflow is blue when cooling, red when heating,
      and stronger the harder it runs,
    * a ceiling fan spinning at the commanded fan speed,
    * a person when the room is occupied (or "Empty · eco"),
    * a thermometer with the 22–25 °C comfort band and a humidity dial,
    * live readouts: AC power, fan speed, energy used so far.

Play / Pause / Reset, a speed selector and a time slider drive the
animation in the browser, and a small chart under the rooms shows each
room's temperature with a cursor at the current time.

`static_room_html(...)` shows a single room for one operating point
(used on the Controller tab with the sidebar sliders).
"""

from __future__ import annotations

import json

import numpy as np

from simulation import AC_ELEC_KW, COMFORT_HIGH, COMFORT_LOW, FAN_ELEC_KW, SETPOINT, SimResult

CONTROLLER_COLORS = {"Fuzzy (Mamdani)": "#2a78d6", "ON/OFF thermostat": "#eb6834", "Fuzzy PI": "#1baf7a"}


def _round(a, nd=2) -> list:
    return [round(float(v), nd) for v in np.asarray(a)]


def _payload(results: list[SimResult]) -> dict:
    sc = results[0].scenario
    rooms = []
    for r in results:
        kw = np.abs(r.ac) / 100.0 * AC_ELEC_KW + r.fan / 100.0 * FAN_ELEC_KW
        kwh = np.concatenate(([0.0], np.cumsum(kw) / 60.0))
        rooms.append({
            "name": r.controller,
            "color": CONTROLLER_COLORS.get(r.controller, "#4a3aa7"),
            "T": _round(r.T), "H": _round(r.H, 1), "ac": _round(r.ac, 1), "fan": _round(r.fan, 1),
            "kwh": _round(kwh, 3),
        })
    first = results[0]
    return {
        "rooms": rooms,
        "Tout": _round(first.T_out, 1), "Hout": _round(first.H_out, 1),
        "occupied": [bool(v) for v in first.occupied],
        "eco": [bool(v) for v in first.eco],
        "n": int(sc.duration), "startMinute": int(sc.start_minute), "daily": sc.duration > 180,
        "comfort": [COMFORT_LOW, COMFORT_HIGH], "setpoint": SETPOINT,
        "title": f"Scenario {sc.key}: {sc.name}",
        "animate": True,
    }


def room_html(results: list[SimResult]) -> str:
    """Animated side-by-side rooms for a list of simulation results."""
    return _TEMPLATE.replace("__DATA__", json.dumps(_payload(results)))


def static_room_html(temp: float, hum: float, ac: float, fan: float, name: str = "Fuzzy (Mamdani)",
                     T_out: float | None = None, H_out: float | None = None) -> str:
    """One room frozen at a single operating point (no animation controls)."""
    data = {
        "rooms": [{"name": name, "color": CONTROLLER_COLORS.get(name, "#2a78d6"),
                   "T": [round(temp, 2)] * 2, "H": [round(hum, 1)] * 2,
                   "ac": [round(ac, 1)], "fan": [round(fan, 1)], "kwh": [0.0, 0.0]}],
        "Tout": [round(T_out if T_out is not None else temp, 1)],
        "Hout": [round(H_out if H_out is not None else hum, 1)],
        "occupied": [True], "eco": [False], "n": 1, "startMinute": 0, "daily": False,
        "comfort": [COMFORT_LOW, COMFORT_HIGH], "setpoint": SETPOINT,
        "title": "", "animate": False,
    }
    return _TEMPLATE.replace("__DATA__", json.dumps(data))


# ---------------------------------------------------------------------------
# HTML / SVG / JS template
# ---------------------------------------------------------------------------
_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root { --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
          --panel:#fcfcfb; --border:rgba(11,11,11,0.10); }
  * { box-sizing: border-box; }
  body { margin:0; padding:4px; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         color: var(--ink); background: transparent; }
  .title { font-weight:600; font-size:15px; margin:2px 4px 8px; }
  .rooms { display:grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap:12px; }
  .panel { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:6px; }
  .panel svg { width:100%; height:auto; display:block; }
  .controls { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin:12px 4px 6px; }
  button { font:inherit; font-size:14px; padding:6px 14px; border-radius:8px; border:1px solid var(--axis);
           background:#fff; color:var(--ink); cursor:pointer; }
  button.primary { background:#2a78d6; border-color:#2a78d6; color:#fff; font-weight:600; min-width:92px; }
  select { font:inherit; font-size:13px; padding:5px 8px; border-radius:8px; border:1px solid var(--axis); background:#fff; }
  input[type=range] { flex:1; min-width:180px; accent-color:#2a78d6; }
  .clock { font-variant-numeric: tabular-nums; font-weight:600; min-width:110px; }
  .chart { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:6px; margin-top:4px; }
  .chart svg { width:100%; height:auto; display:block; }
  .hidden { display:none !important; }
  body.static .rooms { grid-template-columns: minmax(300px, 520px); }
</style></head>
<body>
<div class="title" id="title"></div>
<div class="rooms" id="rooms"></div>
<div class="controls" id="controls">
  <button class="primary" id="play">▶ Play</button>
  <button id="reset">↺ Reset</button>
  <label>Speed <select id="speed">
    <option value="1">1 min / s</option><option value="5">5 min / s</option>
    <option value="15">15 min / s</option><option value="60">60 min / s</option>
  </select></label>
  <span class="clock" id="clock"></span>
  <input type="range" id="scrub" min="0" step="0.01" value="0">
</div>
<div class="chart" id="chartbox"><svg id="chart" viewBox="0 0 1000 190"></svg></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
};
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const mix = (c1, c2, t) => { const a = hex(c1), b = hex(c2);
  return "rgb(" + a.map((v, i) => Math.round(lerp(v, b[i], t))).join(",") + ")"; };

// wall colour: cold blue -> neutral -> warm red
function wallColor(T) {
  if (T <= D.setpoint) return mix("#b7d3f6", "#f4f1ea", clamp((T - 14) / (D.setpoint - 14), 0, 1));
  return mix("#f4f1ea", "#f6b9a3", clamp((T - D.setpoint) / (32 - D.setpoint), 0, 1));
}
const yT = T => 300 - (clamp(T, 10, 40) - 10) / 30 * 240;   // thermometer scale

// ---------------------------------------------------------------- rooms --
const roomsDiv = document.getElementById("rooms");
const views = D.rooms.map(room => buildRoom(room));

function buildRoom(room) {
  const panel = document.createElement("div");
  panel.className = "panel";
  roomsDiv.appendChild(panel);
  const svg = el("svg", { viewBox: "0 0 520 400", role: "img", "aria-label": room.name + " room" }, panel);
  const v = {};
  el("rect", { x: 14, y: 12, width: 10, height: 10, rx: 2, fill: room.color }, svg);
  const name = el("text", { x: 30, y: 22, "font-size": 15, "font-weight": 600, fill: "#0b0b0b" }, svg);
  name.textContent = room.name;
  v.badgeBg = el("rect", { x: 404, y: 6, width: 100, height: 22, rx: 11 }, svg);
  v.badge = el("text", { x: 454, y: 21, "text-anchor": "middle", "font-size": 12, "font-weight": 600 }, svg);

  // room shell
  v.wall = el("rect", { x: 16, y: 40, width: 360, height: 300, rx: 10, stroke: "#c3c2b7", "stroke-width": 1.25 }, svg);
  el("rect", { x: 17, y: 296, width: 358, height: 43, fill: "#e6e0d4" }, svg);
  el("line", { x1: 17, y1: 296, x2: 375, y2: 296, stroke: "#c3c2b7" }, svg);

  // window with outdoor weather
  v.sky = el("rect", { x: 34, y: 112, width: 112, height: 92, rx: 4, stroke: "#898781", "stroke-width": 2 }, svg);
  v.sun = el("circle", { cx: 116, cy: 136, r: 13, fill: "#eda100" }, svg);
  v.cloud = el("g", {}, svg);
  el("ellipse", { cx: 72, cy: 150, rx: 20, ry: 10, fill: "#ffffff", opacity: 0.9 }, v.cloud);
  el("ellipse", { cx: 88, cy: 144, rx: 14, ry: 10, fill: "#ffffff", opacity: 0.9 }, v.cloud);
  el("line", { x1: 90, y1: 112, x2: 90, y2: 204, stroke: "#898781", "stroke-width": 2 }, svg);
  el("line", { x1: 34, y1: 158, x2: 146, y2: 158, stroke: "#898781", "stroke-width": 2 }, svg);
  v.outside = el("text", { x: 90, y: 222, "text-anchor": "middle", "font-size": 11.5, fill: "#52514e" }, svg);

  // ceiling fan
  el("line", { x1: 196, y1: 40, x2: 196, y2: 74, stroke: "#52514e", "stroke-width": 2 }, svg);
  v.fan = el("g", {}, svg);
  for (let i = 0; i < 3; i++) el("ellipse", { cx: 196 + 17, cy: 78, rx: 16, ry: 4.5, fill: "#898781",
    transform: `rotate(${i * 120} 196 78)` }, v.fan);
  el("circle", { cx: 196, cy: 78, r: 5, fill: "#52514e" }, svg);

  // wall AC unit + airflow
  el("rect", { x: 236, y: 58, width: 124, height: 34, rx: 7, fill: "#ffffff", stroke: "#898781", "stroke-width": 1.25 }, svg);
  el("line", { x1: 246, y1: 84, x2: 350, y2: 84, stroke: "#c3c2b7", "stroke-width": 2 }, svg);
  v.led = el("circle", { cx: 348, cy: 68, r: 3.5 }, svg);
  v.flow = [];
  [258, 298, 338].forEach((x, i) => {
    v.flow.push(el("path", { d: `M ${x} 96 q 12 22 0 44 t 0 44`, fill: "none", "stroke-width": 3,
      "stroke-linecap": "round", "stroke-dasharray": "7 9" }, svg));
  });

  // humidity dial on the wall
  el("circle", { cx: 186, cy: 160, r: 30, fill: "#ffffff", stroke: "#898781", "stroke-width": 1.25 }, svg);
  el("path", { d: "M 164 172 A 24 24 0 1 1 208 172", fill: "none", stroke: "#e1e0d9", "stroke-width": 5 }, svg);
  v.hArc = el("path", { fill: "none", stroke: "#2a78d6", "stroke-width": 5, "stroke-linecap": "round" }, svg);
  v.hText = el("text", { x: 186, y: 166, "text-anchor": "middle", "font-size": 12, "font-weight": 600, fill: "#0b0b0b" }, svg);
  const rh = el("text", { x: 186, y: 204, "text-anchor": "middle", "font-size": 10.5, fill: "#52514e" }, svg);
  rh.textContent = "humidity";

  // desk + person
  el("rect", { x: 210, y: 252, width: 120, height: 8, rx: 2, fill: "#b9a88e" }, svg);
  el("rect", { x: 218, y: 260, width: 6, height: 36, fill: "#b9a88e" }, svg);
  el("rect", { x: 316, y: 260, width: 6, height: 36, fill: "#b9a88e" }, svg);
  v.person = el("g", {}, svg);
  el("circle", { cx: 186, cy: 236, r: 11, fill: "#52514e" }, v.person);
  el("path", { d: "M 170 296 L 172 262 Q 186 248 200 262 L 202 296 Z", fill: "#52514e" }, v.person);
  v.empty = el("text", { x: 186, y: 282, "text-anchor": "middle", "font-size": 12, fill: "#1baf7a", "font-weight": 600 }, svg);
  v.empty.textContent = "Empty · eco";

  // thermometer
  el("rect", { x: 430, y: 52, width: 20, height: 256, rx: 10, fill: "#ffffff", stroke: "#898781", "stroke-width": 1.25 }, svg);
  el("rect", { x: 426, y: yT(D.comfort[1]), width: 28, height: yT(D.comfort[0]) - yT(D.comfort[1]),
    fill: "#1baf7a", opacity: 0.22 }, svg);
  v.merc = el("rect", { x: 435, width: 10, rx: 5, fill: "#e34948" }, svg);
  el("circle", { cx: 440, cy: 320, r: 15, fill: "#e34948" }, svg);
  for (let t = 10; t <= 40; t += 5) {
    el("line", { x1: 452, x2: 458, y1: yT(t), y2: yT(t), stroke: "#898781" }, svg);
    const lb = el("text", { x: 462, y: yT(t) + 4, "font-size": 10.5, fill: "#52514e" }, svg);
    lb.textContent = t + "°";
  }
  v.tText = el("text", { x: 440, y: 360, "text-anchor": "middle", "font-size": 18, "font-weight": 700, fill: "#0b0b0b" }, svg);

  // readouts
  v.read = [0, 1, 2].map(i => el("text", { x: 16 + i * 122, y: 366, "font-size": 12.5, fill: "#0b0b0b" }, svg));
  v.readSub = [0, 1, 2].map(i => el("text", { x: 16 + i * 122, y: 384, "font-size": 10.5, fill: "#52514e" }, svg));
  v.readSub[0].textContent = "AC power"; v.readSub[1].textContent = "fan speed"; v.readSub[2].textContent = "energy so far";
  v.room = room;
  return v;
}

function arcPath(frac) {      // humidity dial arc, 20..90 % mapped to 0..1
  const a0 = Math.PI * 0.75, sweep = Math.PI * 1.5 * clamp(frac, 0, 1);
  const a1 = a0 + sweep, r = 24, cx = 186, cy = 160;
  const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
  return `M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${r} ${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
}

let fanAngle = 0, flowOffset = 0;

function render(f, dtReal) {
  const n = D.n;
  const i0 = Math.floor(clamp(f, 0, n)), i1 = Math.min(i0 + 1, n), w = clamp(f, 0, n) - i0;
  const ia = Math.min(i0, n - 1);
  const Tout = D.Tout[ia], Hout = D.Hout[ia];
  const occ = D.occupied[ia], eco = D.eco[ia];
  views.forEach(v => {
    const R = v.room;
    const T = lerp(R.T[i0], R.T[i1], w), H = lerp(R.H[i0], R.H[i1], w);
    const ac = R.ac[ia], fan = R.fan[ia], kwh = lerp(R.kwh[i0], R.kwh[i1], w);
    v.wall.setAttribute("fill", wallColor(T));
    v.sky.setAttribute("fill", Tout >= 24 ? "#9ec5f4" : (Tout <= 15 ? "#c9ced6" : "#cde2fb"));
    v.sun.style.display = Tout >= 20 ? "" : "none";
    v.cloud.style.display = Tout < 24 ? "" : "none";
    v.outside.textContent = D.animate ? `outside ${Tout.toFixed(1)} °C · ${Hout.toFixed(0)} %` : "";
    const mag = Math.abs(ac) / 100;
    const mode = ac >= 5 ? "cool" : (ac <= -5 ? "heat" : "idle");
    const fc = mode === "cool" ? "#2a78d6" : "#e34948";
    v.flow.forEach((p, k) => {
      p.setAttribute("stroke", fc);
      p.setAttribute("opacity", mode === "idle" ? 0 : (0.25 + 0.75 * mag).toFixed(2));
      p.setAttribute("stroke-dashoffset", (-flowOffset * (0.3 + mag) - k * 5).toFixed(1));
    });
    v.led.setAttribute("fill", mode === "idle" ? "#c3c2b7" : fc);
    const badge = { cool: ["Cooling", "#2a78d6"], heat: ["Heating", "#e34948"], idle: ["Idle", "#898781"] }[mode];
    v.badge.textContent = badge[0];
    v.badge.setAttribute("fill", badge[1]);
    v.badgeBg.setAttribute("fill", badge[1]);
    v.badgeBg.setAttribute("fill-opacity", 0.12);
    v.fan.setAttribute("transform", `rotate(${(fanAngle * fan / 100).toFixed(1)} 196 78)`);
    v.hArc.setAttribute("d", arcPath((H - 20) / 70));
    v.hText.textContent = H.toFixed(0) + "%";
    const top = yT(T);
    v.merc.setAttribute("y", top.toFixed(1));
    v.merc.setAttribute("height", (316 - top).toFixed(1));
    v.tText.textContent = T.toFixed(1) + " °C";
    v.tText.setAttribute("fill", T >= D.comfort[0] && T <= D.comfort[1] ? "#0b0b0b" : "#e34948");
    v.person.style.display = occ ? "" : "none";
    v.empty.style.display = occ ? "none" : "";
    v.empty.textContent = eco ? "Empty · eco setback" : "Empty";
    v.read[0].textContent = (ac > 0 ? "+" : "") + ac.toFixed(0) + " %";
    v.read[1].textContent = fan.toFixed(0) + " %";
    v.read[2].textContent = kwh.toFixed(2) + " kWh";
  });
  drawCursor(f);
  document.getElementById("clock").textContent = clockText(f);
  scrub.value = f;
}

function clockText(f) {
  if (!D.daily) return `t = ${Math.floor(f)} / ${D.n} min`;
  const m = Math.floor(D.startMinute + f) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- chart --
const chart = document.getElementById("chart");
const CX0 = 54, CX1 = 980, CY0 = 18, CY1 = 160;
let cursor;
(function buildChart() {
  const all = D.rooms.flatMap(r => r.T).concat(D.Tout, D.comfort);
  const lo = Math.floor(Math.min(...all) - 0.5), hi = Math.ceil(Math.max(...all) + 0.5);
  const X = i => CX0 + i / D.n * (CX1 - CX0), Y = T => CY1 - (T - lo) / (hi - lo) * (CY1 - CY0);
  el("rect", { x: CX0, y: Y(D.comfort[1]), width: CX1 - CX0, height: Y(D.comfort[0]) - Y(D.comfort[1]),
    fill: "#898781", opacity: 0.13 }, chart);
  const step = (hi - lo) > 12 ? 5 : 2;
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
    el("line", { x1: CX0, x2: CX1, y1: Y(t), y2: Y(t), stroke: "#e1e0d9" }, chart);
    const lb = el("text", { x: CX0 - 8, y: Y(t) + 4, "text-anchor": "end", "font-size": 11, fill: "#52514e" }, chart);
    lb.textContent = t + "°";
  }
  const ticks = D.daily ? 8 : 6;
  for (let k = 0; k <= ticks; k++) {
    const i = Math.round(k * D.n / ticks);
    const lb = el("text", { x: X(i), y: CY1 + 18, "text-anchor": "middle", "font-size": 11, fill: "#52514e" }, chart);
    lb.textContent = D.daily ? clockText(i) : i + " min";
  }
  const path = arr => arr.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)).join(" ");
  el("path", { d: path(D.Tout), fill: "none", stroke: "#898781", "stroke-width": 1.25, "stroke-dasharray": "3 4" }, chart);
  D.rooms.forEach(r => el("path", { d: path(r.T), fill: "none", stroke: r.color, "stroke-width": 2 }, chart));
  // legend
  let lx = CX0;
  D.rooms.concat([{ name: "outside", color: "#898781" }]).forEach(r => {
    el("rect", { x: lx, y: 2, width: 10, height: 10, rx: 2, fill: r.color }, chart);
    const t = el("text", { x: lx + 14, y: 11, "font-size": 11, fill: "#52514e" }, chart);
    t.textContent = r.name;
    lx += 26 + r.name.length * 6.4;
  });
  cursor = el("line", { y1: CY0, y2: CY1, stroke: "#0b0b0b", "stroke-width": 1.25 }, chart);
  window._X = X;
})();
function drawCursor(f) { const x = window._X(f); cursor.setAttribute("x1", x); cursor.setAttribute("x2", x); }

// ------------------------------------------------------------- controls --
document.getElementById("title").textContent = D.title;
const playBtn = document.getElementById("play"), scrub = document.getElementById("scrub");
const speedSel = document.getElementById("speed");
scrub.max = D.n;
speedSel.value = D.daily ? "60" : "5";
let frame = 0, playing = false, last = null;

function tick(ts) {
  const dt = last === null ? 0 : (ts - last) / 1000;
  last = ts;
  fanAngle = (fanAngle + dt * 720) % 360000;
  flowOffset += dt * 60;
  if (playing) {
    frame += dt * Number(speedSel.value);
    if (frame >= D.n) { frame = D.n; playing = false; playBtn.textContent = "▶ Play"; }
  }
  render(frame, dt);
  requestAnimationFrame(tick);
}
playBtn.onclick = () => {
  if (frame >= D.n) frame = 0;
  playing = !playing;
  playBtn.textContent = playing ? "❚❚ Pause" : "▶ Play";
};
document.getElementById("reset").onclick = () => { frame = 0; playing = false; playBtn.textContent = "▶ Play"; };
scrub.oninput = () => { frame = Number(scrub.value); };

// "#f=<minute>" in the URL opens the animation at that minute (used for screenshots)
const hashFrame = /f=([0-9.]+)/.exec(location.hash);
if (hashFrame) frame = clamp(Number(hashFrame[1]), 0, D.n);

if (!D.animate) {
  document.getElementById("controls").classList.add("hidden");
  document.getElementById("chartbox").classList.add("hidden");
  document.getElementById("title").classList.add("hidden");
  document.body.classList.add("static");
  frame = 0;
}
requestAnimationFrame(tick);
</script>
</body></html>
"""
