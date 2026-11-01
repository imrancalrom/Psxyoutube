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
    return t


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
