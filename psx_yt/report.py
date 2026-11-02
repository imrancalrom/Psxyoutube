"""Render trend data as a self-contained HTML dashboard."""

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
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
#tracktbl tr.few td { color: var(--muted); }
#tracktbl tr.total td { font-weight: 600; }
#logtbl td.vid { white-space: normal; min-width: 240px; max-width: 420px; }
#logtbl td.vid a { color: var(--accent); }
.calls { margin: 0 0 10px; }
.star { color: var(--hold); margin-right: 3px; }
#watchtbl tr.row td { vertical-align: top; }
.chsel { position: relative; }
.chsel summary { list-style: none; cursor: pointer; padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); font-size: 13px; white-space: nowrap; }
.chsel summary::-webkit-details-marker { display: none; }
.chsel summary::after { content: " ▾"; color: var(--muted); }
.chsel[data-on] summary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.chlist { position: absolute; z-index: 5; top: calc(100% + 4px); left: 0; min-width: 240px; max-width: calc(100vw - 32px);
  max-height: 60vh; overflow: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 6px 10px; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15); }
.chlist label { display: flex; gap: 8px; align-items: center; padding: 4px 0; font-size: 13px; cursor: pointer; }
.chlist label .name { margin-left: auto; padding-left: 12px; }
.chbtns { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 4px; }
@media (max-width: 600px) {
  .chsel { flex-basis: 100%; }
  .chlist { position: static; min-width: 0; max-width: none; margin-top: 4px; box-shadow: none; }
}
.digest { margin-bottom: 16px; }
.digest summary { cursor: pointer; line-height: 1.6; }
.digest h3 { font-size: 13px; margin: 12px 0 4px; }
.digest ul { margin: 0; padding-left: 18px; }
.digest li { margin: 2px 0; }
.dwrap { position: sticky; left: 8px; width: var(--wrapw, auto); max-width: var(--wrapw, none); }
.tv { margin: 4px 0 12px; }
.chip { display: inline-block; font-size: 11px; line-height: 1.5; padding: 0 7px; margin-left: 2px; border-radius: 99px;
  border: 1px solid var(--border); color: var(--text); background: var(--bg); white-space: nowrap; }
