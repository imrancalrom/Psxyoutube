"""Aggregate mentions into per-stock trend statistics."""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .tickers import Stock


def _day(iso: str) -> date:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).date()


def trend_label(recent: int, previous: int) -> str:
    if recent == 0 and previous == 0:
        return "QUIET"
    if previous == 0:
        return "NEW"
    ratio = recent / previous
    if ratio >= 1.5 and recent >= 2:
        return "RISING"
    if ratio <= 0.67:
        return "FALLING"
    return "STEADY"


def tone_label(recent: float | None, previous: float | None, min_change: float = 0.25) -> str:
    """Week-over-week change in net tone (each -1..+1); '-' when either week has too few videos to tell."""
    if recent is None or previous is None:
        return "-"
    change = recent - previous
    if change >= min_change:
        return "IMPROVING"
    if change <= -min_change:
        return "WORSENING"
    return "STABLE"


def call_label(buy: int, hold: int, sell: int, min_calls: int = 3) -> str:
    """Consensus of the buy/hold/sell calls made in videos: the call with at least half of them, else MIXED;
    '-' when fewer than min_calls videos made a call."""
    calls = buy + hold + sell
    if calls < min_calls:
        return "-"
    ranked = sorted((("BUY", buy), ("HOLD", hold), ("SELL", sell)), key=lambda c: -c[1])
    if ranked[0][1] * 2 >= calls and ranked[0][1] > ranked[1][1]:
        return ranked[0][0]
    return "MIXED"


def summary(a: dict) -> str:
    """One factual line about a stock or sector, built only from its stats (never advice), e.g.
    '13 videos on 6 channels · new this week (3) · calls split: 2 buy, 2 sell'."""
    n = lambda count, word: f"{count} {word}{'' if count == 1 else 's'}"
    coverage = n(a["videos"], "video") + (" on 1 channel only" if a["channel_count"] == 1
                                          else f" on {a['channel_count']} channels")
    momentum = {
        "NEW": (f"new this week ({a['recent']})" if a["recent"] == a["videos"]
                else f"{a['recent']} this week, none the week before"),
        "RISING": f"buzz rising ({a['previous']}→{a['recent']} a week)",
        "FALLING": f"buzz fading ({a['previous']}→{a['recent']} a week)",
        "STEADY": f"steady ({a['recent']} this week)",
        "QUIET": "quiet in the last two weeks",
    }[a["trend"]]
    counts = ", ".join(f"{c} {w}" for c, w in ((a["bullish"], "buy"), (a["hold"], "hold"), (a["bearish"], "sell")) if c)
    calls = {
        "BUY": f"channels lean BUY ({counts})", "SELL": f"channels lean SELL ({counts})",
        "HOLD": f"mostly HOLD calls ({counts})", "MIXED": f"calls split: {counts}",
    }.get(a["call"], f"few calls so far ({counts})" if counts else "no buy/sell calls yet")
    parts = [coverage, momentum, calls]
    if a["tone_trend"] == "IMPROVING":
        parts.append("tone improving")
    elif a["tone_trend"] == "WORSENING":
        parts.append("tone turning bearish")
    return " · ".join(parts)


def _net(net: int, videos: int, min_videos: int) -> float | None:
    return round(net / videos, 2) if videos >= min_videos else None


def _aggregate(rows, start: date, today: date, window: int, dates: list[str], min_tone_videos: int,
               new_entry, min_calls: int = 3) -> list[dict]:
    """Per-key stats from one row per (video, key). new_entry(row) gives the identifying fields for a new key.

    The week-over-week fields (recent/previous counts and tone) always look at the last two windows, even when the
    period is shorter, so a 7-day view still compares this week with the week before.
    """
    weeks: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # recent, previous, net recent, net previous
    for r in rows:
        age = (today - _day(r["published_at"])).days
        if 0 <= age < 2 * window:
            tone = (r["sentiment"] > 0) - (r["sentiment"] < 0)
            w = weeks[r["key"]]
            w[0 if age < window else 1] += 1
            w[2 if age < window else 3] += tone
    agg: dict[str, dict] = {}
    for r in rows:
        d = _day(r["published_at"])
        if d < start or d > today:
            continue
        a = agg.get(r["key"])
        if a is None:
            a = agg[r["key"]] = {
                **new_entry(r),
                "videos": 0, "mentions": 0, "title_videos": 0, "views": 0, "buzz": 0.0,
                "bullish": 0, "bearish": 0, "neutral": 0, "hold": 0,
                "channels": set(), "daily": defaultdict(int), "top_videos": [],
            }
        a["videos"] += 1
        a["mentions"] += r["in_title"] + r["in_description"] + r["in_transcript"]
        a["title_videos"] += 1 if r["in_title"] else 0
        a["views"] += r["views"] or 0
        a["buzz"] += (2 if r["in_title"] else 1) * (1 + math.log10(1 + (r["views"] or 0)))
        a["bullish" if r["sentiment"] > 0 else "bearish" if r["sentiment"] < 0 else "neutral"] += 1
        tone = (r["sentiment"] > 0) - (r["sentiment"] < 0)
        call = "buy" if tone > 0 else "sell" if tone < 0 else "hold" if r["holds"] else ""
        a["hold"] += call == "hold"  # neutral videos with an explicit hold call
        a["channels"].add(r["channel_title"] or r["channel_id"])
        a["daily"][d.isoformat()] += 1
        a["top_videos"].append({
            "id": r["video_id"], "title": r["title"], "channel": r["channel_title"] or r["channel_id"],
            "published": d.isoformat(), "views": r["views"] or 0, "sentiment": tone, "call": call,
        })

    result = []
    for a in agg.values():
        a["channels"] = sorted(a["channels"])
        a["channel_count"] = len(a["channels"])
        a["buzz"] = round(a["buzz"], 1)
        a["sentiment_score"] = round((a["bullish"] - a["bearish"]) / a["videos"], 2)
        a["call"] = call_label(a["bullish"], a["hold"], a["bearish"], min_calls)
        calls = a["bullish"] + a["hold"] + a["bearish"]
        # Sort key for the call column: share of buy minus share of sell among the videos that made a call.
        a["call_score"] = round((a["bullish"] - a["bearish"]) / calls, 2) if a["call"] != "-" else None
        key = a["symbol"] if "symbol" in a else a["sector"]
        a["recent"], a["previous"], net_recent, net_previous = weeks[key]
        a["trend"] = trend_label(a["recent"], a["previous"])
        a["tone_recent"] = _net(net_recent, a["recent"], min_tone_videos)
        a["tone_previous"] = _net(net_previous, a["previous"], min_tone_videos)
        both = a["tone_recent"] is not None and a["tone_previous"] is not None
        a["tone_change"] = round(a["tone_recent"] - a["tone_previous"], 2) if both else None
        a["tone_trend"] = tone_label(a["tone_recent"], a["tone_previous"])
        a["summary"] = summary(a)
        daily = a.pop("daily")
        a["series"] = [daily.get(d, 0) for d in dates]
        a["top_videos"].sort(key=lambda v: (v["published"], v["views"]), reverse=True)
        a["top_videos"] = a["top_videos"][:10]
        result.append(a)
    result.sort(key=lambda a: a["buzz"], reverse=True)
    return result


