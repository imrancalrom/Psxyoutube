#!/usr/bin/env bash
# Fetch YouTube captions from this computer and push them to the dashboard's data: `bash captions.sh`.
# Keeps going in rounds of 300 videos (15-minute pauses) until every video is done or YouTube says "slow down".
# Stop at any time with Ctrl+C: every finished round is already saved.
set -e
cd "$(dirname "$0")"
echo "Updating the code..."
git pull --ff-only
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
"$PY" -m pip install --quiet -r requirements.txt
"$PY" scripts/local_captions.py --rounds 0 "$@"
