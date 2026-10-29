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


def compute(conn, stocks: dict[str, Stock], days: int = 30, window: int = 7, today: date | None = None,
            min_tone_videos: int = 3) -> dict:
    """Stats for every stock mentioned in the last `days` days.

    buzz     = sum over videos of (2 if in title else 1) * (1 + log10(1 + views))
    momentum = videos in the last `window` days vs the `window` days before that
    tone     = net sentiment (bullish - bearish) / videos in each of those two windows, and its change;
               a window needs `min_tone_videos` videos to get a tone
    """
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    rows = conn.execute(
        """SELECT m.*, v.title, v.published_at, v.views, v.channel_id, c.title AS channel_title
           FROM mentions m JOIN videos v ON v.id = m.video_id LEFT JOIN channels c ON c.id = v.channel_id"""
    ).fetchall()

    agg: dict[str, dict] = {}
    sector_buzz: dict[str, float] = defaultdict(float)
    for r in rows:
        d = _day(r["published_at"])
        if d < start or d > today:
            continue
        sym = r["symbol"]
        stock = stocks.get(sym)
        a = agg.setdefault(sym, {
            "symbol": sym,
            "name": stock.name if stock else sym,
            "sector": stock.sector if stock else "Other",
            "videos": 0, "mentions": 0, "title_videos": 0, "views": 0, "buzz": 0.0,
            "bullish": 0, "bearish": 0, "neutral": 0,
            "recent": 0, "previous": 0, "net_recent": 0, "net_previous": 0,
            "channels": set(), "daily": defaultdict(int), "top_videos": [],
        })
        weight = (2 if r["in_title"] else 1) * (1 + math.log10(1 + (r["views"] or 0)))
        a["videos"] += 1
        a["mentions"] += r["in_title"] + r["in_description"] + r["in_transcript"]
        a["title_videos"] += 1 if r["in_title"] else 0
        a["views"] += r["views"] or 0
        a["buzz"] += weight
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
            "published": d.isoformat(), "views": r["views"] or 0,
            "sentiment": tone,
        })
        sector_buzz[a["sector"]] += weight

    dates = [(start + timedelta(days=i)).isoformat() for i in range(days)]
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
        a["series"] = [a["daily"].get(d, 0) for d in dates]
        del a["daily"]
        a["top_videos"].sort(key=lambda v: (v["published"], v["views"]), reverse=True)
        a["top_videos"] = a["top_videos"][:10]
        result.append(a)
    result.sort(key=lambda a: a["buzz"], reverse=True)

    total_videos = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE substr(published_at, 1, 10) >= ?", (start.isoformat(),)
    ).fetchone()[0]
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "start": start.isoformat(), "end": today.isoformat(), "days": days, "window": window,
        "dates": dates, "stocks": result,
        "sectors": sorted(({"sector": k, "buzz": round(v, 1)} for k, v in sector_buzz.items()),
                          key=lambda s: s["buzz"], reverse=True),
        "video_count": total_videos,
        "channel_count": conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0],
    }