.sigs { margin: 0 0 6px; padding-left: 18px; font-size: 13px; }
.tvlinks { display: inline-flex; flex-wrap: wrap; gap: 4px 14px; }
.tvhead { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; justify-content: space-between; margin-bottom: 6px; }
.tv > .name { margin-top: 4px; }
.tsum { font-size: 13px; margin-bottom: 6px; }
.pchart svg { display: block; overflow: visible; }
.pchart svg text { fill: var(--muted); font-size: 11px; }
.pchart .grid { stroke: var(--border); } .pchart .dash { stroke-dasharray: 3 3; }
.pchart .ln { fill: none; stroke-width: 1.5; stroke-linejoin: round; }
.pchart .lvl { stroke-width: 1.2; stroke-dasharray: 6 4; }
.pchart .lvl.sup { stroke: var(--bull); } .pchart .lvl.res { stroke: var(--bear); }
.pchart text.sup { fill: var(--bull); } .pchart text.res { fill: var(--bear); }
.pchart .hit { fill: transparent; } .pchart .hit:hover { fill: var(--border); fill-opacity: 0.35; }
.legend i.sw { height: 0; border-top: 2px dashed; border-radius: 0; vertical-align: 3px; }
.legend i.sw.sup { border-color: var(--bull); } .legend i.sw.res { border-color: var(--bear); }
tr.has-note td { border-bottom: 0; padding-bottom: 2px; }
tr.note td { padding-top: 0; color: var(--muted); font-size: 12px; white-space: normal; }
tr.row.note:hover { background: none; }
</style>
</head>
<body>
<main>
  <h1>PSX stocks on YouTube</h1>
  <div class="sub" id="sub"></div>
  <details class="card digest" id="digest" open></details>
  <div class="toolbar"><span class="lbl">Period</span><div class="seg" id="periods" role="group" aria-label="Period"></div>
    <span class="lbl">Channels</span>
    <details class="chsel" id="chsel"><summary id="chsum">All channels</summary>
      <div class="chlist"><div class="chbtns"><button type="button" class="link" id="chall">All</button>
        <button type="button" class="link" id="chnone">None</button></div><div id="chboxes"></div></div>
    </details>
  </div>
  <div class="card section" id="watchcard">
    <h2>Your watchlist</h2>
    <div class="tablewrap"><table id="watchtbl">
      <thead><tr>
        <th>Stock</th><th class="num" title="Videos in the selected period">Videos</th>
        <th class="num" title="Videos in the last 7 days (and the 7 days before)">7d (prev)</th><th>Trend</th>
        <th title="Net tone, previous 7 days to last 7 days">Tone 7d</th><th>YouTube call</th>
        <th class="num" title="Latest daily close and its change on the day before (Yahoo Finance)">Last close</th>
        <th>Signals</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">The stocks in watchlist.txt / the WATCHLIST variable, for the selected period and channels. Click one to
      find it in the table below.</div>
  </div>
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
  <div class="card section" id="trackcard">
    <h2>Channel track record</h2>
    <div class="tablewrap"><table id="tracktbl">
      <thead><tr>
        <th>Channel</th><th class="num" title="Buy / sell calls on stocks with prices">Calls</th>
        <th class="num" title="Share of calls where the price went the called way after 5 trading days (calls scored)">Right after 5 days</th>
        <th class="num" title="Share of calls where the price went the called way after 20 trading days (calls scored)">Right after 20 days</th>
        <th class="num" title="Average 20-day price move in the called direction (a buy that rose 5% and a sell that fell 5% both count +5%)">Avg move, 20 days</th>
        <th class="num" title="That average minus the average move of all priced stocks over the same days">vs market</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">How each channel's buy and sell calls turned out. A call is entered at the close of the first trading day after the
      video, and scored 5 and 20 trading days later; "vs market" subtracts the average move of all priced stocks over the same
      days. Greyed rows have fewer than 5 scored calls: too few to read anything into. Calls are detected from keywords (hold
      calls have no direction and aren't scored), prices are Yahoo Finance daily closes, and past results don't predict future
      ones. Click a channel to see its calls: each result is the price move, green when it went the called way (a sell call
      followed by a fall is green). Covers all stored videos, whatever period is selected above.</div>
  </div>
  <div class="card section" id="logcard">
    <h2>Call log</h2>
    <div class="toolbar">
      <input type="search" id="lq" placeholder="Stock symbol" aria-label="Filter calls by stock">
      <select id="lch" aria-label="Channel"></select>
      <select id="lcall" aria-label="Call">
        <option value="">All calls</option><option value="buy">Buy</option><option value="sell">Sell</option>
        <option value="hold">Hold</option>
      </select>
      <button type="button" id="lreset" class="link">Reset</button>
      <span class="name" id="lcount"></span>
    </div>
    <div class="tablewrap"><table id="logtbl">
      <thead><tr>
        <th>Date</th><th>Stock</th><th>Call</th><th>Channel</th>
        <th class="num" title="Close on the first trading day after the video">Entry</th>
        <th class="num" title="Price move from the entry to the latest close; green when it went the called way">Since call</th>
        <th class="num" title="Price move 5 trading days after the entry">5 days</th>
        <th class="num" title="Price move 20 trading days after the entry">20 days</th>
        <th class="num" title="20-day move in the called direction minus the average move of all priced stocks">20d vs market</th>
        <th>Video</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">Every explicit buy, sell or hold call the tracked channels made, newest first, from all stored videos
      whatever period is selected above. Moves are price changes from Yahoo Finance daily closes, green when they went
      the called way (a fall after a sell call is green); hold calls have no direction. "–" means no prices for that stock
      or no trading day since the video. Calls are detected from keywords; not investment advice.</div>
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
      <select id="fsig" aria-label="Technical signal">
        <option value="">All signals</option><option value="any">Any signal</option><option value="near_support">Near support</option><option value="near_resistance">Near resistance</option><option value="range">Tight range</option><option value="oversold">RSI oversold</option><option value="overbought">RSI overbought</option><option value="golden_cross">Golden cross</option><option value="death_cross">Death cross</option><option value="high52">52-week high</option><option value="low52">52-week low</option>
      </select>
      <select id="fmin" aria-label="Minimum videos">
        <option value="1">1+ videos</option><option value="2">2+ videos</option><option value="3">3+ videos</option>
        <option value="5">5+ videos</option><option value="10">10+ videos</option>
      </select>
      <select id="fwatch" aria-label="Watchlist">
        <option value="">All stocks</option><option value="1">Watchlist only</option>
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
const WATCH = new Set((ALL.watchlist || []).map(w => w.symbol));  // stocks in watchlist.txt / $WATCHLIST
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const signed = n => (n > 0 ? "+" : "") + n.toFixed(2);

function drawDigest() {
  const d = ALL.digest, el = document.getElementById("digest");
  if (!d) { el.remove(); return; }
  el.innerHTML = `<summary><strong>${esc(d.title)}</strong> <span class="name">${esc(d.headline)}</span></summary>` +
    d.sections.map(s => `<h3>${esc(s.title)}</h3><ul>${s.items.map(i => `<li>${esc(i)}</li>`).join("")}</ul>`).join("") +
    `<div class="name">Always the latest run, whatever period is selected below. What the tracked channels said, detected
      from keywords; not investment advice.</div>`;
}
drawDigest();

// Call log: every explicit call, filterable; also used for the "Calls on this stock" list in an opened stock.
const LOG_PAGE = 50;
const CALLS = (ALL.track && ALL.track.calls) || [];
const callClass = c => ({buy: "pos", sell: "neg", hold: "holdc"}[c]);
// A price move, coloured by whether it went the called way (hold calls stay plain).
function moveCell(c, v) {
  if (v === null || v === undefined) return `<span class="name">–</span>`;
  const side = {buy: 1, sell: -1}[c.call] || 0, good = side * v > 0, bad = side * v < 0;
  return `<span class="${good ? "pos" : bad ? "neg" : ""}">${v > 0 ? "+" : ""}${v.toFixed(1)}%</span>`;
}
const pending = c => c.entry === null ? `<span class="name">–</span>` : `<span class="name">pending</span>`;
const horizonCell = (c, h) => c["move" + h] === null ? pending(c) : moveCell(c, c["move" + h]);
function vsMarket(c) {
  const h = ALL.track.horizons[1], side = {buy: 1, sell: -1}[c.call];
  if (!side || c["move" + h] === null || c["market" + h] === null) return `<span class="name">–</span>`;
  const x = side * (c["move" + h] - c["market" + h]);
  return `<span class="${x > 0 ? "pos" : x < 0 ? "neg" : ""}">${x > 0 ? "+" : ""}${x.toFixed(1)}%</span>`;
}
const videoLink = c =>
  `<a href="https://www.youtube.com/watch?v=${esc(c.video_id)}" target="_blank" rel="noopener">${esc(c.title)}</a>`;

function stockCalls(sym) {
  const mine = CALLS.filter(c => c.symbol === sym);
  if (!mine.length) return "";
  const [h1, h2] = ALL.track.horizons;
  return `<div class="calls"><strong>Calls on ${esc(sym)}</strong> <span class="name">(all stored videos)</span><ul>` +
    mine.map(c => `<li>${esc(c.published)} · <span class="${callClass(c.call)}">${c.call}</span> — ${esc(c.channel)} ·
      ${c.entry === null ? "no price yet" : `entry ${c.entry} · since call ${moveCell(c, c.now)} · ${h1}d ${horizonCell(c, h1)} ·
      ${h2}d ${horizonCell(c, h2)}`} · ${videoLink(c)}</li>`).join("") + `</ul></div>`;
}

function drawLog() {
  const card = document.getElementById("logcard");
  if (!CALLS.length) { card.remove(); return; }
  const el = document.getElementById("logtbl"), lq = document.getElementById("lq");
  const lch = document.getElementById("lch"), lcall = document.getElementById("lcall");
  const [h1, h2] = ALL.track.horizons;
  const channels = [...new Set(CALLS.map(c => c.channel))].sort();
  lch.innerHTML = `<option value="">All channels</option>` + channels.map(n => `<option>${esc(n)}</option>`).join("");
  let showAll = false;
  function render() {
    const text = lq.value.trim().toUpperCase();
    const shown = CALLS.filter(c => (!text || c.symbol.includes(text)) && (!lch.value || c.channel === lch.value) &&
                                    (!lcall.value || c.call === lcall.value));
    const page = showAll ? shown : shown.slice(0, LOG_PAGE);
    el.querySelector("tbody").innerHTML = page.map(c => `<tr>
        <td>${esc(c.published)}</td><td class="sym">${esc(c.symbol)}</td>
        <td><span class="badge ${c.call.toUpperCase()}">${c.call.toUpperCase()}</span></td><td>${esc(c.channel)}</td>
        <td class="num">${c.entry === null ? `<span class="name">–</span>` : `${c.entry} <span class="name">${esc(c.entry_date)}</span>`}</td>
        <td class="num">${moveCell(c, c.now)}</td><td class="num">${horizonCell(c, h1)}</td>
        <td class="num">${horizonCell(c, h2)}</td><td class="num">${vsMarket(c)}</td>
        <td class="vid">${videoLink(c)}</td></tr>`).join("") +
      (shown.length > page.length ? `<tr><td colspan="10"><button type="button" class="link" id="lmore">Show all
        ${shown.length} calls</button></td></tr>` : "") ||
      `<tr><td colspan="10">No calls match these filters.</td></tr>`;
    const n = {buy: 0, sell: 0, hold: 0};
    shown.forEach(c => n[c.call]++);
    document.getElementById("lcount").textContent =
      `${shown.length} of ${CALLS.length} calls · ${n.buy} buy, ${n.sell} sell, ${n.hold} hold`;
  }
  el.querySelector("tbody").addEventListener("click", e => { if (e.target.id === "lmore") { showAll = true; render(); } });
  [lq, lch, lcall].forEach(x => x.addEventListener("input", () => { showAll = false; render(); }));
  document.getElementById("lreset").addEventListener("click", () => {
    lq.value = ""; lch.value = ""; lcall.value = ""; showAll = false; render();
  });
  render();
}

// Channel track record: all stored calls, so it doesn't follow the period switch.
function drawTrack() {
  const T = ALL.track, el = document.getElementById("tracktbl");
  if (!T || !T.channels.length || !T.channels[0].calls) { document.getElementById("trackcard").remove(); return; }
  const [h1, h2] = T.horizons, open = new Set();
  const pct = (v, signed = true) => v === null || v === undefined ? "–" : `${signed && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
  const rate = (hit, n) => hit === null ? "–" : `${hit}% <span class="name">of ${n}</span>`;
  const tone = v => v === null || v === undefined ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
  function calls(channel) {
    const mine = T.calls.filter(c => c.call !== "hold" && c.entry !== null &&
                                     (channel === "All channels" || c.channel === channel));
    const res = (c, h) => c["move" + h] === null ? `<span class="name">pending</span>`
      : `<span class="${c["right" + h] ? "pos" : "neg"}">${pct(c["move" + h])}</span>`;
    return `<ul>${mine.map(c => `<li>${esc(c.published)} · <strong>${esc(c.symbol)}</strong>
      <span class="${c.call === "buy" ? "pos" : "neg"}">${c.call}</span> ·
      <a href="https://www.youtube.com/watch?v=${esc(c.video_id)}" target="_blank" rel="noopener">${esc(c.title)}</a>
      ${channel === "All channels" ? `— ${esc(c.channel)}` : ""} · entry ${c.entry} (${esc(c.entry_date)}) ·
      ${h1}d ${res(c, h1)} · ${h2}d ${res(c, h2)}</li>`).join("")}</ul>`;
  }
  function render() {
    el.querySelector("tbody").innerHTML = T.channels.map(r => {
      const few = r.channel !== "All channels" && !r.enough;
      return `<tr class="row${few ? " few" : ""}${r.channel === "All channels" ? " total" : ""}" data-s="${esc(r.channel)}">
        <td>${esc(r.channel)}${few ? ` <span class="name">few calls</span>` : ""}</td>
        <td class="num">${r.calls} <span class="name">(${r.buy} buy, ${r.sell} sell)</span></td>
        <td class="num">${rate(r["hit" + h1], r["n" + h1])}</td><td class="num">${rate(r["hit" + h2], r["n" + h2])}</td>
        <td class="num ${tone(r["avg" + h2])}">${pct(r["avg" + h2])}</td>
        <td class="num ${tone(r["excess" + h2])}">${pct(r["excess" + h2])}</td></tr>` +
        (open.has(r.channel) ? `<tr class="detail"><td colspan="6"><div class="dwrap">${calls(r.channel)}</div></td></tr>` : "");
    }).join("");
    fitDetails(el);
  }
  el.querySelector("tbody").addEventListener("click", e => {
    if (e.target.closest("a")) return;
    const tr = e.target.closest("tr.row"); if (!tr) return;
    const k = tr.dataset.s; open.has(k) ? open.delete(k) : open.add(k); render();
  });
  render();
}

function drawHeader() {
  document.getElementById("sub").textContent = `Last ${DATA.days} days: ${DATA.start} to ${DATA.end} · ` +
    `${DATA.channel_count} channel${DATA.channel_count === 1 ? "" : "s"} · ${DATA.video_count} videos · ` +
    `generated ${DATA.generated}` + captionNote() +
    (CHANS ? ` · filtered to ${CHANS.size} of ${CHANNELS.length} channels` : "");
}

// Most buy/sell calls are spoken, so say how much of the archive has had its captions read.
function captionNote() {
  const c = ALL.captions;
  if (!c || !c.total) return "";
  const pct = Math.round(100 * (c.read + c.none) / c.total);
  return ` · captions checked for ${pct}% of videos` + (c.waiting ? ` (${c.waiting} waiting)` : "");
}

function drawTiles() {
  const S = DATA.stocks;
  const rising = S.filter(s => s.trend === "RISING" || s.trend === "NEW").sort((a, b) => b.recent - a.recent)[0];
  const mostBuy = S.filter(s => s.buy_calls > 0).sort((a, b) => b.buy_calls - a.buy_calls || b.call_score - a.call_score)[0];
  const mostSell = S.filter(s => s.sell_calls > 0).sort((a, b) => b.sell_calls - a.sell_calls || a.call_score - b.call_score)[0];
  const better = S.filter(s => s.tone_trend === "IMPROVING").sort((a, b) => b.tone_change - a.tone_change)[0];
  const worse = S.filter(s => s.tone_trend === "WORSENING").sort((a, b) => a.tone_change - b.tone_change)[0];
  const tiles = [
    ["Stocks discussed", S.length],
    ["Most discussed", S[0] ? S[0].symbol : "-"],
    ["Fastest rising (7d)", rising ? `${rising.symbol} (${rising.previous}→${rising.recent})` : "-"],
    ["Most buy calls", mostBuy ? `${mostBuy.symbol} (${mostBuy.buy_calls})` : "-"],
    ["Most sell calls", mostSell ? `${mostSell.symbol} (${mostSell.sell_calls})` : "-"],
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
    `<div class="d">${s.buy_calls} buy · ${s.hold} hold · ${s.sell_calls} sell</div></span>`;
}
function sbar(s) {
  const w = k => (100 * s[k] / s.videos).toFixed(0) + "%";
  return `<div class="sbar" title="Tone: ${s.bullish} positive · ${s.neutral} neutral · ${s.bearish} negative">` +
    `<span style="width:${w("bullish")};background:var(--bull)"></span>` +
    `<span style="width:${w("neutral")};background:var(--neutral)"></span>` +
    `<span style="width:${w("bearish")};background:var(--bear)"></span></div>`;
}
const FIRST_VIDEOS = 10;
function videoList(s, showAll) {
  const refs = showAll ? s.v : s.v.slice(0, FIRST_VIDEOS);
  const more = s.v.length > FIRST_VIDEOS
    ? `<button type="button" class="link more">${showAll ? `Show the newest ${FIRST_VIDEOS}` : `Show all ${s.v.length} videos`}</button>` : "";
  return `<strong>Channels:</strong> ${s.channels.map(esc).join(", ")}` +
    `<div class="name">${s.v.length} video${s.v.length === 1 ? "" : "s"} in the last ${DATA.days} days, newest first</div><ul>` +
    refs.map(([id, call]) => {
      const [title, channel, published, views] = ALL.videos[id];
      return `<li>${published} · <a href="https://www.youtube.com/watch?v=${esc(id)}" target="_blank" rel="noopener">${esc(title)}</a>
      — ${esc(channel)} · ${fmt(views)} views
      <span class="${{buy: "pos", sell: "neg", hold: "holdc"}[call] || ""}">${call ? call + " call" : "mention"}</span></li>`;
    }).join("") + `</ul>${more}`;
}

// A sortable table whose rows expand to show their videos. rows() is read on every render, so it follows the period.
function table({ id, rows, key, cells, empty, filter = () => true, onRender = () => {}, note = null, extra = null }) {
  const el = document.getElementById(id), cols = el.querySelectorAll("thead th").length;
  let sortKey = "buzz", sortDir = -1;
  const open = new Set(), showAll = new Set();
  function render() {
    const all = rows();
    const shown = all.filter(filter).sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || y === null) return (x === null) - (y === null);  // rows without a value always last
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    el.querySelector("tbody").innerHTML = shown.map(s =>
      `<tr class="row${note ? " has-note" : ""}" data-s="${esc(s[key])}">${cells(s)}</tr>` +
      (note ? `<tr class="row note" data-s="${esc(s[key])}"><td colspan="${cols}">${note(s)}</td></tr>` : "") +
      (open.has(s[key]) ? `<tr class="detail" data-s="${esc(s[key])}"><td colspan="${cols}"><div class="dwrap">${extra ? extra(s) : ""}${videoList(s, showAll.has(s[key]))}</div></td></tr>` : "")
    ).join("") || `<tr><td colspan="${cols}">${empty}</td></tr>`;
    onRender(shown.length, all.length);
    fitDetails(el);
    loadCharts(el);
  }
  el.querySelector("tbody").addEventListener("click", e => {
    if (e.target.closest("a")) return;  // links (YouTube, TradingView) open without toggling the row
    const more = e.target.closest("button.more");
    if (more) { const k = more.closest("tr").dataset.s; showAll.has(k) ? showAll.delete(k) : showAll.add(k); render(); return; }
    const tr = e.target.closest("tr.row"); if (!tr) return;
    const k = tr.dataset.s; open.has(k) ? open.delete(k) : open.add(k); render();
  });
  el.querySelectorAll("th[data-k]").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k; sortDir = sortKey === k ? -sortDir : -1; sortKey = k; render();
  }));
  return render;
}

// Price section of an opened stock: our own technical chart when the daily run fetched prices (works offline),
// otherwise TradingView's chart. The TradingView link is always there.
const tvPage = sym => `https://www.tradingview.com/symbols/PSX-${encodeURIComponent(sym)}/`;
const tvChart = sym => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent("PSX:" + sym)}`;
function tradingView(s) {
  const t = ALL.tech[s.symbol];
  const links = `<a href="${tvChart(s.symbol)}" target="_blank" rel="noopener">Open chart on TradingView ↗</a>
      <a href="${tvPage(s.symbol)}" target="_blank" rel="noopener">Overview ↗</a>`;
  const head = `<div class="tvhead"><strong>${esc(s.symbol)} price${t ? ` · last close ${esc(t.date)}` : ""}</strong>
      <span class="tvlinks">${links}</span></div>`;
  if (!t) return `<div class="tv">${head}
    <div class="name">TradingView's embeddable chart doesn't carry PSX stocks (it shows a different company instead), so the
      chart opens on TradingView's own site, which has PSX:${esc(s.symbol)} with all its indicators: add Pivot Points
      Standard for support/resistance, Moving Average (50, 200), RSI and MACD from its Indicators menu.</div></div>`;
  const sigs = (t.signals || []).length
    ? `<ul class="sigs">${t.signals.map(g => `<li><strong>${esc(g.label)}</strong>: ${esc(g.detail)}</li>`).join("")}</ul>` : "";
  return `<div class="tv">${head}<div class="tsum">${esc(t.summary)}</div>${sigs}
    <div class="pchart" data-symbol="${esc(s.symbol)}"></div>
    <div class="name">Daily closes for the last ${t.chart.dates.length} trading days with SMA 50 and SMA 200; dashed lines are support
      (green) and resistance (red) from swing highs/lows over the past year, with how many times price touched them; lower
      panel RSI 14 (30/70 bands). Prices: Yahoo Finance (${esc(s.symbol)}.KA), daily closes. Calculated mechanically; not advice.</div></div>`;
}
function priceChart(box, t) {
  const c = t.chart, n = c.close.length;
  const W = Math.max(300, box.clientWidth), PH = 220, GAP = 16, RH = 70, L = 8, R = 92, T = 8, B = 20;
  const H = T + PH + GAP + RH + B;
  const lvls = [...t.support.map(l => ({ ...l, kind: "S" })), ...t.resistance.map(l => ({ ...l, kind: "R" }))];
  const vals = [...c.close, ...c.sma50, ...c.sma200, ...lvls.map(l => l.price)].filter(v => v !== null);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.04 || hi * 0.02; lo -= pad; hi += pad;
  const x = i => L + (n < 2 ? 0 : i * (W - L - R) / (n - 1));
  const y = v => T + PH * (1 - (v - lo) / (hi - lo));
  const ry = v => T + PH + GAP + RH * (1 - v / 100);
  const path = (arr, yf) => { let d = "", pen = false;
    arr.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${yf(v).toFixed(1)}`; pen = true; });
    return d; };
  // Level labels sit on the right axis: keep them at least 13px apart, and drop grid labels they would cover.
  const labelY = [];
  [...lvls].sort((a, b) => y(a.price) - y(b.price)).forEach(l => {
    let ly = y(l.price) - 3;
    if (labelY.length && ly - labelY[labelY.length - 1].y < 13) ly = labelY[labelY.length - 1].y + 13;
    labelY.push({ l, y: ly });
  });
  let svg = "";
  for (let k = 0; k <= 4; k++) {  // price grid
    const v = lo + (hi - lo) * k / 4, gy = y(v) + 4;
    svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`;
    if (labelY.every(p => Math.abs(p.y - gy) >= 12)) svg += `<text x="${W - R + 6}" y="${gy}">${v.toFixed(v < 100 ? 2 : 0)}</text>`;
  }
  [30, 70].forEach(v => { svg += `<line class="grid dash" x1="${L}" x2="${W - R}" y1="${ry(v)}" y2="${ry(v)}"/><text x="${W - R + 6}" y="${ry(v) + 4}">${v}</text>`; });
  svg += `<text x="${L}" y="${T + PH + GAP - 3}">RSI 14</text>`;
  let lastMonth = "";  // month labels along the bottom
  c.dates.forEach((d, i) => { const m = d.slice(0, 7); if (m !== lastMonth) { if (lastMonth && x(i) < W - R - 20) svg += `<text x="${x(i)}" y="${H - 5}" text-anchor="middle">${new Date(d + "T00:00:00Z").toLocaleString("en", { month: "short", timeZone: "UTC" })}</text>`; lastMonth = m; } });
  labelY.forEach(({ l, y: ly }) => {
    const cls = l.kind === "S" ? "sup" : "res";
    svg += `<line class="lvl ${cls}" x1="${L}" x2="${W - R}" y1="${y(l.price)}" y2="${y(l.price)}"/>` +
      `<text class="${cls}" x="${W - R + 6}" y="${ly}">${l.kind} ${l.price} (${l.touches}×)</text>`;
  });
  svg += `<path d="${path(c.sma200, y)}" class="ln" style="stroke:var(--s4)"/>` +
         `<path d="${path(c.sma50, y)}" class="ln" style="stroke:var(--s2)"/>` +
         `<path d="${path(c.close, y)}" class="ln" style="stroke:var(--accent);stroke-width:2"/>` +
         `<path d="${path(c.rsi14, ry)}" class="ln" style="stroke:var(--s3)"/>`;
  const half = n < 2 ? 4 : (W - L - R) / (n - 1) / 2;
  c.dates.forEach((d, i) => {
    const f = v => v === null ? "–" : v;
    svg += `<rect class="hit" x="${x(i) - half}" y="${T}" width="${2 * half}" height="${PH + GAP + RH}"><title>${d}: close ${c.close[i]} · SMA 50 ${f(c.sma50[i])} · SMA 200 ${f(c.sma200[i])} · RSI ${f(c.rsi14[i])}</title></rect>`;
  });
  box.innerHTML = `<div class="legend"><span><i style="background:var(--accent)"></i>Close</span><span><i style="background:var(--s2)"></i>SMA 50</span>` +
    `<span><i style="background:var(--s4)"></i>SMA 200</span><span><i style="background:var(--s3)"></i>RSI 14</span>` +
    `<span><i class="sw sup"></i>Support</span><span><i class="sw res"></i>Resistance</span></div>` +
    `<svg width="${W}" height="${H}" role="img" aria-label="${esc(t.summary)}">${svg}</svg>`;
}
// A row's detail spans the whole (possibly wider than the screen) table, so pin its content to the visible width.
function fitDetails(tbl) {
  tbl.style.setProperty("--wrapw", Math.max(260, tbl.parentElement.clientWidth - 16) + "px");
}
window.addEventListener("resize", () => document.querySelectorAll("#tbl, #sectbl").forEach(fitDetails));
function loadCharts(root) {
  root.querySelectorAll(".pchart:not([data-drawn])").forEach(box => {
    box.dataset.drawn = "1";
    priceChart(box, ALL.tech[box.dataset.symbol]);
  });
}

const q = document.getElementById("q"), fsec = document.getElementById("fsec");
const fcall = document.getElementById("fcall"), fmin = document.getElementById("fmin"), fsig = document.getElementById("fsig");
const fwatch = document.getElementById("fwatch");
if (!WATCH.size) fwatch.remove();
// Technical signals from daily closes (support/resistance, RSI, crosses, 52-week range).
const signalsOf = sym => (ALL.tech[sym] && ALL.tech[sym].signals) || [];
const signalChips = sym => signalsOf(sym).map(g => ` <span class="chip" title="${esc(g.detail)}">${esc(g.label)}</span>`).join("");
function stockFilter(s) {
  const text = q.value.toLowerCase();
  if (text && !(s.symbol + " " + s.name + " " + s.sector).toLowerCase().includes(text)) return false;
  if (fsec.value && s.sector !== fsec.value) return false;
  if (fcall.value === "any" ? s.call === "-" : fcall.value && s.call !== fcall.value) return false;
  const kinds = signalsOf(s.symbol).map(g => g.kind);
  if (fsig.value === "any" ? !kinds.length : fsig.value && !kinds.includes(fsig.value)) return false;
  if (fwatch.value && !WATCH.has(s.symbol)) return false;
  return s.videos >= Number(fmin.value);
}
const renderStocks = table({
  id: "tbl", rows: () => DATA.stocks, key: "symbol", empty: "No stocks match these filters in this period.",
  filter: stockFilter, note: s => esc(s.summary) + signalChips(s.symbol), extra: s => tradingView(s) + stockCalls(s.symbol),
  onRender: (shown, all) => { document.getElementById("count").textContent = `Showing ${shown} of ${all} stocks`; },
  cells: s => `<td><div class="sym">${WATCH.has(s.symbol) ? `<span class="star" title="On your watchlist">★</span>` : ""}${esc(s.symbol)}</div><div class="name">${esc(s.name)}</div></td>
    <td>${esc(s.sector)}</td><td class="num">${s.buzz}</td><td class="num">${s.videos}</td>
    <td class="num">${s.channel_count}</td><td class="num">${s.recent} <span class="name">(${s.previous})</span></td>
    <td><span class="badge ${s.trend}">${s.trend}</span></td><td>${sbar(s)}</td><td>${tone(s)}</td><td>${callCell(s)}</td><td class="num">${fmt(s.views)}</td>`,
});
[q, fsec, fcall, fsig, fmin, fwatch].forEach(el => el.addEventListener("input", renderStocks));
document.getElementById("freset").addEventListener("click", () => {
  q.value = ""; fsec.value = ""; fcall.value = ""; fsig.value = ""; fmin.value = "1"; fwatch.value = ""; renderStocks();
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

// Channel filter: stock and sector figures are rebuilt in the browser from the selected channels' videos, with the
// same rules as psx_yt/trends.py. The track record, call log and digest are not filtered by it.
const LONGEST = ALL.periods[Math.max(...PERIODS)];  // its video lists cover the two weeks the 7d numbers need
const CHANNELS = Object.keys(LONGEST.channel_videos || {}).sort((a, b) => a.localeCompare(b));
let CHANS = null;  // null = every channel
const round2 = x => Math.round(x * 100) / 100;
const dayDiff = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 864e5);
function trendLabel(recent, previous) {
  if (!recent && !previous) return "QUIET";
  if (!previous) return "NEW";
  const r = recent / previous;
  return r >= 1.5 && recent >= 2 ? "RISING" : r <= 0.67 ? "FALLING" : "STEADY";
}
function toneLabel(recent, previous) {
  if (recent === null || previous === null) return "-";
  const c = recent - previous;
  return c >= 0.25 ? "IMPROVING" : c <= -0.25 ? "WORSENING" : "STABLE";
}
function callLabel(buy, hold, sell, min = 3) {
  const n = buy + hold + sell;
  if (n < min) return "-";
  const r = [["BUY", buy], ["HOLD", hold], ["SELL", sell]].sort((a, b) => b[1] - a[1]);
  return r[0][1] * 2 >= n && r[0][1] > r[1][1] ? r[0][0] : "MIXED";
}
function summaryLine(a) {
  const n = (c, w) => `${c} ${w}${c === 1 ? "" : "s"}`;
  const coverage = n(a.videos, "video") + (a.channel_count === 1 ? " on 1 channel only" : ` on ${a.channel_count} channels`);
  const momentum = {
    NEW: a.recent === a.videos ? `new this week (${a.recent})` : `${a.recent} this week, none the week before`,
    RISING: `buzz rising (${a.previous}→${a.recent} a week)`, FALLING: `buzz fading (${a.previous}→${a.recent} a week)`,
    STEADY: `steady (${a.recent} this week)`, QUIET: "quiet in the last two weeks",
  }[a.trend];
  const counts = [[a.buy_calls, "buy"], [a.hold, "hold"], [a.sell_calls, "sell"]].filter(([c]) => c)
    .map(([c, w]) => `${c} ${w}`).join(", ");
  const calls = {BUY: `channels lean BUY (${counts})`, SELL: `channels lean SELL (${counts})`,
    HOLD: `mostly HOLD calls (${counts})`, MIXED: `calls split: ${counts}`}[a.call]
    || (counts ? `few calls so far (${counts})` : "no buy/sell calls yet");
  const parts = [coverage, momentum, calls];
  if (a.tone_trend === "IMPROVING") parts.push("tone improving");
  else if (a.tone_trend === "WORSENING") parts.push("tone turning bearish");
  return parts.join(" · ");
}
function aggregate(items, longest, keyName, d) {
  const idx = Object.fromEntries(d.dates.map((x, i) => [x, i]));
  const longBy = new Map(longest.map(x => [x[keyName], x]));
  const out = [];
  for (const it of items) {
    const refs = it.v.filter(r => CHANS.has(ALL.videos[r[0]][1]));
    if (!refs.length) continue;
    const a = {...it, v: refs, videos: refs.length, views: 0, buzz: 0, bullish: 0, bearish: 0, neutral: 0,
               buy_calls: 0, sell_calls: 0, hold: 0};
    const ch = new Set(), series = d.dates.map(() => 0);
    let direct = 0;
    for (const [id, call, tone, inTitle, dir] of refs) {
      const [, channel, published, views] = ALL.videos[id];
      a.views += views;
      a.buzz += (inTitle ? 2 : 1) * (1 + Math.log10(1 + views));
      a[tone > 0 ? "bullish" : tone < 0 ? "bearish" : "neutral"]++;
      if (call === "buy") a.buy_calls++; else if (call === "sell") a.sell_calls++; else if (call === "hold") a.hold++;
      ch.add(channel);
      if (published in idx) series[idx[published]]++;
      direct += dir ? 1 : 0;
    }
    a.channels = [...ch].sort();
    a.channel_count = ch.size;
    a.buzz = Math.round(a.buzz * 10) / 10;
    a.sentiment_score = round2((a.bullish - a.bearish) / a.videos);
    a.call = callLabel(a.buy_calls, a.hold, a.sell_calls);
    const calls = a.buy_calls + a.hold + a.sell_calls;
    a.call_score = a.call !== "-" ? round2((a.buy_calls - a.sell_calls) / calls) : null;
    const w = [0, 0, 0, 0], long = longBy.get(it[keyName]);  // recent, previous, net tone recent, net tone previous
    for (const [id, , tone] of long ? long.v : []) {
      const [, channel, published] = ALL.videos[id];
      if (!CHANS.has(channel)) continue;
      const age = dayDiff(d.end, published);
      if (age >= 0 && age < 2 * d.window) { const k = age < d.window ? 0 : 1; w[k]++; w[k + 2] += Math.sign(tone); }
    }
    [a.recent, a.previous] = w;
    a.trend = trendLabel(a.recent, a.previous);
    a.tone_recent = w[0] >= 3 ? round2(w[2] / w[0]) : null;
    a.tone_previous = w[1] >= 3 ? round2(w[3] / w[1]) : null;
    a.tone_change = a.tone_recent !== null && a.tone_previous !== null ? round2(a.tone_recent - a.tone_previous) : null;
    a.tone_trend = toneLabel(a.tone_recent, a.tone_previous);
    a.series = series;
    if (keyName === "sector") a.direct_videos = direct;
    a.summary = summaryLine(a);
    out.push(a);
  }
  return out.sort((x, y) => y.buzz - x.buzz);
}
function derive(d) {
  const stocks = aggregate(d.stocks, LONGEST.stocks, "symbol", d);
  const sectors = aggregate(d.sectors, LONGEST.sectors, "sector", d);
  for (const sec of sectors) {
    sec.stocks = stocks.filter(s => s.sector === sec.sector).sort((a, b) => b.videos - a.videos).slice(0, 8).map(s => s.symbol);
  }
  const counts = d.channel_videos || {};
  return {...d, stocks, sectors, channel_count: CHANS.size,
          video_count: [...CHANS].reduce((n, c) => n + (counts[c] || 0), 0)};
}
function drawChannelPicker() {
  const box = document.getElementById("chboxes"), sel = document.getElementById("chsel");
  if (!CHANNELS.length) { sel.remove(); return; }
  box.innerHTML = CHANNELS.map(c => `<label><input type="checkbox" value="${esc(c)}" checked> ${esc(c)}
    <span class="name">${LONGEST.channel_videos[c]}</span></label>`).join("");
  const apply = () => {
    const on = [...box.querySelectorAll("input:checked")].map(i => i.value);
    CHANS = on.length === CHANNELS.length ? null : new Set(on);
    document.getElementById("chsum").textContent = !CHANS ? "All channels"
      : on.length === 1 ? on[0] : `${on.length} of ${CHANNELS.length} channels`;
    CHANS ? sel.setAttribute("data-on", "") : sel.removeAttribute("data-on");
    setPeriod(DAYS);
  };
  box.addEventListener("change", apply);
  const all = v => () => { box.querySelectorAll("input").forEach(i => { i.checked = v; }); apply(); };
  document.getElementById("chall").addEventListener("click", all(true));
  document.getElementById("chnone").addEventListener("click", all(false));
  document.addEventListener("click", e => { if (!sel.contains(e.target)) sel.removeAttribute("open"); });
}

// Watchlist: the stocks listed in watchlist.txt / $WATCHLIST, first on the page; follows the period and channels.
function drawWatch() {
  const card = document.getElementById("watchcard");
  if (!WATCH.size) { card.remove(); return; }
  const by = new Map(DATA.stocks.map(s => [s.symbol, s]));
  card.querySelector("tbody").innerHTML = ALL.watchlist.map(w => {
    const s = by.get(w.symbol), t = ALL.tech[w.symbol];
    const price = t ? `${t.close.toLocaleString(undefined, {maximumFractionDigits: 2})}
      <span class="${t.change_pct > 0 ? "pos" : t.change_pct < 0 ? "neg" : "name"}">${t.change_pct > 0 ? "+" : ""}${t.change_pct.toFixed(1)}%</span>
      <div class="name">${esc(t.date)}</div>` : `<span class="name">–</span>`;
    const head = `<td><div class="sym">${esc(w.symbol)}</div><div class="name">${esc(w.name)}</div></td>`;
    const body = s ? `<td class="num">${s.videos}</td><td class="num">${s.recent} <span class="name">(${s.previous})</span></td>
        <td><span class="badge ${s.trend}">${s.trend}</span></td><td>${tone(s)}</td><td>${callCell(s)}</td>`
      : `<td class="num">0</td><td colspan="4" class="name">No videos in this period${CHANS ? " from these channels" : ""}</td>`;
    return `<tr class="row" data-s="${esc(w.symbol)}">${head}${body}<td class="num">${price}</td>
      <td>${signalChips(w.symbol) || `<span class="name">–</span>`}</td></tr>`;
  }).join("");
}
document.getElementById("watchtbl").addEventListener("click", e => {
  const tr = e.target.closest("tr.row"); if (!tr) return;
  q.value = tr.dataset.s; fwatch.value = ""; renderStocks();
  document.getElementById("tbl").scrollIntoView({behavior: "smooth", block: "start"});
});

const periodBox = document.getElementById("periods");
periodBox.innerHTML = PERIODS.map(d => `<button type="button" data-d="${d}">${d} days</button>`).join("");
let DAYS = ALL.default;
function setPeriod(d) {
  DAYS = d;
  DATA = CHANS ? derive(ALL.periods[d]) : ALL.periods[d];
  periodBox.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(Number(b.dataset.d) === d)));
  drawHeader(); drawWatch(); drawTiles(); drawCharts(); fillSectors(); renderStocks(); renderSectors();
  try { history.replaceState(null, "", "#" + d); } catch (e) { /* e.g. inside a sandboxed preview */ }
}
periodBox.addEventListener("click", e => { const b = e.target.closest("button"); if (b) setPeriod(Number(b.dataset.d)); });
const fromLink = Number(location.hash.slice(1));
drawChannelPicker();
setPeriod(PERIODS.includes(fromLink) ? fromLink : ALL.default);
drawTrack();
drawLog();
</script>
</body>
</html>
"""


def write_report(periods: dict[int, dict], path: str | Path, default: int, tech: dict | None = None,
                 digest: dict | None = None, track: dict | None = None, captions: dict | None = None,
                 watchlist: list[dict] | None = None) -> Path:
    """Dashboard with one dataset per look-back period (days -> compute() output), opening on `default`.
    `tech` maps symbols to prices.technicals() output for the price charts."""
    # Each video's details are stored once; stocks and sectors in every period refer to them by id.
    videos: dict[str, list] = {}

    def compact(item: dict) -> dict:
        refs = []
        for v in item["video_list"]:
            videos[v["id"]] = [v["title"], v["channel"], v["published"], v["views"]]
            refs.append([v["id"], v["call"], v["sentiment"], v["in_title"], v["direct"]])
        return {**{k: x for k, x in item.items() if k != "video_list"}, "v": refs}

    data = {"periods": {str(d): {**p, "stocks": [compact(x) for x in p["stocks"]],
                                 "sectors": [compact(x) for x in p["sectors"]]} for d, p in periods.items()},
            "default": default, "videos": videos, "tech": tech or {}, "digest": digest, "track": track,
            "captions": captions, "watchlist": watchlist or []}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path = Path(path)
    path.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    return path
