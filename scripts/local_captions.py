"""Fetch captions from your own computer and push them to the `data` branch.

YouTube blocks caption requests from GitHub's servers, so the daily workflow can't read them. Run this from a
normal internet connection now and then; the next workflow run picks the captions up from the data branch.

    pip install -r requirements.txt
    python scripts/local_captions.py            # captions for videos still waiting for them, then push
    python scripts/local_captions.py --retry    # also retry videos marked as having no captions
    python scripts/local_captions.py --no-push  # fetch and analyze, but leave the data branch alone

Your working tree and current branch are not touched: the new data commit is built with git plumbing. The push
is refused if the data branch changed while this ran (e.g. a workflow run finished), so nothing is overwritten;
just run it again.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from psx_yt import cli, db  # noqa: E402

BRANCH = "data"
FILES = ["psx_yt.db", "report.html", "psx_buzz.csv", "psx_sectors.csv"]


def git(*args: str, input: bytes | None = None) -> bytes:
    r = subprocess.run(["git", *args], cwd=ROOT, input=input, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--remote", default="origin")
    p.add_argument("--retry", action="store_true", help="also retry videos marked as having no captions")
    p.add_argument("--no-push", action="store_true", help="don't update the data branch")
    p.add_argument("--keep", help="also copy the updated files to this folder")
    args = p.parse_args(argv)

    print(f"Fetching the {BRANCH} branch from {args.remote}")
    git("fetch", "--quiet", args.remote, BRANCH)
    base = git("rev-parse", "FETCH_HEAD").decode().strip()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        dbfile = out / "psx_yt.db"
        dbfile.write_bytes(git("show", f"{base}:psx_yt.db"))

        conn = db.connect(str(dbfile))
        try:
            cli.fetch_transcripts(conn, retry=args.retry)
            got = conn.execute("SELECT COUNT(*) FROM videos WHERE length(transcript) > 0").fetchone()[0]
        finally:
            conn.close()
        print(f"{got} videos now have captions")

        dbarg = ["--db", str(dbfile)]
        cli.main([*dbarg, "analyze"])
        cli.main([*dbarg, "report", "-o", str(out / "report.html")])
        cli.main([*dbarg, "export", "-o", str(out / "psx_buzz.csv")])
        cli.main([*dbarg, "export", "--sectors", "-o", str(out / "psx_sectors.csv")])

        if args.keep:
            Path(args.keep).mkdir(parents=True, exist_ok=True)
            for name in FILES:
                shutil.copy2(out / name, Path(args.keep) / name)
            print(f"Copied the files to {Path(args.keep).resolve()}")
        if args.no_push:
            print("--no-push: data branch left as it was")
            return

        # One fresh commit holding just these files, like the workflow makes; the database keeps the history.
        entries = []
        for name in FILES:
            blob = git("hash-object", "-w", "--", str(out / name)).decode().strip()
            entries.append(f"100644 blob {blob}\t{name}\n")
        tree = git("mktree", input="".join(entries).encode()).decode().strip()
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        commit = git("commit-tree", tree, "-m", f"Data as of {when} (captions fetched locally)").decode().strip()

    print(f"Pushing to {args.remote}/{BRANCH}")
    r = subprocess.run(["git", "push", f"--force-with-lease=refs/heads/{BRANCH}:{base}", args.remote,
                        f"{commit}:refs/heads/{BRANCH}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        if "stale info" in r.stderr or "rejected" in r.stderr:
            sys.exit(f"The {BRANCH} branch changed while this ran (probably a workflow run), so nothing was pushed. "
                     "Run this script again; captions already fetched will be fetched again.")
        sys.exit(f"git push failed:\n{r.stderr.strip()}")
    print("Done. The next workflow run will start from this data.")


if __name__ == "__main__":
    main()
