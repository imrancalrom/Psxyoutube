"""Render trend data as a self-contained HTML dashboard."""

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PSX YouTube Buzz</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1d1b; --muted: #6b6b66; --border: #e3e2dc;
  --accent: #2563eb; --bull: #15803d; --bear: #b91c1c; --neutral: #a8a29e;
  --s1: #2563eb; --s2: #d97706; --s3: #0d9488; --s4: #9333ea; --s5: #db2777;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #141413; --surface: #1e1e1c; --text: #ecebe6; --muted: #9c9a92; --border: #33322e;
    --accent: #60a5fa; --bull: #4ade80; --bear: #f87171; --neutral: #78716c;
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
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.tile, .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tile .v { font-size: 22px; font-weight: 600; }
.tile .l { color: var(--muted); font-size: 12px; }
.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
.chart { position: relative; height: 280px; }
input[type=search] { width: 100%; max-width: 320px; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--bg); color: var(--text); margin-bottom: 12px; }
.tablewrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--muted); font-weight: 500; font-size: 12px; cursor: pointer; user-select: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.row { cursor: pointer; }
tr.row:hover { background: var(--bg); }
.sym { font-weight: 600; }
.name { color: var(--muted); font-size: 12px; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 99px; border: 1px solid currentColor; }
.RISING, .NEW, .IMPROVING { color: var(--bull); } .FALLING, .WORSENING { color: var(--bear); }
.STEADY, .QUIET, .STABLE { color: var(--muted); }
.tone { font-size: 12px; } .tone .d { color: var(--muted); margin-top: 2px; }
.sbar { display: flex; width: 110px; height: 8px; border-radius: 4px; overflow: hidden; background: var(--border); }
.sbar span { display: block; height: 100%; }
.detail td { white-space: normal; background: var(--bg); }
.detail ul { margin: 4px 0; padding-left: 18px; }
.detail a { color: var(--accent); }
.pos { color: var(--bull); } .neg { color: var(--bear); }
.foot { color: var(--muted); font-size: 12px; margin-top: 16px; }
.section { margin-bottom: 16px; }
</style>
</head>
<body>
<main>
  <h1>PSX stocks on YouTube</h1>
  <div class="sub" id="sub"></div>
  <div class="tiles" id="tiles"></div>
  <div class="grid">
    <div class="card"><h2>Daily videos mentioning the top 5 stocks</h2><div class="chart"><canvas id="line"></canvas></div></div>
    <div class="card"><h2>Buzz by sector</h2><div class="chart"><canvas id="sectors"></canvas></div></div>
  </div>
  <div class="card section">
    <h2>Sectors</h2>
    <div class="tablewrap"><table id="sectbl">
      <thead><tr>
        <th data-k="sector">Sector</th><th data-k="buzz" class="num">Buzz</th><th data-k="videos" class="num">Videos</th>
        <th data-k="direct_videos" class="num" title="Videos naming the sector itself, not just one of its stocks">Named</th>
        <th data-k="recent" class="num">Last 7d</th><th data-k="previous" class="num">Prev 7d</th><th data-k="trend">Trend</th>
        <th data-k="sentiment_score">Sentiment</th><th data-k="tone_change" title="Net tone, previous 7 days to last 7 days">Tone 7d</th>
        <th>Stocks mentioned</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">A sector counts every video that names it ("refineries", "OMCs", "سیمنٹ") or mentions one of its stocks.</div>
  </div>
  <div class="card">
    <h2>All stocks discussed</h2>
    <input type="search" id="q" placeholder="Filter by symbol, name or sector">
    <div class="tablewrap"><table id="tbl">
      <thead><tr>
        <th data-k="symbol">Stock</th><th data-k="sector">Sector</th>
        <th data-k="buzz" class="num">Buzz</th><th data-k="videos" class="num">Videos</th>
        <th data-k="channel_count" class="num">Channels</th><th data-k="recent" class="num">Last 7d</th>
        <th data-k="previous" class="num">Prev 7d</th><th data-k="trend">Trend</th>
        <th data-k="sentiment_score">Sentiment</th><th data-k="tone_change" title="Net tone, previous 7 days to last 7 days">Tone 7d</th>
        <th data-k="views" class="num">Views</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="foot">Click a row to see the videos. Buzz weights each video by its views and doubles it when the stock is in the title.
      Tone 7d compares net tone (−1 all bearish … +1 all bullish) in the last 7 days with the 7 before; it needs 3+ videos in each.
      Sentiment is keyword based (English, Roman Urdu, Urdu) and is a rough guide, not investment advice.</div>
  </div>
