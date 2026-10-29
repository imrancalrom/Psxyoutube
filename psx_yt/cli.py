"""Command line interface: python -m psx_yt <command> ..."""

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from . import db, youtube
from .analyzer import (Analyzer, analyze_video, analyze_video_sectors, boilerplate_lines, strip_lines,
                       strip_payment_details, strip_video_titles, title_key)
from .report import write_report
from .tickers import load_tickers
from .trends import compute


def cmd_add_channel(args, conn):
    refs = list(args.refs)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            refs += [ln.split("#")[0].strip() for ln in f if ln.split("#")[0].strip()]
    if not refs:
        sys.exit("Give at least one channel (UC... id, @handle or URL) or --file")
    for ref in refs:
        try:
            cid, title = youtube.resolve_channel(ref, args.api_key)
        except youtube.YouTubeError as e:
            print(f"  ! {ref}: {e}")
            continue
        db.upsert_channel(conn, cid, title, ref)
        print(f"  + {cid}  {title or ''}  ({ref})")
    conn.commit()


def cmd_channels(args, conn):
    rows = conn.execute(
        "SELECT c.*, COUNT(v.id) AS n FROM channels c LEFT JOIN videos v ON v.channel_id = c.id GROUP BY c.id"
    ).fetchall()
    for r in rows:
        print(f"{r['id']}  {r['n']:>4} videos  {r['title'] or ''}  {r['ref'] or ''}")
    if not rows:
        print("No channels yet. Add some with: python -m psx_yt add-channel @handle")


KEY_REJECTED = {400, 401, 403}  # HTTP statuses meaning the API key is bad, restricted or out of quota


def warn(message: str):
    """Print a warning; inside GitHub Actions also show it on the run's summary page."""
    print(f"  ! {message}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{message}")


def cmd_fetch(args, conn):
    channels = conn.execute("SELECT id, title FROM channels").fetchall()
    if not channels:
        sys.exit("No channels yet. Add some with: python -m psx_yt add-channel @handle")
    mode = "YouTube Data API" if args.api_key else "RSS feed (latest ~15 videos; set YOUTUBE_API_KEY for more)"
    print(f"Fetching {len(channels)} channels via {mode}")
    api_key = args.api_key
    for ch in channels:
        name = ch["title"] or ch["id"]
        videos = None
        if api_key:
            try:
                title, videos = youtube.fetch_api(ch["id"], api_key, args.max)
            except (youtube.YouTubeError, OSError) as e:
                print(f"  ! {name}: YouTube Data API failed ({e}); using the RSS feed")
                if getattr(e, "status", None) in KEY_REJECTED:
                    # The key itself is the problem, so every channel would fail the same way.
                    api_key = None
                    warn(f"YouTube Data API rejected the key ({e}). Fetched the latest ~15 videos per channel "
                         "from RSS instead; check the YOUTUBE_API_KEY secret and its API restrictions.")
        if videos is None:
            try:
                title, videos = youtube.fetch_rss(ch["id"])
            except (youtube.YouTubeError, OSError) as e:
                print(f"  ! {name}: {e}")
                continue
        db.upsert_channel(conn, ch["id"], title)
        for v in videos:
            v["channel_id"] = ch["id"]
            db.upsert_video(conn, v)
        conn.commit()
        print(f"  {title or ch['id']}: {len(videos)} videos")
    if args.transcripts:
        fetch_transcripts(conn, retry=args.retry_captions)


DEFAULT_DAYS = 90  # look-back for top/report/export; trends still compare the last 7 days with the 7 before
CAPTION_GRACE = timedelta(days=2)  # YouTube can take a while to auto-generate captions for new uploads
MAX_FAILURES_IN_A_ROW = 5  # stop early when YouTube is blocking us rather than hammering it


