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


def _net(net: int, videos: int, min_videos: int) -> float | None:
    return round(net / videos, 2) if videos >= min_videos else None


def _aggregate(rows, start: date, today: date, window: int, dates: list[str], min_tone_videos: int,
               new_entry) -> list[dict]:
    """Per-key stats from one row per (video, key). new_entry(row) gives the identifying fields for a new key."""
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
                "bullish": 0, "bearish": 0, "neutral": 0,
                "recent": 0, "previous": 0, "net_recent": 0, "net_previous": 0,
                "channels": set(), "daily": defaultdict(int), "top_videos": [],
            }
        a["videos"] += 1
        a["mentions"] += r["in_title"] + r["in_description"] + r["in_transcript"]
        a["title_videos"] += 1 if r["in_title"] else 0
        a["views"] += r["views"] or 0
        a["buzz"] += (2 if r["in_title"] else 1) * (1 + math.log10(1 + (r["views"] or 0)))
        a["bullish" if r["sentiment"] > 0 else "bearish" if r["sentiment"] < 0 else "neutral"] += 1
        tone = (r["sentiment"] > 0) - (r["sentiment"] < 0)
        age = (today - d).days
        if age < window:
            a["recent"] += 1
            a["net_recent"] += tone
        elif age < 2 * window:
            a["previous"] += 1
            a["net_previous"] += tone
        a["channels"].add(r["channel_title"] or r["channel_id"])
        a["daily"][d.isoformat()] += 1
        a["top_videos"].append({
            "id": r["video_id"], "title": r["title"], "channel": r["channel_title"] or r["channel_id"],
            "published": d.isoformat(), "views": r["views"] or 0, "sentiment": tone,
        })

    result = []
    for a in agg.values():
        a["channels"] = sorted(a["channels"])
        a["channel_count"] = len(a["channels"])
        a["buzz"] = round(a["buzz"], 1)
        a["sentiment_score"] = round((a["bullish"] - a["bearish"]) / a["videos"], 2)
        a["trend"] = trend_label(a["recent"], a["previous"])
        a["tone_recent"] = _net(a.pop("net_recent"), a["recent"], min_tone_videos)
        a["tone_previous"] = _net(a.pop("net_previous"), a["previous"], min_tone_videos)
        both = a["tone_recent"] is not None and a["tone_previous"] is not None
        a["tone_change"] = round(a["tone_recent"] - a["tone_previous"], 2) if both else None
        a["tone_trend"] = tone_label(a["tone_recent"], a["tone_previous"])
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
                "key": sector, "in_title": 0, "in_description": 0, "in_transcript": 0, "sentiment": 0,
                "direct": False, "symbols": set(),
            }
        for k in ("in_title", "in_description", "in_transcript", "sentiment"):
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