</main>
<script>
const DATA = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

document.getElementById("sub").textContent =
  `${DATA.start} to ${DATA.end} · ${DATA.channel_count} channels · ${DATA.video_count} videos · generated ${DATA.generated}`;

const S = DATA.stocks;
const rising = S.filter(s => s.trend === "RISING" || s.trend === "NEW").sort((a, b) => b.recent - a.recent)[0];
const bull = S.filter(s => s.videos >= 2).sort((a, b) => b.sentiment_score - a.sentiment_score)[0];
const better = S.filter(s => s.tone_trend === "IMPROVING").sort((a, b) => b.tone_change - a.tone_change)[0];
const worse = S.filter(s => s.tone_trend === "WORSENING").sort((a, b) => a.tone_change - b.tone_change)[0];
const signed = n => (n > 0 ? "+" : "") + n.toFixed(2);
const tiles = [
  ["Stocks discussed", S.length],
  ["Most discussed", S[0] ? S[0].symbol : "-"],
  ["Fastest rising (7d)", rising ? `${rising.symbol} (${rising.previous}→${rising.recent})` : "-"],
  ["Most bullish (2+ videos)", bull ? `${bull.symbol} (${signed(bull.sentiment_score)})` : "-"],
  ["Tone improving most (7d)", better ? `${better.symbol} (${signed(better.tone_change)})` : "-"],
  ["Tone worsening most (7d)", worse ? `${worse.symbol} (${signed(worse.tone_change)})` : "-"],
];
document.getElementById("tiles").innerHTML = tiles.map(([l, v]) =>
  `<div class="tile"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");

if (window.Chart) {
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--border");
  const palette = ["--s1", "--s2", "--s3", "--s4", "--s5"].map(css);
  new Chart(document.getElementById("line"), {
    type: "line",
    data: { labels: DATA.dates.map(d => d.slice(5)),
            datasets: S.slice(0, 5).map((s, i) => ({ label: s.symbol, data: s.series, borderColor: palette[i],
              backgroundColor: palette[i], tension: 0.3, pointRadius: 0, borderWidth: 2 })) },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
               scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
  });
  const sec = DATA.sectors.slice(0, 10);
  new Chart(document.getElementById("sectors"), {
    type: "bar",
    data: { labels: sec.map(s => s.sector), datasets: [{ label: "Buzz", data: sec.map(s => s.buzz),
            backgroundColor: css("--accent"), borderRadius: 4 }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } } },
  });
} else {
  document.querySelectorAll(".chart").forEach(el => {
    el.innerHTML = '<p class="name">Charts need an internet connection to load Chart.js.</p>';
  });
}

function tone(s) {
  if (s.tone_change === null) {
    const one = s.tone_recent ?? s.tone_previous;
    return `<span class="tone d" title="Needs 3+ videos in each of the last two weeks">${one === null ? "–" : "too few videos"}</span>`;
  }
  return `<span class="tone" title="${signed(s.tone_previous)} → ${signed(s.tone_recent)}">` +
    `<span class="badge ${s.tone_trend}">${s.tone_trend}</span><div class="d">${signed(s.tone_previous)} → ${signed(s.tone_recent)}</div></span>`;
}
function sbar(s) {
  const w = k => (100 * s[k] / s.videos).toFixed(0) + "%";
  return `<div class="sbar" title="${s.bullish} bullish · ${s.neutral} neutral · ${s.bearish} bearish">` +
    `<span style="width:${w("bullish")};background:var(--bull)"></span>` +
    `<span style="width:${w("neutral")};background:var(--neutral)"></span>` +
    `<span style="width:${w("bearish")};background:var(--bear)"></span></div>`;
}
function videoList(s) {
  return `<strong>Channels:</strong> ${s.channels.map(esc).join(", ")}<ul>` +
    s.top_videos.map(v => `<li>${v.published} · <a href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener">${esc(v.title)}</a>
      — ${esc(v.channel)} · ${fmt(v.views)} views
      <span class="${v.sentiment > 0 ? "pos" : v.sentiment < 0 ? "neg" : ""}">${v.sentiment > 0 ? "bullish" : v.sentiment < 0 ? "bearish" : "neutral"}</span></li>`).join("") +
    `</ul>`;
}

// A sortable table whose rows expand to show their videos.
function table({ id, rows, key, cells, empty, filter = () => true }) {
  const el = document.getElementById(id), cols = el.querySelectorAll("thead th").length;
  let sortKey = "buzz", sortDir = -1;
  const open = new Set();
  function render() {
    const shown = rows.filter(filter).sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x === null || y === null) return (x === null) - (y === null);  // rows without a value always last
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    el.querySelector("tbody").innerHTML = shown.map(s =>
      `<tr class="row" data-s="${esc(s[key])}">${cells(s)}</tr>` +
      (open.has(s[key]) ? `<tr class="detail"><td colspan="${cols}">${videoList(s)}</td></tr>` : "")
    ).join("") || `<tr><td colspan="${cols}">${empty}</td></tr>`;
  }
  el.querySelector("tbody").addEventListener("click", e => {
    const tr = e.target.closest("tr.row"); if (!tr) return;
    const k = tr.dataset.s; open.has(k) ? open.delete(k) : open.add(k); render();
  });
  el.querySelectorAll("th[data-k]").forEach(th => th.addEventListener("click", () => {
    const k = th.dataset.k; sortDir = sortKey === k ? -sortDir : -1; sortKey = k; render();
  }));
  render();
  return render;
}

const q = document.getElementById("q");
const renderStocks = table({
  id: "tbl", rows: S, key: "symbol", empty: "No stock mentions in this period.",
  filter: s => !q.value || (s.symbol + " " + s.name + " " + s.sector).toLowerCase().includes(q.value.toLowerCase()),
  cells: s => `<td><div class="sym">${esc(s.symbol)}</div><div class="name">${esc(s.name)}</div></td>
    <td>${esc(s.sector)}</td><td class="num">${s.buzz}</td><td class="num">${s.videos}</td>
    <td class="num">${s.channel_count}</td><td class="num">${s.recent}</td><td class="num">${s.previous}</td>
    <td><span class="badge ${s.trend}">${s.trend}</span></td><td>${sbar(s)}</td><td>${tone(s)}</td><td class="num">${fmt(s.views)}</td>`,
});
q.addEventListener("input", renderStocks);
table({
  id: "sectbl", rows: DATA.sectors, key: "sector", empty: "No sectors discussed in this period.",
  cells: s => `<td class="sym">${esc(s.sector)}</td><td class="num">${s.buzz}</td><td class="num">${s.videos}</td>
    <td class="num">${s.direct_videos}</td><td class="num">${s.recent}</td><td class="num">${s.previous}</td>
    <td><span class="badge ${s.trend}">${s.trend}</span></td><td>${sbar(s)}</td><td>${tone(s)}</td>
    <td class="name">${s.stocks.map(esc).join(" ") || "–"}</td>`,
});
</script>
</body>
</html>
"""


def write_report(data: dict, path: str | Path) -> Path:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path = Path(path)
    path.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    return path
