"""Fetch captions from your own computer and push them to the `data` branch.

YouTube blocks caption requests from GitHub's servers, so the daily workflow can't read them. Run this from a
normal internet connection now and then; the next workflow run picks the captions up from the data branch.
The easiest way is to double-click captions.bat (Windows) or run `bash captions.sh` (Mac/Linux), which update the
code first and keep going until every video is done.

    pip install -r requirements.txt
    python scripts/local_captions.py              # one round: up to 300 videos still waiting, newest first, then push
    python scripts/local_captions.py --rounds 0   # rounds until nothing waits (or YouTube blocks), pushing each one
    python scripts/local_captions.py --retry      # also retry videos marked as having no captions
    python scripts/local_captions.py --no-push    # fetch and analyze, but leave the data branch alone

Your working tree and current branch are not touched: the new data commit is built with git plumbing. Every round
is pushed as soon as it is done, so stopping the script (Ctrl+C, closing the window) loses at most the round in
progress. If the data branch changed meanwhile (the daily workflow finished), the captions are copied into the
newer data and pushed again, so nothing is overwritten and nothing has to be fetched twice.
"""

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from psx_yt import cli, db  # noqa: E402

BRANCH = "data"
FILES = ["psx_yt.db", "report.html", "psx_buzz.csv", "psx_sectors.csv", "digest.md"]
PUSH_ATTEMPTS = 3


