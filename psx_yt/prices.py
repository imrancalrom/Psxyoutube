"""Daily closing prices from the PSX data portal, and the technical indicators drawn on the dashboard.

Indicators use common default settings and closing prices only (the portal's end-of-day series has no daily
high/low): SMA 20/50/200, RSI 14, MACD 12/26/9, the 52-week range, and support/resistance from swing points.
They are mechanical calculations, not advice.
"""

from datetime import datetime, timezone

import requests

EOD_URL = "https://dps.psx.com.pk/timeseries/eod/{}"
HEADERS = {"User-Agent": "Mozilla/5.0 (psx-yt-tracker)", "Accept": "application/json"}


class PriceError(RuntimeError):
    pass


def parse_eod(payload) -> list[tuple[str, float, int | None]]:
    """[(YYYY-MM-DD, close, volume or None)] oldest first, from the portal's {"data": [[unix time, close, volume, ...]]}.

    Raises PriceError, quoting what arrived, when the shape isn't that, so a format change shows up in the log.
    """
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise PriceError(f"unexpected response: {str(payload)[:200]}")
    out = {}
    for row in rows:
        if not (isinstance(row, (list, tuple)) and len(row) >= 2):
            raise PriceError(f"unexpected row: {str(row)[:120]}")
        ts, close = row[0], row[1]
        if not (isinstance(ts, (int, float)) and ts > 9e8 and isinstance(close, (int, float)) and close > 0):
            raise PriceError(f"unexpected row: {str(row)[:120]}")
        day = datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, timezone.utc).date().isoformat()  # s or ms
        volume = row[2] if len(row) > 2 and isinstance(row[2], (int, float)) else None
        out[day] = (day, float(close), int(volume) if volume is not None else None)
    return sorted(out.values())


