"""A short 'what changed' note for each daily run: the last 24 hours, and this week against last week.

Everything is read from the stored data, so it needs no snapshot of the previous run.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import prices
from .tickers import Stock
from .trends import compute

TOP = 5  # items per list, so the note stays a quick read


def build(conn, stocks: dict[str, Stock], now: datetime | None = None, window: int = 7) -> dict:
    """{"title", "headline", "sections": [{"title", "items": [str]}]}; empty sections are left out."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    data = compute(conn, stocks, days=90, window=window, today=today)
    names = {s["symbol"]: s for s in data["stocks"]}

    # Last 24 hours: videos published since this time yesterday.
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    day_videos = conn.execute(
        """SELECT v.id, v.title, v.channel_id, c.title AS channel FROM videos v LEFT JOIN channels c ON c.id = v.channel_id
           WHERE replace(substr(v.published_at, 1, 19), ' ', 'T') >= ?""", (since,)).fetchall()
    day_ids = [v["id"] for v in day_videos]
    day_mentions = conn.execute(
        f"""SELECT m.symbol, m.calls, m.holds, c.title AS channel FROM mentions m JOIN videos v ON v.id = m.video_id
            LEFT JOIN channels c ON c.id = v.channel_id WHERE m.video_id IN ({",".join("?" * len(day_ids))})""",
        day_ids).fetchall() if day_ids else []
    day_count = defaultdict(int)
    day_calls = []
    for m in day_mentions:
        day_count[m["symbol"]] += 1
        call = "buy" if m["calls"] > 0 else "sell" if m["calls"] < 0 else "hold" if m["holds"] else None
        if call:
            day_calls.append(f"{m['symbol']} {call} ({m['channel']})")
    last24 = []
    if day_videos:
        channels = len({v["channel_id"] for v in day_videos})
        last24.append(f"{len(day_videos)} new video{'s' if len(day_videos) != 1 else ''} from "
                      f"{channels} channel{'s' if channels != 1 else ''}")
        ranked = sorted(day_count.items(), key=lambda kv: (-kv[1], kv[0]))
        last24.append("Stocks mentioned: " + ", ".join(f"{s} ({n})" if n > 1 else s for s, n in ranked[:8])
                      if ranked else "No stock mentions in them")
        if day_calls:
            last24.append("Calls: " + "; ".join(day_calls[:TOP]))
    else:
        last24.append("No new videos")

    # This week vs last week, from the same week-over-week numbers as the dashboard.
    week = []
    new = [s for s in data["stocks"] if sum(s["series"][-window:]) > 0 and sum(s["series"][:-window]) == 0]
    if new:
        week.append("Newly discussed (none in the 83 days before): " +
                    ", ".join(f"{s['symbol']} ({sum(s['series'][-window:])})" for s in new[:TOP]))
    rising = sorted((s for s in data["stocks"] if s["trend"] == "RISING"), key=lambda s: s["previous"] - s["recent"])
    if rising:
        week.append("Buzz rising: " + ", ".join(f"{s['symbol']} {s['previous']}→{s['recent']}" for s in rising[:TOP]))
    # One video last week and none this week is noise, not a trend.
    fading = sorted((s for s in data["stocks"] if s["trend"] == "FALLING" and s["previous"] >= 2),
                    key=lambda s: s["recent"] - s["previous"])
    if fading:
        week.append("Buzz fading: " + ", ".join(f"{s['symbol']} {s['previous']}→{s['recent']}" for s in fading[:TOP]))

    start = (today - timedelta(days=window - 1)).isoformat()
    calls = defaultdict(lambda: {"buy": 0, "sell": 0, "hold": 0, "channels": set()})
    for m in conn.execute(
            """SELECT m.symbol, m.calls, m.holds, v.channel_id FROM mentions m JOIN videos v ON v.id = m.video_id
               WHERE substr(v.published_at, 1, 10) >= ? AND (m.calls != 0 OR m.holds > 0)""", (start,)):
        kind = "buy" if m["calls"] > 0 else "sell" if m["calls"] < 0 else "hold"
        calls[m["symbol"]][kind] += 1
        calls[m["symbol"]]["channels"].add(m["channel_id"])

    def call_list(kind):
        picked = sorted(((sym, c) for sym, c in calls.items() if c[kind]),
                        key=lambda kv: (-kv[1][kind], -len(kv[1]["channels"]), kv[0]))
        return ", ".join(f"{sym} ×{c[kind]}" + (f" ({len(c['channels'])} channels)" if len(c["channels"]) > 1 else "")
                         for sym, c in picked[:TOP])

    for kind, label in (("buy", "Buy calls this week"), ("sell", "Sell calls this week"), ("hold", "Hold calls this week")):
        listed = call_list(kind)
        if listed:
            week.append(f"{label}: {listed}")

    sectors = []
    for s in data["sectors"]:
        bits = []
        if s["trend"] == "RISING" and s["recent"] >= 3:
            bits.append(f"buzz rising {s['previous']}→{s['recent']}")
        if s["tone_trend"] == "IMPROVING":
            bits.append(f"tone improving ({s['tone_change']:+.2f})")
        elif s["tone_trend"] == "WORSENING":
            bits.append(f"tone turning bearish ({s['tone_change']:+.2f})")
        if bits:
            sectors.append(f"{s['sector']}: {', '.join(bits)}")

    # Technical signals from daily closes, for the discussed stocks; within a signal, stocks whose buzz is rising come
    # first, then the most discussed.
    by_kind = defaultdict(list)
    for st in data["stocks"]:
        t = prices.technicals(prices.load_series(conn, st["symbol"]))
        hot = st["trend"] in ("RISING", "NEW") and st["recent"] >= 2
        for sg in (t or {}).get("signals", []):
            by_kind[sg["kind"]].append((not hot, -st["buzz"], st["symbol"], sg["detail"], hot))
    technical = []
    for kind in ("oversold", "overbought", "near_support", "near_resistance", "range",
                 "golden_cross", "death_cross", "high52", "low52"):
        picked = sorted(by_kind.get(kind, []))[:TOP]
        if picked:
            technical.append(f"{prices.SIGNAL_LABELS[kind]}: " + "; ".join(
                f"{sym} {detail}{' · buzz rising' if hot else ''}" for _, _, sym, detail, hot in picked))

    most = data["stocks"][0]["symbol"] if data["stocks"] else None
    week_videos = sum(1 for _ in conn.execute(
        "SELECT 1 FROM videos WHERE substr(published_at, 1, 10) >= ?", (start,)))
    headline = (f"{week_videos} videos this week across {data['channel_count']} channels"
                + (f"; most discussed over 90 days: {most} ({names[most]['videos']} videos)" if most else ""))
    sections = [{"title": "Last 24 hours", "items": last24},
                {"title": "This week vs last week", "items": week or ["No changes worth noting"]},
                {"title": "Sectors", "items": sectors[:TOP]},
                {"title": "Technical signals (daily closes)", "items": technical}]
    return {"title": f"PSX YouTube digest, {today.strftime('%d %b %Y')}", "date": today.isoformat(),
            "headline": headline, "sections": [s for s in sections if s["items"]]}


def markdown(d: dict) -> str:
    lines = [f"## {d['title']}", "", d["headline"], ""]
    for s in d["sections"]:
        lines += [f"**{s['title']}**", ""] + [f"- {item}" for item in s["items"]] + [""]
    lines.append("_What the tracked channels said, detected from keywords; technical signals are mechanical calculations "
                 "from Yahoo Finance daily closes. Not investment advice._")
    return "\n".join(lines) + "\n"