def fetch_transcripts(conn, retry: bool = False):
    """Download captions for videos that have none stored yet.

    A video is marked caption-less ("") only when YouTube says it has none and it is older than CAPTION_GRACE;
    blocks and errors leave it NULL so the next run tries again.
    """
    if retry:
        print(f"Retrying captions for {db.reset_empty_transcripts(conn)} videos previously marked as having none")
    rows = db.videos_without_transcript(conn)
    print(f"Fetching captions for {len(rows)} videos")
    now = datetime.now(timezone.utc)
    counts = {"ok": 0, "none": 0, "blocked": 0, "error": 0}
    in_a_row = 0
    for i, r in enumerate(rows, 1):
        text, status, detail = youtube.fetch_transcript(r["id"])
        if status == "missing-lib":
            print("  ! youtube-transcript-api is not installed: pip install youtube-transcript-api")
            return
        counts[status] += 1
        if status in ("blocked", "error") and counts[status] == 1:
            print(f"  ! {r['id']}: {status} ({detail})")
        if status == "ok":
            conn.execute("UPDATE videos SET transcript = ? WHERE id = ?", (text, r["id"]))
        elif status == "none":
            published = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if now - published > CAPTION_GRACE:
                conn.execute("UPDATE videos SET transcript = '' WHERE id = ?", (r["id"],))
        in_a_row = in_a_row + 1 if status in ("blocked", "error") else 0
        if in_a_row >= MAX_FAILURES_IN_A_ROW:
            print(f"  ! {in_a_row} failures in a row ({status}); stopping, the rest will be tried next run")
            break
        if i % 20 == 0:
            conn.commit()
            print(f"  {i}/{len(rows)}")
    conn.commit()
    print("Captions: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    if counts["blocked"]:
        print("  YouTube is blocking caption requests from this network; they will be retried next run.")


def cmd_analyze(args, conn):
    analyzer = Analyzer(load_tickers(args.tickers))
    conn.execute("DELETE FROM mentions")
    conn.execute("DELETE FROM sector_mentions")
    n_videos = n_mentions = n_sectors = 0
    videos = conn.execute("SELECT id, channel_id, title, description, transcript FROM videos").fetchall()
    by_channel: dict[str, list[str]] = {}
    for v in videos:
        by_channel.setdefault(v["channel_id"], []).append(v["description"] or "")
    boilerplate = {cid: boilerplate_lines(descs) for cid, descs in by_channel.items()}
    titles: dict[str, set[str]] = {}
    for v in videos:
        titles.setdefault(v["channel_id"], set()).add(title_key(v["title"]))
    for v in videos:
        n_videos += 1
        description = strip_payment_details(strip_lines(v["description"], boilerplate[v["channel_id"]]))
        description = strip_video_titles(description, titles[v["channel_id"]] - {title_key(v["title"])})
        texts = (v["title"], description, v["transcript"])
        for table, found in (("mentions", analyze_video(analyzer, *texts)),
                             ("sector_mentions", analyze_video_sectors(analyzer, *texts))):
            for key, m in found.items():
                conn.execute(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (v["id"], key, m["title"], m["description"], m["transcript"], m["sentiment"], m["holds"]))
            if table == "mentions":
                n_mentions += len(found)
            else:
                n_sectors += len(found)
    conn.commit()
    print(f"Analyzed {n_videos} videos: {n_mentions} stock mentions, {n_sectors} sectors named outright")


def call_cell(s: dict) -> str:
    """'BUY 5/2/1' style: consensus, then buy/hold/sell video counts."""
    return f"{s['call']:<5} {s['bullish']}/{s['hold']}/{s['bearish']}"


def tone_cell(s: dict) -> str:
    """'IMPROVING +0.40' style summary of the week-over-week tone change."""
    return s["tone_trend"] if s["tone_change"] is None else f"{s['tone_trend']} {s['tone_change']:+.2f}"


def cmd_top(args, conn):
    data = compute(conn, load_tickers(args.tickers), days=args.days)
    print(f"PSX stocks on YouTube, {data['start']} to {data['end']} ({data['video_count']} videos)\n")
    print(f"{'#':>3}  {'Symbol':<8} {'Sector':<20} {'Buzz':>7} {'Videos':>6} {'Chan':>4} "
          f"{'7d':>4} {'prev':>4}  {'Trend':<8} {'Sent':>5}  {'Tone 7d':<16} {'Call (b/h/s)':<14}")
    for i, s in enumerate(data["stocks"][: args.limit], 1):
        print(f"{i:>3}  {s['symbol']:<8} {s['sector'][:20]:<20} {s['buzz']:>7} {s['videos']:>6} "
              f"{s['channel_count']:>4} {s['recent']:>4} {s['previous']:>4}  {s['trend']:<8} "
              f"{s['sentiment_score']:>+5.2f}  {tone_cell(s):<16} {call_cell(s):<14}")
    if not data["stocks"]:
        print("No mentions found. Run `fetch` and `analyze` first.")
    if data["sectors"]:
        print(f"\n     {'Sector':<20} {'Buzz':>7} {'Videos':>6} {'Named':>5} "
              f"{'7d':>4} {'prev':>4}  {'Trend':<8} {'Sent':>5}  {'Tone 7d':<16} {'Call (b/h/s)':<14} Stocks")
        for s in data["sectors"][: args.limit]:
            print(f"     {s['sector'][:20]:<20} {s['buzz']:>7} {s['videos']:>6} {s['direct_videos']:>5} "
                  f"{s['recent']:>4} {s['previous']:>4}  {s['trend']:<8} {s['sentiment_score']:>+5.2f}  "
                  f"{tone_cell(s):<16} {call_cell(s):<14} {' '.join(s['stocks'][:5])}")


REPORT_PERIODS = (7, 15, 21, 28, 90)  # look-backs the dashboard can switch between


def cmd_report(args, conn):
    stocks = load_tickers(args.tickers)
    periods = {d: compute(conn, stocks, days=d) for d in sorted({*REPORT_PERIODS, args.days})}
    path = write_report(periods, args.output, default=args.days)
    data = periods[args.days]
    print(f"Dashboard written to {path.resolve()} ({len(data['stocks'])} stocks, {len(data['sectors'])} sectors "
          f"over {args.days} days; also {', '.join(str(d) for d in periods if d != args.days)}-day views)")


EXPORT_FIELDS = ["symbol", "name", "sector", "buzz", "videos", "mentions", "title_videos", "channel_count", "recent",
                 "previous", "trend", "bullish", "neutral", "bearish", "sentiment_score", "tone_recent", "tone_previous",
                 "tone_change", "tone_trend", "hold", "call", "views", "summary"]
SECTOR_EXPORT_FIELDS = ["sector", "buzz", "videos", "direct_videos", "mentions", "title_videos", "channel_count",
                        "recent", "previous", "trend", "bullish", "neutral", "bearish", "sentiment_score",
                        "tone_recent", "tone_previous", "tone_change", "tone_trend", "hold", "call", "views", "summary"]


def cmd_export(args, conn):
    """Leaderboard as CSV (one row per stock, or per sector with --sectors) or JSON (everything the dashboard uses),
    picked by file extension."""
    data = compute(conn, load_tickers(args.tickers), days=args.days)
    if args.output.lower().endswith(".json"):
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    else:
        # utf-8-sig so Excel shows Urdu company names and channel titles correctly.
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            fields, rows = ((SECTOR_EXPORT_FIELDS, data["sectors"]) if args.sectors
                            else (EXPORT_FIELDS, data["stocks"]))
            extra = ["stocks", "channels"] if args.sectors else ["channels"]
            w = csv.DictWriter(f, ["rank", *fields, *extra], extrasaction="ignore")
            w.writeheader()
            for i, s in enumerate(rows, 1):
                w.writerow({**s, "rank": i, **{k: "; ".join(s[k]) for k in extra}})
    what = f"{len(data['sectors'])} sectors" if args.sectors and not args.output.lower().endswith(".json") \
        else f"{len(data['stocks'])} stocks"
    print(f"Exported {what} to {args.output}")


def cmd_run(args, conn):
    cmd_fetch(args, conn)
    cmd_analyze(args, conn)
    cmd_top(args, conn)
    cmd_report(args, conn)


DEMO_TEMPLATES = [
    ("{a} breakout! Target price and full technical analysis", 1),
    ("Should you buy {a}? Strong results and dividend expected", 1),
    ("{a} aur {b} mein tezi - kya abhi khareedain?", 1),
    ("Avoid {a} for now - bearish chart, sell on rally", -1),
    ("{a} crash: what went wrong? Losses explained", -1),
    ("PSX market update: {a}, {b} and {c} in focus today", 0),
    ("KSE-100 weekly review | {a} and {b} discussed", 0),
    ("Cement sector rally: {a} and {b} lead the way", 1),
    ("Refineries in momentum, {a} in focus", 1),
    ("Selling from banks - {a} under pressure", -1),
]
DEMO_WEIGHTS = {  # symbol: (popularity, bullishness, recent boost)
    "OGDC": (9, 0.6, 1.0), "HUBC": (8, 0.7, 1.8), "LUCK": (7, 0.5, 1.0), "MEBL": (7, 0.7, 1.2),
    "SYS": (6, 0.3, 0.5), "PPL": (6, 0.6, 1.0), "EFERT": (5, 0.6, 1.0), "FFC": (5, 0.7, 1.3),
    "KEL": (4, 0.2, 2.5), "TRG": (4, 0.3, 0.6), "PSO": (4, 0.5, 1.0), "MLCF": (3, 0.6, 1.6),
    "UBL": (3, 0.6, 1.0), "AIRLINK": (3, 0.5, 2.2), "SEARL": (2, 0.4, 0.8), "CNERGY": (2, 0.3, 1.0),
}
DEMO_TONE_SHIFT = {"KEL": 0.5, "SYS": 0.4, "HUBC": -0.4, "MEBL": -0.35}  # bullishness change in the last 7 days
DEMO_NAMES = {"OGDC": "OGDC", "HUBC": "Hub Power", "LUCK": "Lucky Cement", "MEBL": "Meezan Bank",
              "SYS": "Systems Limited", "PPL": "$PPL", "EFERT": "Engro Fertilizer", "FFC": "FFC", "KEL": "K-Electric",
              "TRG": "TRG", "PSO": "PSO", "MLCF": "MLCF", "UBL": "UBL", "AIRLINK": "AIRLINK", "SEARL": "Searle",
              "CNERGY": "CNERGY"}


def cmd_demo(args, conn):
    """Fill the database with synthetic videos so the dashboard can be tried without network access."""
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    channels = [(f"UCdemo{c * 22}"[:24], f"Demo Channel {c}") for c in "ABCDE"]
    for cid, title in channels:
        db.upsert_channel(conn, cid, title, "demo")
    syms = list(DEMO_WEIGHTS)
    for i in range(args.videos):
        age = rng.randint(0, 29)
        recent = age < 7
        weights = [DEMO_WEIGHTS[s][0] * (DEMO_WEIGHTS[s][2] if recent else 1) for s in syms]
        picks = []
        while len(picks) < 3:
            s = rng.choices(syms, weights)[0]
            if s not in picks:
                picks.append(s)
        bullish = rng.random() < DEMO_WEIGHTS[picks[0]][1] + (DEMO_TONE_SHIFT.get(picks[0], 0) if recent else 0)
        pool = [t for t, tone in DEMO_TEMPLATES if tone == 0 or (tone > 0) == bullish]
        title = rng.choice(pool).format(**{k: DEMO_NAMES[s] for k, s in zip("abc", picks)})
        cid, _ = rng.choice(channels)
        published = now - timedelta(days=age, hours=rng.randint(0, 20))
        db.upsert_video(conn, {
            "id": f"demo{i:07d}", "channel_id": cid, "title": title,
            "description": "Synthetic demo video for PSX YouTube Tracker.",
            "published_at": published.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "views": int(rng.lognormvariate(8.5, 1.0)),
        })
    conn.commit()
    print(f"Inserted {args.videos} synthetic videos across {len(channels)} demo channels")
    cmd_analyze(args, conn)
    cmd_top(args, conn)
    cmd_report(args, conn)


def main(argv=None):
    p = argparse.ArgumentParser(prog="psx_yt", description="Track which PSX stocks YouTube channels are discussing.")
    p.add_argument("--db", default="psx_yt.db", help="SQLite database file (default: psx_yt.db)")
    p.add_argument("--tickers", default="tickers_extra.csv", help="CSV of extra/override tickers")
    p.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY"),
                   help="YouTube Data API v3 key (default: $YOUTUBE_API_KEY); without it RSS feeds are used")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add-channel", help="Add channels by UC... id, @handle or URL")
    s.add_argument("refs", nargs="*")
    s.add_argument("--file", help="Text file with one channel per line (# comments allowed)")
    s.set_defaults(func=cmd_add_channel)

    sub.add_parser("channels", help="List tracked channels").set_defaults(func=cmd_channels)

    def fetch_opts(sp):
        sp.add_argument("--max", type=int, default=200, help="Max videos per channel in API mode")
        sp.add_argument("--transcripts", action="store_true", help="Also download captions (slower, more accurate)")
        sp.add_argument("--retry-captions", action="store_true",
                        help="With --transcripts: try again for videos previously marked as having no captions")

    def view_opts(sp):
        sp.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Look-back period in days")
        sp.add_argument("--limit", type=int, default=25, help="Rows to print")
        sp.add_argument("-o", "--output", default="report.html", help="Dashboard HTML file")

    s = sub.add_parser("fetch", help="Download video metadata from tracked channels")
    fetch_opts(s)
    s.set_defaults(func=cmd_fetch)
    sub.add_parser("analyze", help="Detect stock mentions in stored videos").set_defaults(func=cmd_analyze)
    s = sub.add_parser("top", help="Print the most discussed stocks")
    view_opts(s)
    s.set_defaults(func=cmd_top)
    s = sub.add_parser("report", help="Write the HTML dashboard")
    view_opts(s)
    s.set_defaults(func=cmd_report)
    s = sub.add_parser("export", help="Save the leaderboard as CSV or JSON (by file extension)")
    s.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Look-back period in days")
    s.add_argument("-o", "--output", default="psx_buzz.csv", help="Output file, .csv or .json")
    s.add_argument("--sectors", action="store_true", help="CSV of sectors instead of stocks")
    s.set_defaults(func=cmd_export)
    s = sub.add_parser("run", help="fetch + analyze + top + report")
    fetch_opts(s)
    view_opts(s)
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("demo", help="Try it offline with synthetic data (use a separate --db)")
    s.add_argument("--videos", type=int, default=300)
    view_opts(s)
    s.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    conn = db.connect(args.db)
    try:
        args.func(args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