def fetch_eod(symbol: str) -> list[tuple[str, float, int | None]]:
    r = requests.get(EOD_URL.format(symbol), headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise PriceError(f"HTTP {r.status_code}")
    try:
        payload = r.json()
    except ValueError:
        raise PriceError(f"not JSON: {r.text[:120]!r}") from None
    return parse_eod(payload)


def probe(symbol: str) -> None:
    """Print what the portal's likely price endpoints return for one symbol (to find the right one; run on a machine
    that can reach dps.psx.com.pk)."""
    ajax = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": f"https://dps.psx.com.pk/company/{symbol}"}
    tries = [
        ("GET", f"https://dps.psx.com.pk/timeseries/eod/{symbol}", HEADERS, None),
        ("GET", f"https://dps.psx.com.pk/timeseries/eod/{symbol}", ajax, None),
        ("GET", f"https://dps.psx.com.pk/timeseries/int/{symbol}", ajax, None),
        ("GET", f"https://dps.psx.com.pk/company/{symbol}", HEADERS, None),
        ("POST", "https://dps.psx.com.pk/historical", ajax, {"symbol": symbol}),
        ("GET", "https://dps.psx.com.pk/historical", HEADERS, None),
    ]
    for method, url, headers, form in tries:
        try:
            r = requests.request(method, url, headers=headers, data=form, timeout=30)
            body = " ".join(r.text[:300].split())
            print(f"{method} {url} {'(ajax headers)' if headers is ajax else ''}{' form=' + str(form) if form else ''}\n"
                  f"   -> HTTP {r.status_code}, {r.headers.get('content-type', '?')}, {len(r.content)} bytes: {body}")
            if r.headers.get("content-type", "").startswith("text/html"):
                forms = [" ".join(f.split())[:300] for f in __import__("re").findall(r"<form.*?</form>", r.text, flags=16)]
                for f in forms[:3]:
                    print(f"   form: {f}")
        except requests.RequestException as e:
            print(f"{method} {url} -> {type(e).__name__}: {e}")


YAHOO_URL = "https://query{n}.finance.yahoo.com/v8/finance/chart/{symbol}.KA"


def parse_yahoo(symbol: str, payload) -> list[tuple[str, float, int | None]]:
    """[(YYYY-MM-DD, close, volume)] oldest first from Yahoo's chart API, after checking the series really is
    SYMBOL on the Karachi exchange in PKR (raises PriceError otherwise, so another listing is never used).

    Only the daily closes are used: Yahoo's `regularMarketPrice` for PSX stocks disagrees with its own closes
    (OGDC 131.87 vs a 306.78 close on 30 Oct 2026, when TradingView showed ~308).
    """
    chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
    if chart.get("error"):
        raise PriceError(f"Yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise PriceError("Yahoo returned no data")
    res = results[0]
    meta = res.get("meta", {})
    want = {"symbol": f"{symbol}.KA", "exchangeName": "KAR", "currency": "PKR"}
    got = {k: meta.get(k) for k in want}
    if got != want:
        raise PriceError(f"Yahoo series is not {symbol} on the Karachi exchange in PKR: {got}")
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    out = {}
    for ts, close, volume in zip(res.get("timestamp") or [], quote.get("close") or [], quote.get("volume") or []):
        if isinstance(ts, (int, float)) and isinstance(close, (int, float)) and close > 0:
            day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
            out[day] = (day, round(float(close), 2), int(volume) if isinstance(volume, (int, float)) else None)
    if len(out) < 30:
        raise PriceError(f"only {len(out)} daily closes")
    return sorted(out.values())


def impossible(prev: float, cur: float) -> bool:
    """A day-to-day move PSX's circuit breaker wouldn't allow (10%, or Rs 1 for cheap stocks), with some slack."""
    return abs(cur - prev) > max(0.11 * prev, 1.05)


def clean_series(rows: list[tuple[str, float, int | None]], max_glitch: int = 10):
    """(cleaned rows, note) for a price series with impossible jumps: Yahoo's PSX history switches between split-
    adjusted and unadjusted prices (LUCK 284 -> 1412 -> 292) and has short glitches (WTL 1.26 -> 0.12 for a few days).

    A jump that comes back within `max_glitch` days is a glitch and those days are dropped; a jump that doesn't come
    back is a change of scale, and only the data after the last one is kept, so prices on two scales are never mixed.
    """
    rows = list(rows)
    dropped = 0
    i = 1
    while i < len(rows):
        if impossible(rows[i - 1][1], rows[i][1]):
            base = rows[i - 1][1]
            back = next((j for j in range(i + 1, min(i + 1 + max_glitch, len(rows)))
                         if not impossible(base, rows[j][1])), None)
            if back is not None:  # a glitch: the price returns to where it was
                dropped += back - i
                del rows[i:back]
                continue
        i += 1
    breaks = [i for i in range(1, len(rows)) if impossible(rows[i - 1][1], rows[i][1])]
    cut = 0
    if breaks:  # a lasting change of scale: keep only what comes after it
        cut = breaks[-1]
        rows = rows[cut:]
    note = ", ".join(x for x in (f"{dropped} glitch days dropped" if dropped else "",
                                 f"{cut} days before a change of scale dropped" if cut else "") if x)
    return rows, note


def load_series(conn, symbol: str) -> list[tuple[str, float, int | None]]:
    """A stock's stored daily prices, oldest first, cleaned (every reader goes through this)."""
    rows = conn.execute("SELECT date, close, volume FROM prices WHERE symbol = ? ORDER BY date", (symbol,)).fetchall()
    return clean_series([tuple(r) for r in rows])[0]


def priced_symbols(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol")]


def fetch_yahoo(symbol: str) -> list[tuple[str, float, int | None]]:
    r = requests.get(YAHOO_URL.format(n=1, symbol=symbol), params={"range": "2y", "interval": "1d"},
                     headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise PriceError(f"HTTP {r.status_code}")
    try:
        payload = r.json()
    except ValueError:
        raise PriceError(f"not JSON: {r.text[:120]!r}") from None
    return parse_yahoo(symbol, payload)


def probe_yahoo(symbol: str) -> None:
    """Print what Yahoo Finance returns for SYMBOL.KA, including what it says the series is (symbol, exchange,
    currency, name), so a wrong match can be spotted before any of it is used."""
    for n in (1, 2):
        url = YAHOO_URL.format(n=n, symbol=symbol)
        try:
            r = requests.get(url, params={"range": "2y", "interval": "1d"}, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"GET {url} -> {type(e).__name__}: {e}")
            continue
        print(f"GET {url}?range=2y&interval=1d\n   -> HTTP {r.status_code}, {r.headers.get('content-type', '?')}, {len(r.content)} bytes")
        try:
            chart = r.json().get("chart", {})
        except ValueError:
            print(f"   not JSON: {' '.join(r.text[:200].split())}")
            continue
        if chart.get("error"):
            print(f"   error: {chart['error']}")
        for res in chart.get("result") or []:
            meta = res.get("meta", {})
            print("   meta: " + ", ".join(f"{k}={meta.get(k)!r}" for k in
                                         ("symbol", "exchangeName", "fullExchangeName", "currency", "longName",
                                          "shortName", "instrumentType", "regularMarketPrice", "dataGranularity")))
            ts = res.get("timestamp") or []
            quote = (res.get("indicators", {}).get("quote") or [{}])[0]
            closes = quote.get("close") or []
            points = [(t, c) for t, c in zip(ts, closes) if c is not None]
            print(f"   {len(ts)} timestamps, {len(points)} closes; fields: {sorted(quote)}")
            for t, c in points[:2] + points[-3:]:
                print(f"     {datetime.fromtimestamp(t, timezone.utc).date()} close {c}")
        break


# --- indicators -------------------------------------------------------------------------------------------------

def sma(values: list[float], n: int) -> list[float | None]:
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        out.append(round(total / n, 2) if i >= n - 1 else None)
    return out


def ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    k, prev = 2 / (n + 1), None
    for i, v in enumerate(values):
        if i < n - 1:
            out.append(None)
            continue
        prev = sum(values[:n]) / n if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(values: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return out
    gains = [max(values[i] - values[i - 1], 0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0) for i in range(1, len(values))]
    avg_gain, avg_loss = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(values)):
        if i > n:
            avg_gain = (avg_gain * (n - 1) + gains[i - 1]) / n
            avg_loss = (avg_loss * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if avg_loss == 0 else round(100 - 100 / (1 + avg_gain / avg_loss), 1)
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """(macd line, signal line, histogram), None until there is enough data."""
    f, s = ema(values, fast), ema(values, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:]], signal) if start < len(line) else []
    sig = [None] * start + sig_part
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    r = lambda xs: [round(x, 2) if x is not None else None for x in xs]
    return r(line), r(sig), r(hist)


def levels(closes: list[float], window: int = 5, tolerance: float = 0.015, lookback: int = 250) -> list[dict]:
    """Support/resistance candidates from swing highs and lows of the last `lookback` closes.

    A swing point is the highest (or lowest) close within `window` days either side. Points within `tolerance` of
    each other are one level (their average); a level's strength is how many swing points touched it.
    """
    data = closes[-lookback:]
    pivots = []
    for i in range(window, len(data) - window):
        span = data[i - window:i + window + 1]
        if data[i] == max(span) or data[i] == min(span):
            pivots.append(data[i])
    clusters: list[list[float]] = []
    for p in sorted(pivots):
        if clusters and p <= clusters[-1][0] * (1 + tolerance):
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [{"price": round(sum(c) / len(c), 2), "touches": len(c)} for c in clusters]


def technicals(series: list[tuple[str, float, int | None]], chart_days: int = 180) -> dict | None:
    """Indicators and chart data for one stock, or None with too little history (< 30 days)."""
    if len(series) < 30:
        return None
    dates = [d for d, _, _ in series]
    closes = [c for _, c, _ in series]
    last = closes[-1]
    s20, s50, s200, r14 = sma(closes, 20), sma(closes, 50), sma(closes, 200), rsi(closes)
    m_line, m_sig, m_hist = macd(closes)
    year = closes[-250:]
    lv = levels(closes)
    # Nearest two levels on each side of today's close, strongest first among equals; ignore ones within 0.5%.
    support = sorted((l for l in lv if l["price"] < last * 0.995), key=lambda l: -l["price"])[:2]
    resistance = sorted((l for l in lv if l["price"] > last * 1.005), key=lambda l: l["price"])[:2]

    def cross(fast, slow, days=20):
        for i in range(len(closes) - 1, max(len(closes) - 1 - days, 0), -1):
            a, b, pa, pb = fast[i], slow[i], fast[i - 1], slow[i - 1]
            if None in (a, b, pa, pb):
                return None
            if pa <= pb and a > b:
                return {"kind": "golden", "date": dates[i]}
            if pa >= pb and a < b:
                return {"kind": "death", "date": dates[i]}
        return None

    k = slice(-chart_days, None)
    t = {
        "date": dates[-1], "close": last,
        "change_pct": round(100 * (last / closes[-2] - 1), 2),
        "sma20": s20[-1], "sma50": s50[-1], "sma200": s200[-1], "rsi14": r14[-1],
        "macd": m_line[-1], "macd_signal": m_sig[-1], "macd_hist": m_hist[-1],
        "high52": max(year), "low52": min(year),
        "support": support, "resistance": resistance,
        "cross": cross(s50, s200),
        "chart": {"dates": dates[k], "close": closes[k], "sma50": s50[k], "sma200": s200[k], "rsi14": r14[k]},
    }
    t["summary"] = technical_summary(t)
    t["signals"] = signals(t)
    return t


NEAR = 0.02  # "near" a level: within 2% of it
MIN_TOUCHES = 2  # a level price has tested only once is weak evidence, so it doesn't make a "near" signal

SIGNAL_LABELS = {
    "near_support": "Near support", "near_resistance": "Near resistance", "range": "Tight range",
    "oversold": "RSI oversold", "overbought": "RSI overbought",
    "golden_cross": "Golden cross", "death_cross": "Death cross",
    "high52": "52-week high", "low52": "52-week low",
}


def signals(t: dict) -> list[dict]:
    """Mechanical signals from a technicals() result: [{"kind", "label", "detail"}], most specific first."""
    out = []
    close = t["close"]
    sup = next((l for l in t["support"] if l["touches"] >= MIN_TOUCHES and close <= l["price"] * (1 + NEAR)), None)
    res = next((l for l in t["resistance"] if l["touches"] >= MIN_TOUCHES and close >= l["price"] * (1 - NEAR)), None)
    if sup and res:  # close to both: squeezed between them
        out.append(("range", f"{sup['price']:g}–{res['price']:g}, {100 * (res['price'] / sup['price'] - 1):.1f}% wide"))
    elif sup:
        out.append(("near_support", f"{sup['price']:g} support ({sup['touches']}×), {100 * (close / sup['price'] - 1):.1f}% above"))
    elif res:
        out.append(("near_resistance", f"{res['price']:g} resistance ({res['touches']}×), {100 * (res['price'] / close - 1):.1f}% below"))
    if t["rsi14"] is not None and t["rsi14"] <= 30:
        out.append(("oversold", f"RSI {t['rsi14']:.0f}"))
    if t["rsi14"] is not None and t["rsi14"] >= 70:
        out.append(("overbought", f"RSI {t['rsi14']:.0f}"))
    if t["cross"]:
        out.append((f"{t['cross']['kind']}_cross", f"SMA 50 {'above' if t['cross']['kind'] == 'golden' else 'below'} "
                                                    f"SMA 200 since {t['cross']['date']}"))
    if close >= t["high52"]:
        out.append(("high52", f"at {close:g}"))
    elif close <= t["low52"]:
        out.append(("low52", f"at {close:g}"))
    return [{"kind": k, "label": SIGNAL_LABELS[k], "detail": d} for k, d in out]


def technical_summary(t: dict) -> str:
    """'Close 308.05 (−0.6%) · above SMA 50, below SMA 200 · RSI 62 · support 290 (3×), resistance 320 (2×)'."""
    parts = [f"Close {t['close']:g} ({t['change_pct']:+.1f}%)"]
    sides = [f"{'above' if t['close'] >= t[k] else 'below'} SMA {k[3:]}" for k in ("sma50", "sma200") if t[k] is not None]
    if sides:
        parts.append(", ".join(sides))
    if t["cross"]:
        parts.append(f"{t['cross']['kind']} cross {t['cross']['date']}")
    if t["rsi14"] is not None:
        zone = " overbought" if t["rsi14"] >= 70 else " oversold" if t["rsi14"] <= 30 else ""
        parts.append(f"RSI {t['rsi14']:.0f}{zone}")
    lv = lambda ls: ", ".join(f"{l['price']:g} ({l['touches']}×)" for l in ls)
    if t["support"]:
        parts.append(f"support {lv(t['support'])}")
    if t["resistance"]:
        parts.append(f"resistance {lv(t['resistance'])}")
    return " · ".join(parts)
