"""How channels' buy and sell calls turned out: the price move 5 and 20 trading days after each call.

A call is entered at the close of the first trading day *after* the video was published (many videos come out after
the market closes), and compared with the equal-weight average move of all priced stocks over the same days, so a
rising market doesn't make every buy call look good. Hold calls, and calls on stocks without prices, are listed in the
call log but not scored. Calls are found by keywords, samples are small, and past results don't predict future ones.
"""

from bisect import bisect_right
from collections import defaultdict

from . import prices

HORIZONS = (5, 20)  # trading days after entry
MIN_CALLS = 5       # fewer scored calls than this is too few to read anything into


def _load_prices(conn) -> dict[str, tuple[list[str], list[float]]]:
    out = {}
    for sym in prices.priced_symbols(conn):
        series = prices.load_series(conn, sym)  # cleaned of Yahoo's split/glitch jumps
        out[sym] = ([d for d, _, _ in series], [c for _, c, _ in series])
    return out


def _market_move(prices, start: str, end: str) -> float | None:
    """Equal-weight average move of every stock with closes on both days."""
    moves = []
    for dates, closes in prices.values():
        i, j = bisect_right(dates, start) - 1, bisect_right(dates, end) - 1
        if i >= 0 and j >= 0 and dates[i] == start and dates[j] == end:
            moves.append(closes[j] / closes[i] - 1)
    return sum(moves) / len(moves) if moves else None


def evaluate(conn) -> list[dict]:
    """Every explicit call (buy, sell or hold), newest first. Calls on stocks with prices get the entry close, the move
    since then to the latest close ("now"), and 5- and 20-day results (None while pending); calls on stocks without
    prices, or made after the last close, have entry None. Hold calls have no direction, so no right/wrong."""
    prices = _load_prices(conn)
    rows = conn.execute(
        """SELECT m.symbol, m.calls, m.holds, v.id AS video_id, v.title, substr(v.published_at, 1, 10) AS day,
                  v.channel_id, COALESCE(c.title, v.channel_id) AS channel
           FROM mentions m JOIN videos v ON v.id = m.video_id LEFT JOIN channels c ON c.id = v.channel_id
           WHERE m.calls != 0 OR m.holds > 0 ORDER BY v.published_at DESC, m.symbol""").fetchall()
    calls = []
    for r in rows:
        side = 1 if r["calls"] > 0 else -1 if r["calls"] < 0 else 0
        call = {"channel": r["channel"], "channel_id": r["channel_id"], "symbol": r["symbol"],
                "call": {1: "buy", -1: "sell", 0: "hold"}[side], "video_id": r["video_id"], "title": r["title"],
                "published": r["day"], "entry_date": None, "entry": None, "last_date": None, "last": None, "now": None}
        for h in HORIZONS:
            call[f"move{h}"] = call[f"market{h}"] = call[f"right{h}"] = None
        calls.append(call)
        if r["symbol"] not in prices:
            continue
        dates, closes = prices[r["symbol"]]
        entry = bisect_right(dates, r["day"])  # first trading day strictly after the video
        if entry >= len(dates):
            continue  # no trading day after it yet
        call.update(entry_date=dates[entry], entry=closes[entry], last_date=dates[-1], last=closes[-1],
                    now=round(100 * (closes[-1] / closes[entry] - 1), 2))
        for h in HORIZONS:
            exit_ = entry + h
            if exit_ >= len(dates):
                continue
            move = closes[exit_] / closes[entry] - 1
            market = _market_move(prices, dates[entry], dates[exit_])
            call[f"move{h}"] = round(100 * move, 2)                 # raw price move, %
            call[f"market{h}"] = round(100 * market, 2) if market is not None else None
            if side:
                call[f"right{h}"] = side * move > 0                 # went the way the call said
    return calls


def scored(calls: list[dict]) -> list[dict]:
    """The calls the track record scores: buy and sell calls on stocks with prices."""
    return [c for c in calls if c["call"] != "hold" and c["entry"] is not None]


def summarise(calls: list[dict]) -> list[dict]:
    """Per channel (and an "All channels" row first): calls, and per horizon how many were scored, the share that went
    the called way, the average move in the called direction, and that average minus the market's."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in calls:
        groups[c["channel"]].append(c)

    def stats(name, items):
        row = {"channel": name, "calls": len(items), "buy": sum(c["call"] == "buy" for c in items),
               "sell": sum(c["call"] == "sell" for c in items)}
        for h in HORIZONS:
            scored = [c for c in items if c[f"right{h}"] is not None]
            sign = lambda c: 1 if c["call"] == "buy" else -1
            directional = [sign(c) * c[f"move{h}"] for c in scored]
            excess = [sign(c) * (c[f"move{h}"] - c[f"market{h}"]) for c in scored if c[f"market{h}"] is not None]
            row[f"n{h}"] = len(scored)
            row[f"hit{h}"] = round(100 * sum(c[f"right{h}"] for c in scored) / len(scored)) if scored else None
            row[f"avg{h}"] = round(sum(directional) / len(directional), 2) if directional else None
            row[f"excess{h}"] = round(sum(excess) / len(excess), 2) if excess else None
            row[f"pending{h}"] = len(items) - len(scored)
        row["enough"] = row[f"n{HORIZONS[-1]}"] >= MIN_CALLS
        return row

    rows = [stats(name, items) for name, items in groups.items()]
    last = HORIZONS[-1]
    rows.sort(key=lambda r: (not r["enough"], -r[f"excess{last}"] if r[f"excess{last}"] is not None else 0, -r["calls"]))
    return [stats("All channels", calls)] + rows


def build(conn) -> dict:
    calls = evaluate(conn)
    return {"horizons": list(HORIZONS), "min_calls": MIN_CALLS, "channels": summarise(scored(calls)), "calls": calls}
