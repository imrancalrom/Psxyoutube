# PSX YouTube Tracker

Reads YouTube channels that talk about the Pakistan Stock Exchange, works out **which PSX stocks are being discussed**,
and shows **how that buzz is trending**: which stocks are rising, which are fading, and whether the tone is bullish or bearish.

## Quick start

```bash
pip install -r requirements.txt

# 1. Try it offline with synthetic data
python -m psx_yt --db demo.db demo -o demo_report.html     # open demo_report.html

# 2. Track real channels
python -m psx_yt add-channel @SomePsxChannel https://www.youtube.com/@AnotherOne
#    or: cp channels.example.txt channels.txt, edit it, then
python -m psx_yt add-channel --file channels.txt

# 3. Fetch, analyse, print the leaderboard and write report.html
python -m psx_yt run
```

Re-run `python -m psx_yt run` daily (cron / Task Scheduler) to build up history; videos are stored in `psx_yt.db`.

### Daily runs on GitHub Actions

`.github/workflows/daily.yml` runs the tracker every day at 21:17 Pakistan time (16:17 UTC), so nothing has to run on
your own machine:

1. Copy `channels.example.txt` to `channels.txt`, list your channels and commit it.
2. Optional: add a `YOUTUBE_API_KEY` repository secret (Settings → Secrets and variables → Actions) for full upload
   history, and a `FETCH_TRANSCRIPTS` variable set to `true` to read captions. YouTube often blocks caption requests
   from cloud servers, so transcripts may come back empty there.
3. Run it once from the Actions tab ("Daily PSX YouTube run" → Run workflow) to check it works.

Each run keeps the database, the latest `report.html` and `psx_buzz.csv` on a `data` branch, replaced by one fresh
commit each day. The database already holds the full history, so old copies are not kept. The leaderboard appears in
the run summary, and the report and CSV can be downloaded from the run's artifacts. To work with the data locally:
`git fetch origin data && git show origin/data:psx_yt.db > psx_yt.db`.

### Getting more data

| Mode | Setup | What you get |
|------|-------|--------------|
| RSS (default) | nothing | latest ~15 videos per channel: title, description, views |
| YouTube Data API v3 | `export YOUTUBE_API_KEY=...` ([get a key](https://console.cloud.google.com/apis/library/youtube.googleapis.com)) | full upload history (`--max 200` per channel) |
| Transcripts | `fetch --transcripts` / `run --transcripts` | reads Urdu/English captions, catching stocks only mentioned out loud |

## Commands

| Command | Does |
|---------|------|
| `add-channel REF... [--file F]` | add channels by `@handle`, channel URL (`/@name`, `/channel/`, `/c/`, `/user/`) or `UC...` id |
| `channels` | list tracked channels and video counts |
| `fetch [--transcripts] [--max N]` | download video metadata (and captions) |
| `analyze` | detect stock mentions in all stored videos |
| `top [--days 30] [--limit 25]` | print the most discussed stocks |
| `report [--days 30] [-o report.html]` | write the HTML dashboard |
| `export [--days 30] [-o psx_buzz.csv]` | save the leaderboard as CSV (opens in Excel), or everything as `.json` |
| `run` | fetch + analyze + top + report |
| `demo [--videos 300]` | synthetic data to try the dashboard |

Global options: `--db FILE`, `--api-key KEY`, `--tickers extra.csv`.

## How it works

1. **Detection** (`psx_yt/analyzer.py`, `psx_yt/tickers.py`): ~90 PSX stocks (KSE-100 heavyweights and popular names)
   with their symbol, company name and common aliases in English, Roman Urdu and Urdu script
   (`OGDC`, `ogdcl`, `Hub Power`, `hubco`, `حب پاور`, ...). Longest match wins, so "Engro Fertilizer" counts as
   EFERT rather than ENGROH. Symbols that are ordinary words (`POWER`, `LUCK`, `PPL`, `UNITY`, `MARI`...) only count
   when tagged (`$LUCK`, `#PPL`) or named in full ("Lucky Cement").
2. **Sentiment**: the clause around each mention is scored with bullish/bearish cue words
   (*buy, breakout, target, tezi, khareedain, منافع* vs *sell, crash, avoid, girawat, mandi, نقصان*), with simple
   negation ("don't buy", "mat khareedo"). Clauses are split on commas and contrast words (*but, vs, lekin, magar,
   لیکن*), so "Buy OGDC, sell PSO" is bullish OGDC and bearish PSO; a clause with no cue words takes the tone of
   its whole sentence ("OGDC, HUBC and PSO: buy all three").
3. **Trends** (`psx_yt/trends.py`), over the look-back period:
   - **Buzz**: sum over videos of `(2 if in title else 1) × (1 + log10(1 + views))`
   - **Last 7d vs prev 7d** video counts give the trend label: `NEW`, `RISING` (≥1.5×), `STEADY`, `FALLING` (≤0.67×)
   - **Sentiment**: share of bullish / neutral / bearish videos, net score from −1 to +1
   - **Tone trend**: net sentiment in the last 7 days vs the 7 days before, labelled `IMPROVING` (up ≥0.25),
     `WORSENING` (down ≥0.25) or `STABLE`. Each week needs 3+ videos, otherwise it shows `-`, so one video can't
     flip the label. Useful for spotting a stock whose buzz is rising while the tone turns bearish.
   - channel breadth, total views, daily series, latest videos per stock
4. **Dashboard** (`report.html`): leaderboard tiles (including tone improving / worsening most), daily trend chart for the top 5, buzz by sector,
   and a sortable/filterable table; click a stock to see the videos behind it.

### Adding stocks

Copy `tickers_extra.example.csv` to `tickers_extra.csv` and add rows (aliases separated by `;`).
Rows override built-in stocks with the same symbol. Then run `python -m psx_yt analyze`.

## Tests

```bash
python -m unittest -v
```

## Limits

- Sentiment is keyword based: sarcasm, questions ("should you buy?") and tone carried across sentences are missed.
- Without transcripts only titles and descriptions are read, so stocks discussed only verbally are missed.
- Not investment advice.