def git(*args: str, input: bytes | None = None) -> bytes:
    r = subprocess.run(["git", *args], cwd=ROOT, input=input, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def load_base(remote: str, dbfile: Path) -> str:
    """Download the data branch's database to `dbfile`; returns the commit it came from."""
    print(f"Fetching the {BRANCH} branch from {remote}")
    git("fetch", "--quiet", remote, BRANCH)
    base = git("rev-parse", "FETCH_HEAD").decode().strip()
    dbfile.write_bytes(git("show", f"{base}:psx_yt.db"))
    return base


def apply_captions(conn, fetched: dict[str, str]) -> None:
    """Put captions fetched by this script into a (possibly newer) database. A caption fills in a video that has
    none stored or is marked caption-less; a "no captions" mark only fills in a video not tried yet."""
    for vid, text in fetched.items():
        if text:
            conn.execute("UPDATE videos SET transcript = ? WHERE id = ? AND (transcript IS NULL OR transcript = '')",
                         (text, vid))
        else:
            conn.execute("UPDATE videos SET transcript = '' WHERE id = ? AND transcript IS NULL", (vid,))
    conn.commit()


def explicit_calls(conn) -> set[tuple[str, str, int]]:
    return {(r[0], r[1], 1 if r[2] > 0 else -1)
            for r in conn.execute("SELECT video_id, symbol, calls FROM mentions WHERE calls != 0")}


def build_outputs(dbfile: Path, out: Path) -> None:
    dbarg = ["--db", str(dbfile)]
    cli.main([*dbarg, "analyze"])
    cli.main([*dbarg, "report", "-o", str(out / "report.html")])
    cli.main([*dbarg, "export", "-o", str(out / "psx_buzz.csv")])
    cli.main([*dbarg, "export", "--sectors", "-o", str(out / "psx_sectors.csv")])
    cli.main([*dbarg, "digest", "-o", str(out / "digest.md")])


def push(remote: str, base: str, out: Path) -> bool:
    """One fresh commit holding just the files, like the workflow makes (the database keeps the history), pushed only
    if the data branch is still at `base`. False when it moved on meanwhile."""
    entries = []
    for name in FILES:
        blob = git("hash-object", "-w", "--", str(out / name)).decode().strip()
        entries.append(f"100644 blob {blob}\t{name}\n")
    tree = git("mktree", input="".join(entries).encode()).decode().strip()
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = git("commit-tree", tree, "-m", f"Data as of {when} (captions fetched locally)").decode().strip()
    print(f"Pushing to {remote}/{BRANCH}")
    r = subprocess.run(["git", "push", f"--force-with-lease=refs/heads/{BRANCH}:{base}", remote,
                        f"{commit}:refs/heads/{BRANCH}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        return True
    if "stale info" in r.stderr or "rejected" in r.stderr:
        return False
    sys.exit(f"git push failed:\n{r.stderr.strip()}")


def describe_new_calls(conn, new: set[tuple[str, str, int]]) -> None:
    if not new:
        print("No new buy/sell calls found in these captions.")
        return
    print(f"New buy/sell calls found ({len(new)}):")
    rows = []
    for vid, sym, call in new:
        v = conn.execute("SELECT v.title, v.published_at, COALESCE(c.title, v.channel_id) FROM videos v "
                         "LEFT JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (vid,)).fetchone()
        rows.append((v[1] or "", sym, call, v[2], v[0]))
    for published, sym, call, channel, title in sorted(rows, reverse=True)[:20]:
        print(f"  {published[:10]}  {'BUY ' if call > 0 else 'SELL'} {sym:<8} {channel}: {title[:60]}")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more (see the dashboard after the next workflow run)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--remote", default="origin")
    p.add_argument("--retry", action="store_true", help="also retry videos marked as having no captions")
    p.add_argument("--limit", type=int, default=300,
                   help="videos per round, newest first (default 300, about 5-10 minutes; 0 = all). YouTube tends to "
                        "block home connections that ask for hundreds of captions in a row")
    p.add_argument("--rounds", type=int, default=1,
                   help="rounds to run (default 1; 0 = until no video is waiting or YouTube blocks)")
    p.add_argument("--pause", type=float, default=15, help="minutes to wait between rounds (default 15)")
    p.add_argument("--no-push", action="store_true", help="don't update the data branch")
    p.add_argument("--keep", help="also copy the updated files to this folder")
    args = p.parse_args(argv)

    fetched: dict[str, str] = {}  # every caption (or "none" mark) this run fetched: video id -> text
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        dbfile = out / "psx_yt.db"
        base = load_base(args.remote, dbfile)
        for rnd in count(1):
            if rnd > 1:
                print(f"\n=== Round {rnd} ===")
                if not args.no_push:
                    base = load_base(args.remote, dbfile)  # picks up a workflow run that finished meanwhile

            conn = db.connect(str(dbfile))
            try:
                apply_captions(conn, fetched)
                before = explicit_calls(conn)
                retry = args.retry and rnd == 1
                untried = {r[0] for r in conn.execute(
                    "SELECT id FROM videos WHERE transcript IS NULL" + (" OR transcript = ''" if retry else ""))}
                counts = cli.fetch_transcripts(conn, retry=retry, limit=args.limit or None)
                if counts is None:
                    sys.exit("Install the requirements first: pip install -r requirements.txt")
                for vid, text in conn.execute("SELECT id, transcript FROM videos WHERE transcript IS NOT NULL"):
                    if vid in untried:
                        fetched[vid] = text
            finally:
                conn.close()

            build_outputs(dbfile, out)
            if args.keep:
                Path(args.keep).mkdir(parents=True, exist_ok=True)
                for name in FILES:
                    shutil.copy2(out / name, Path(args.keep) / name)
                print(f"Copied the files to {Path(args.keep).resolve()}")

            if args.no_push:
                print("--no-push: data branch left as it was")
            else:
                for attempt in range(1, PUSH_ATTEMPTS + 1):
                    if push(args.remote, base, out):
                        print("Pushed. The next workflow run (21:17 PKT, or start one from the Actions tab) will "
                              "show it on the dashboard.")
                        break
                    if attempt == PUSH_ATTEMPTS:
                        sys.exit(f"The {BRANCH} branch kept changing while this ran, so nothing was pushed. "
                                 "Run this again in a few minutes.")
                    print(f"The {BRANCH} branch changed meanwhile (probably the daily workflow); "
                          "adding your captions to the newer data and pushing again")
                    base = load_base(args.remote, dbfile)
                    conn = db.connect(str(dbfile))
                    try:
                        apply_captions(conn, fetched)
                    finally:
                        conn.close()
                    build_outputs(dbfile, out)

            conn = db.connect(str(dbfile))
            try:
                describe_new_calls(conn, explicit_calls(conn) - before)
                stats = db.caption_stats(conn)
            finally:
                conn.close()
            print(f"Captions: {stats['read']} of {stats['total']} videos read, {stats['none']} have none, "
                  f"{stats['waiting']} still waiting")

            if not stats["waiting"]:
                print("All caught up. Run this again every week or so for new videos.")
                break
            per_round = args.limit or stats["waiting"]
            left = math.ceil(stats["waiting"] / per_round)
            if counts["stopped"] or (counts["blocked"] and not counts["ok"]):
                print("YouTube is limiting this connection. Wait a few hours (or use another network) and run "
                      f"again; about {left} more round{'s' if left != 1 else ''} to go. Nothing is lost.")
                break
            if args.rounds and rnd >= args.rounds:
                print(f"About {left} more round{'s' if left != 1 else ''} to catch up: run this again "
                      "(or with --rounds 0 to keep going).")
                break
            print(f"Waiting {args.pause:g} minutes before the next round, so YouTube doesn't block this connection "
                  "(Ctrl+C to stop; everything so far is saved)")
            time.sleep(args.pause * 60)


if __name__ == "__main__":
    main()