def _sector_rows(stock_rows, sector_rows, stocks: dict[str, Stock]) -> list[dict]:
    """One row per (video, sector), from sectors named outright and from the sectors of stocks mentioned.

    "Selling from Banks" and "Buy MEBL" both count for Banks; their sentiments add up within a video.
    """
    merged: dict[tuple[str, str], dict] = {}
    for r, sector, symbol in [(r, r["sector"], None) for r in sector_rows] + \
                             [(r, stocks[r["symbol"]].sector if r["symbol"] in stocks else "Other", r["symbol"])
                              for r in stock_rows]:
        m = merged.get((r["video_id"], sector))
        if m is None:
            m = merged[(r["video_id"], sector)] = {
                **{k: r[k] for k in ("video_id", "title", "published_at", "views", "channel_id", "channel_title")},
                "key": sector, "in_title": 0, "in_description": 0, "in_transcript": 0, "sentiment": 0, "holds": 0,
                "direct": False, "symbols": set(),
            }
        for k in ("in_title", "in_description", "in_transcript", "sentiment", "holds"):
            m[k] += r[k]
        if symbol:
            m["symbols"].add(symbol)
        else:
            m["direct"] = True
    return list(merged.values())


def compute(conn, stocks: dict[str, Stock], days: int = 90, window: int = 7, today: date | None = None,
            min_tone_videos: int = 3) -> dict:
    """Stats for every stock and sector mentioned in the last `days` days.

    buzz     = sum over videos of (2 if in title else 1) * (1 + log10(1 + views))
    momentum = videos in the last `window` days vs the `window` days before that
    tone     = net sentiment (bullish - bearish) / videos in each of those two windows, and its change;
               a window needs `min_tone_videos` videos to get a tone
    A sector counts every video that names it outright ("refineries", "OMCs") or mentions one of its stocks.
    """
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    video_cols = "v.title, v.published_at, v.views, v.channel_id, c.title AS channel_title"
    joins = "JOIN videos v ON v.id = m.video_id LEFT JOIN channels c ON c.id = v.channel_id"
    stock_rows = [{**dict(r), "key": r["symbol"]}
                  for r in conn.execute(f"SELECT m.*, {video_cols} FROM mentions m {joins}")]
    sector_rows = [dict(r) for r in conn.execute(f"SELECT m.*, {video_cols} FROM sector_mentions m {joins}")]

    def stock_entry(r):
        stock = stocks.get(r["symbol"])
        return {"symbol": r["symbol"], "name": stock.name if stock else r["symbol"],
                "sector": stock.sector if stock else "Other"}

    stock_stats = _aggregate(stock_rows, start, today, window, dates, min_tone_videos, stock_entry)

    merged = _sector_rows(stock_rows, sector_rows, stocks)
    sector_stats = _aggregate(merged, start, today, window, dates, min_tone_videos, lambda r: {"sector": r["key"]})
    in_range = [m for m in merged if start <= _day(m["published_at"]) <= today]
    for sec in sector_stats:
        mine = [m for m in in_range if m["key"] == sec["sector"]]
        sec["direct_videos"] = sum(m["direct"] for m in mine)
        counts: dict[str, int] = defaultdict(int)
        for m in mine:
            for sym in m["symbols"]:
                counts[sym] += 1
        sec["stocks"] = sorted(counts, key=lambda k: -counts[k])[:8]

    total_videos = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE substr(published_at, 1, 10) >= ?", (start.isoformat(),)
    ).fetchone()[0]
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "start": start.isoformat(), "end": today.isoformat(), "days": days, "window": window,
        "dates": dates, "stocks": stock_stats, "sectors": sector_stats,
        "video_count": total_videos,
        "channel_count": conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0],
    }
