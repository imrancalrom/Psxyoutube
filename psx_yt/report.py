"""Render trend data as a self-contained HTML dashboard."""

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PSX YouTube Buzz</title>
<style>
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1d1b; --muted: #6b6b66; --border: #e3e2dc;
  --accent: #2563eb; --bull: #15803d; --bear: #b91c1c; --neutral: #a8a29e; --hold: #b45309;
  --s1: #2563eb; --s2: #d97706; --s3: #0d9488; --s4: #9333ea; --s5: #db2777;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141413; --surface: #1e1e1c; --text: #ecebe6; --muted: #9c9a92; --border: #33322e;
    --accent: #60a5fa; --bull: #4ade80; --bear: #f87171; --neutral: #78716c; --hold: #fbbf24;
    --s1: #60a5fa; --s2: #fbbf24; --s3: #2dd4bf; --s4: #c084fc; --s5: #f472b6;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 0 0 12px; }
.sub { color: var(--muted); margin-bottom: 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }
.tile, .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tile .v { font-size: 22px; font-weight: 600; }
.tile .l { color: var(--muted); font-size: 12px; }
.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
.chart { min-height: 230px; }
.chart svg { display: block; overflow: visible; }
.chart svg text { fill: var(--muted); font-size: 11px; }
.chart .grid { stroke: var(--border); }
.chart .hit { fill: transparent; }
.chart .hit:hover { fill: var(--border); fill-opacity: 0.35; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.bar { display: grid; grid-template-columns: minmax(0, 9em) 1fr 3.5em; gap: 8px; align-items: center; font-size: 12px; margin: 7px 0; }
.bl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bt { height: 12px; background: var(--bg); border-radius: 3px; overflow: hidden; }
.bt span { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
.bv { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
input[type=search], select { padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text); font: inherit; }
input[type=search] { flex: 1 1 220px; max-width: 320px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.toolbar .lbl { color: var(--muted); font-size: 12px; margin-right: 2px; }
.seg { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { font: inherit; font-size: 13px; padding: 6px 12px; border: 0; border-right: 1px solid var(--border);
  background: var(--surface); color: var(--text); cursor: pointer; }
.seg button:last-child { border-right: 0; }
.seg button[aria-pressed="true"] { background: var(--accent); color: var(--surface); font-weight: 600; }
button.link { font: inherit; font-size: 13px; background: none; border: 0; color: var(--accent); cursor: pointer; padding: 6px; }
.tablewrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--muted); font-weight: 500; font-size: 12px; cursor: pointer; user-select: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.row { cursor: pointer; }
tr.row:hover { background: var(--bg); }
.sym { font-weight: 600; }
.name { color: var(--muted); font-size: 12px; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 99px; border: 1px solid currentColor; }
.RISING, .NEW, .IMPROVING, .BUY { color: var(--bull); } .FALLING, .WORSENING, .SELL { color: var(--bear); }
.HOLD, .holdc { color: var(--hold); } .MIXED { color: var(--muted); }
.STEADY, .QUIET, .STABLE { color: var(--muted); }
.tone { font-size: 12px; } .tone .d { color: var(--muted); margin-top: 2px; }
.sbar { display: flex; width: 80px; height: 8px; border-radius: 4px; overflow: hidden; background: var(--border); }
.sbar span { display: block; height: 100%; }
.detail td { white-space: normal; background: var(--bg); }
.detail ul { margin: 4px 0; padding-left: 18px; }
.detail a { color: var(--accent); }
.pos { color: var(--bull); } .neg { color: var(--bear); }
.foot { color: var(--muted); font-size: 12px; margin-top: 16px; }
.section { margin-bottom: 16px; }
tr.has-note td { border-bottom: 0; padding-bottom: 2px; }
tr.note td { padding-top: 0; color: var(--muted); font-size: 12px; white-space: normal; }
tr.row.note:hover { background: none; }
</style>
</head>
<body>
<main>
  <h1>PSX stocks on YouTube</h1>
  <div class="sub" id="sub"></div>
  <div class="toolbar"><span class="lbl">Period</span><div class="seg" id="periods" role="group" aria-label="Period"></div></div>
  <div class="tiles" id="tiles"></div>
  <div class="grid">
    <div class="card"><h2 id="lineTitle">Daily videos mentioning the top 5 stocks</h2><div class="chart" id="line"></div></div>
    <div class="card"><h2>Buzz by sector</h2><div class="chart" id="sectors"></div></div>
  </div>
  <div class="card section">
    <h2>Sectors</h2>
    <div class="tablewrap"><table id="sectbl">
      <thead><tr>
        <th data-k="sector">Sector</th><th data-k="buzz" class="num">Buzz</th><th data-k="videos" class="num">Videos</th>
        <th data-k="direct_videos" class="num" title="Videos naming the sector itself, not just one of its stocks">Named</th>
        <th data-k="recent" class="num" title="Videos in the last 7 days (and the 7 days before)">7d (prev)</th><th data-k="trend">Trend</th>
        <th data-k="sentiment_score">Sentiment</th><th data-k="tone_change" title="Net tone, previous 7 days to last 7 days">Tone 7d</th><th data-k="call_score" title="What the channels called it: BUY/HOLD/SELL when one call has at least half of 3+ calls, MIXED otherwise">YouTube call</th>
        <th>Stocks mentioned</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">A sector counts every video that names it ("refineries", "OMCs", "سیمنٹ") or mentions one of its stocks.</div>
  </div>
  <div class="card">
    <h2>All stocks discussed</h2>
    <div class="toolbar">
      <input type="search" id="q" placeholder="Search symbol, name or sector" aria-label="Search stocks">
      <select id="fsec" aria-label="Sector"></select>
      <select id="fcall" aria-label="YouTube call">
        <option value="">All calls</option><option value="any">Any call</option>
        <option value="BUY">BUY</option><option value="HOLD">HOLD</option><option value="SELL">SELL</option>
        <option value="MIXED">MIXED</option>
      </select>
      <select id="fmin" aria-label="Minimum videos">
        <option value="1">1+ videos</option><option value="2">2+ videos</option><option value="3">3+ videos</option>
        <option value="5">5+ videos</option><option value="10">10+ videos</option>
      </select>
      <button type="button" id="freset" class="link">Reset</button>
      <span class="name" id="count"></span>
    </div>
    <div class="tablewrap"><table id="tbl">
      <thead><tr>
        <th data-k="symbol">Stock</th><th data-k="sector">Sector</th>
        <th data-k="buzz" class="num">Buzz</th><th data-k="videos" class="num">Videos</th>
        <th data-k="channel_count" class="num">Channels</th>
        <th data-k="recent" class="num" title="Videos in the last 7 days (and the 7 days before)">7d (prev)</th><th data-k="trend">Trend</th>
        <th data-k="sentiment_score">Sentiment</th><th data-k="tone_change" title="Net tone, previous 7 days to last 7 days">Tone 7d</th><th data-k="call_score" title="What the channels called it: BUY/HOLD/SELL when one call has at least half of 3+ calls, MIXED otherwise">YouTube call</th>
        <th data-k="views" class="num">Views</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">The grey line under each stock sums up its numbers for the chosen period. Click a row to see the videos. Buzz weights each video by its views and doubles it when the stock is in the title.
      Tone 7d compares net tone (−1 all bearish … +1 all bullish) in the last 7 days with the 7 before; it needs 3+ videos in each.
      YouTube call counts the videos that said buy, hold or sell about a stock: BUY, HOLD or SELL when one call has at least half
      of 3+ calls, MIXED otherwise. It reports what the tracked channels said, detected from keywords (English, Roman Urdu, Urdu);
      it is not a recommendation and not investment advice.</div>
  </div>
</main>
<script>
const ALL = __DATA__;  // {periods: {"7": compute() output, ...}, default: 90}
const PERIODS = Object.keys(ALL.periods).map(Number).sort((a, b) => a - b);
let DATA = null;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const signed = n => (n > 0 ? "+" : "") + n.toFixed(2);

function drawHeader() {
  document.getElementById("sub").textContent = `Last ${DATA.days} days: ${DATA.start} to ${DATA.end} · ` +
    `${DATA.channel_count} channels · ${DATA.video_count} videos · generated ${DATA.generated}`;
}

function drawTiles() {
  const S = DATA.stocks;
  const rising = S.filter(s => s.trend === "RISING" || s.trend === "NEW").sort((a, b) => b.recent - a.recent)[0];
  const mostBuy = S.filter(s => s.bullish > 0).sort((a, b) => b.bullish - a.bullish || b.call_score - a.call_score)[0];
  const mostSell = S.filter(s => s.bearish > 0).sort((a, b) => b.bearish - a.bearish || a.call_score - b.call_score)[0];
  const better = S.filter(s => s.tone_trend === "IMPROVING").sort((a, b) => b.tone_change - a.tone_change)[0];
  const worse = S.filter(s => s.tone_trend === "WORSENING").sort((a, b) => a.tone_change - b.tone_change)[0];
  const tiles = [
    ["Stocks discussed", S.length],
    ["Most discussed", S[0] ? S[0].symbol : "-"],
    ["Fastest rising (7d)", rising ? `${rising.symbol} (${rising.previous}→${rising.recent})` : "-"],
    ["Most buy calls", mostBuy ? `${mostBuy.symbol} (${mostBuy.bullish})` : "-"],
    ["Most sell calls", mostSell ? `${mostSell.symbol} (${mostSell.bearish})` : "-"],
    ["Tone improving most (7d)", better ? `${better.symbol} (${signed(better.tone_change)})` : "-"],
    ["Tone worsening most (7d)", worse ? `${worse.symbol} (${signed(worse.tone_change)})` : "-"],
  ];
  document.getElementById("tiles").innerHTML = tiles.map(([l, v]) =>
    `<div class="tile"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
}

// Charts are drawn here, with no library, so the page works offline and inside app previews.
function lineChart(el, dates, series) {
  const W = Math.max(280, el.clientWidth), H = 230, L = 30, R = 10, T = 10, B = 24;
  const max = Math.max(1, ...series.flatMap(s => s.data));
  const step = max <= 4 ? 1 : Math.ceil(max / 4), top = Math.ceil(max / step) * step;
  const x = i => L + (dates.length < 2 ? (W - L - R) / 2 : i * (W - L - R) / (dates.length - 1));
  const y = v => T + (H - T - B) * (1 - v / top);
  let svg = "";
  for (let v = 0; v <= top; v += step) {
    svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>` +
      `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  const ticks = Math.min(dates.length, Math.max(2, Math.floor((W - L - R) / 64)));
  const shown = new Set(Array.from({ length: ticks }, (_, k) => Math.round(k * (dates.length - 1) / Math.max(1, ticks - 1))));
  shown.forEach(i => { svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${dates[i].slice(5)}</text>`; });
  series.forEach(s => {
    svg += `<polyline fill="none" style="stroke:${s.color}" stroke-width="2" stroke-linejoin="round" ` +
      `points="${s.data.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>`;
    if (dates.length <= 31) s.data.forEach((v, i) => { svg += `<circle cx="${x(i)}" cy="${y(v)}" r="2.5" style="fill:${s.color}"/>`; });
  });
  const half = dates.length < 2 ? (W - L - R) / 2 : (W - L - R) / (dates.length - 1) / 2;
  dates.forEach((d, i) => {  // one invisible column per day; hovering it shows that day's counts
    const tip = `${d}: ` + series.map(s => `${s.label} ${s.data[i]}`).join(", ");
    svg += `<rect class="hit" x="${x(i) - half}" y="${T}" width="${2 * half}" height="${H - T - B}"><title>${esc(tip)}</title></rect>`;
  });
  el.innerHTML = `<div class="legend">${series.map(s =>
      `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join("")}</div>` +
    `<svg width="${W}" height="${H}" role="img" aria-label="Daily videos for ${series.map(s => esc(s.label)).join(", ")}">${svg}</svg>`;
}
function barChart(el, items) {
  const max = Math.max(1, ...items.map(s => s.buzz));
  el.innerHTML = items.map(s => `<div class="bar"><span class="bl" title="${esc(s.sector)}">${esc(s.sector)}</span>` +
    `<span class="bt"><span style="width:${(100 * s.buzz / max).toFixed(1)}%"></span></span><span class="bv">${s.buzz}</span></div>`
  ).join("") || `<p class="name">No sectors discussed in this period.</p>`;
}
// Over a month of daily counts (mostly 0-2) is just spikes, so longer periods are summed per week, ending today.
function weekly(dates, series) {
  const starts = [];
  for (let end = dates.length; end > 0; end -= 7) starts.unshift(Math.max(0, end - 7));
  return { dates: starts.map(i => dates[i]),
           series: series.map(s => ({ ...s, data: starts.map(i => s.data.slice(i, i + 7).reduce((a, b) => a + b, 0)) })) };
}
function drawCharts() {
  const colors = ["--s1", "--s2", "--s3", "--s4", "--s5"].map(v => `var(${v})`);
  let chart = { dates: DATA.dates,
                series: DATA.stocks.slice(0, 5).map((s, i) => ({ label: s.symbol, data: s.series, color: colors[i] })) };
  const byWeek = chart.dates.length > 31;
  if (byWeek) chart = weekly(chart.dates, chart.series);
  document.getElementById("lineTitle").textContent =
    `${byWeek ? "Weekly" : "Daily"} videos mentioning the top 5 stocks${byWeek ? " (week starting)" : ""}`;
  lineChart(document.getElementById("line"), chart.dates, chart.series);
  barChart(document.getElementById("sectors"), DATA.sectors.slice(0, 10));
}
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => DATA && drawCharts(), 150); });

function tone(s) {
  if (s.tone_change === null) {
    const one = s.tone_recent ?? s.tone_previous;
    return `<span class="tone d" title="Needs 3+ videos in each of the last two weeks">${one === null ? "–" : "too few videos"}</span>`;
  }
  return `<span class="tone" title="${signed(s.tone_previous)} → ${signed(s.tone_recent)}">` +
    `<span class="badge ${s.tone_trend}">${s.tone_trend}</span><div class="d">${signed(s.tone_previous)} → ${signed(s.tone_recent)}</div></span>`;
}
function callCell(s) {
  if (s.call === "-") return `<span class="tone d" title="Needs 3+ videos with a buy, hold or sell call">–</span>`;
  return `<span class="tone"><span class="badge ${s.call}">${s.call}</span>` +
    `<div class="d">${s.bullish} buy · ${s.hold} hold · ${s.bearish} sell</div></span>`;
}
function sbar(s) {
  const w = k => (100 * s[k] / s.videos).toFixed(0) + "%";
  return `<div class="sbar" title="${s.bullish} buy · ${s.hold} hold · ${s.bearish} sell · ${s.neutral - s.hold} just mentioned">` +
    `<span style="width:${w("bullish")};background:var(--bull)"></span>` +
    `<span style="width:${w("hold")};background:var(--hold)"></span>` +
    `<span style="width:${(100 * (s.neutral - s.hold) / s.videos).toFixed(0)}%;background:var(--neutral)"></span>` +
    `<span style="width:${w("bearish")};background:var(--bear)"></span></div>`;
}
function videoList(s) {
  return `<strong>Channels:</strong> ${s.channels.map(esc).join(", ")}<ul>` +
    s.top_videos.map(v => `<li>${v.published} · <a href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener">${esc(v.title)}</a>
      — ${esc(v.channel)} · ${fmt(v.views)} views
      <span class="${{buy: "pos", sell: "neg", hold: "holdc"}[v.call] || ""}">${v.call ? v.call + " call" : "mention"}</span></li>`).join("") +
    `</ul>`;
}

// A sortable table whose rows expand to show their videos. rows() is read on every render, so it follows the period.
function table({ id, rows, key, cells, empty, filter = () => true, onRender = () => {}, note = null }) {
  const el = document.getElementById(id), cols = el.querySelectorAll("thead th").length;
  let sortKey = "buzz", sortDir = -1;
  const open = new Set();
  function render() {
    const all = rows();
    const shown = all.filter(filter).sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || y === null) return (x === null) - (y === null);  // rows without a value always last
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    el.querySelector("tbody").innerHTML = shown.map(s =>
      `<tr class="row${note ? " has-note" : ""}" data-s="${esc(s[key])}">${cells(s)}</tr>` +
      (note ? `<tr class="row note" data-s="${esc(s[key])}"><td colspan="${cols}">${esc(note(s))}</td></tr>` : "") +
      (open.has(s[key]) ? `<tr class="detail"><td colspan="${cols}">${videoList(s)}</td></tr>` : "")
    ).join("") || `<tr><td colspan="${cols}">${empty}</td></tr>`;
    onRender(shown.length, all.length);
  }
  el.querySelector("tbody").addEventListener("click", e => {
    const tr = e.target.closest("tr.row"); if (!tr) return;
    const k = tr.dataset.s; open.has(k) ? open.delete(k) : open.add(k); render();
  });
  el.querySelectorAll("th[data-k]").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k; sortDir = sortKey === k ? -sortDir : -1; sortKey = k; render();
  }));
  return render;
}

const q = document.getElementById("q"), fsec = document.getElementById("fsec");
const fcall = document.getElementById("fcall"), fmin = document.getElementById("fmin");
function stockFilter(s) {
  const text = q.value.toLowerCase();
  if (text && !(s.symbol + " " + s.name + " " + s.sector).toLowerCase().includes(text)) return false;
  if (fsec.value && s.sector !== fsec.value) return false;
  if (fcall.value === "any" ? s.call === "-" : fcall.value && s.call !== fcall.value) return false;
  return s.videos >= Number(fmin.value);
}
const renderStocks = table({
  id: "tbl", rows: () => DATA.stocks, key: "symbol", empty: "No stocks match these filters in this period.",
  filter: stockFilter, note: s => s.summary,
  onRender: (shown, all) => { document.getElementById("count").textContent = `Showing ${shown} of ${all} stocks`; },
  cells: s => `<td><div class="sym">${esc(s.symbol)}</div><div class="name">${esc(s.name)}</div></td>
    <td>${esc(s.sector)}</td><td class="num">${s.buzz}</td><td class="num">${s.videos}</td>
    <td class="num">${s.channel_count}</td><td class="num">${s.recent} <span class="name">(${s.previous})</span></td>
    <td><span class="badge ${s.trend}">${s.trend}</span></td><td>${sbar(s)}</td><td>${tone(s)}</td><td>${callCell(s)}</td><td class="num">${fmt(s.views)}</td>`,
});
[q, fsec, fcall, fmin].forEach(el => el.addEventListener("input", renderStocks));
document.getElementById("freset").addEventListener("click", () => {
  q.value = ""; fsec.value = ""; fcall.value = ""; fmin.value = "1"; renderStocks();
});
const renderSectors = table({
  id: "sectbl", rows: () => DATA.sectors, key: "sector", empty: "No sectors discussed in this period.",
  cells: s => `<td class="sym">${esc(s.sector)}</td><td class="num">${s.buzz}</td><td class="num">${s.videos}</td>
    <td class="num">${s.direct_videos}</td><td class="num">${s.recent} <span class="name">(${s.previous})</span></td>
    <td><span class="badge ${s.trend}">${s.trend}</span></td><td>${sbar(s)}</td><td>${tone(s)}</td><td>${callCell(s)}</td>
    <td class="name">${s.stocks.map(esc).join(" ") || "–"}</td>`,
});

function fillSectors() {
  const keep = fsec.value, names = [...new Set(DATA.stocks.map(s => s.sector))].sort();
  fsec.innerHTML = `<option value="">All sectors</option>` + names.map(n => `<option>${esc(n)}</option>`).join("");
  fsec.value = names.includes(keep) ? keep : "";
}

const periodBox = document.getElementById("periods");
periodBox.innerHTML = PERIODS.map(d => `<button type="button" data-d="${d}">${d} days</button>`).join("");
function setPeriod(d) {
  DATA = ALL.periods[d];
  periodBox.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(Number(b.dataset.d) === d)));
  drawHeader(); drawTiles(); drawCharts(); fillSectors(); renderStocks(); renderSectors();
  try { history.replaceState(null, "", "#" + d); } catch (e) { /* e.g. inside a sandboxed preview */ }
}
periodBox.addEventListener("click", e => { const b = e.target.closest("button"); if (b) setPeriod(Number(b.dataset.d)); });
const fromLink = Number(location.hash.slice(1));
setPeriod(PERIODS.includes(fromLink) ? fromLink : ALL.default);
</script>
</body>
</html>
"""


def write_report(periods: dict[int, dict], path: str | Path, default: int) -> Path:
    """Dashboard with one dataset per look-back period (days -> compute() output), opening on `default`."""
    data = {"periods": {str(d): v for d, v in periods.items()}, "default": default}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path = Path(path)
    path.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    return path
