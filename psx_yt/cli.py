"""Command line interface: python -m psx_yt <command> ..."""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from . import db, youtube
from .analyzer import Analyzer, analyze_video
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


def cmd_fetch(args, conn):
    channels = conn.execute("SELECT id, title FROM channels").fetchall()
    if not channels:
        sys.exit("No channels yet. Add some with: python -m psx_yt add-channel @handle")
    mode = "YouTube Data API" if args.api_key else "RSS feed (latest ~15 videos; set YOUTUBE_API_KEY for more)"
    print(f"Fetching {len(channels)} channels via {mode}")
    for ch in channels:
        try:
            if args.api_key:
                title, videos = youtube.fetch_api(ch["id"], args.api_key, args.max)
            else:
                title, videos = youtube.fetch_rss(ch["id"])
        except (youtube.YouTubeError, OSError) as e:
            print(f"  ! {ch['title'] or ch['id']}: {e}")
            continue
        db.upsert_channel(conn, ch["id"], title)
        for v in videos:
            v["channel_id"] = ch["id"]
            db.upsert_video(conn, v)
        conn.commit()
        print(f"  {title or ch['id']}: {len(videos)} videos")
    if args.transcripts:
        ids = db.video_ids_without_transcript(conn)
        print(f"Fetching transcripts for {len(ids)} videos")
        for i, vid in enumerate(ids, 1):
            text = youtube.fetch_transcript(vid)
            # Store "" when captions are unavailable so we don't retry every run.
            conn.execute("UPDATE videos SET transcript = ? WHERE id = ?", (text or "", vid))
            if i % 20 == 0:
                conn.commit()
                print(f"  {i}/{len(ids)}")
        conn.commit()


def cmd_analyze(args, conn):
    analyzer = Analyzer(load_tickers(args.tickers))
    conn.execute("DELETE FROM mentions")
    n_videos = n_mentions = 0
    for v in conn.execute("SELECT id, title, description, transcript FROM videos").fetchall():
        n_videos += 1
        for sym, m in analyze_video(analyzer, v["title"], v["description"], v["transcript"]).items():
            conn.execute(
                "INSERT INTO mentions VALUES (?, ?, ?, ?, ?, ?)",
                (v["id"], sym, m["title"], m["description"], m["transcript"], m["sentiment"]),
            )
            n_mentions += 1
    conn.commit()
    print(f"Analyzed {n_videos} videos: {n_mentions} stock mentions")


def cmd_top(args, conn):
    data = compute(conn, load_tickers(args.tickers), days=args.days)
    print(f"PSX stocks on YouTube, {data['start']} to {data['end']} ({data['video_count']} videos)\n")
    print(f"{'#':>3}  {'Symbol':<8} {'Sector':<20} {'Buzz':>7} {'Videos':>6} {'Chan':>4} "
          f"{'7d':>4} {'prev':>4}  {'Trend':<8} {'Sent':>5}")
    for i, s in enumerate(data["stocks"][: args.limit], 1):
        print(f"{i:>3}  {s['symbol']:<8} {s['sector'][:20]:<20} {s['buzz']:>7} {s['videos']:>6} "
              f"{s['channel_count']:>4} {s['recent']:>4} {s['previous']:>4}  {s['trend']:<8} "
              f"{s['sentiment_score']:>+5.2f}")
    if not data["stocks"]:
        print("No mentions found. Run `fetch` and `analyze` first.")


def cmd_report(args, conn):
    data = compute(conn, load_tickers(args.tickers), days=args.days)
    path = write_report(data, args.output)
    print(f"Dashboard written to {path.resolve()} ({len(data['stocks'])} stocks)")


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
]
DEMO_WEIGHTS = {  # symbol: (popularity, bullishness, recent boost)
    "OGDC": (9, 0.6, 1.0), "HUBC": (8, 0.7, 1.8), "LUCK": (7, 0.5, 1.0), "MEBL": (7, 0.7, 1.2),
    "SYS": (6, 0.3, 0.5), "PPL": (6, 0.6, 1.0), "EFERT": (5, 0.6, 1.0), "FFC": (5, 0.7, 1.3),
    "KEL": (4, 0.2, 2.5), "TRG": (4, 0.3, 0.6), "PSO": (4, 0.5, 1.0), "MLCF": (3, 0.6, 1.6),
    "UBL": (3, 0.6, 1.0), "AIRLINK": (3, 0.5, 2.2), "SEARL": (2, 0.4, 0.8), "CNERGY": (2, 0.3, 1.0),
}
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
        bullish = rng.random() < DEMO_WEIGHTS[picks[0]][1]
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

    def view_opts(sp):
        sp.add_argument("--days", type=int, default=30, help="Look-back period in days")
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
