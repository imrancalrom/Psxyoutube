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
   from cloud servers; the run log then says so (`Captions: 0 ok, 0 none, 5 blocked, ...`) and those videos are
   retried on the next run.
3. Run it once from the Actions tab ("Daily PSX YouTube run" → Run workflow) to check it works.

Each run keeps the database, the latest `report.html`, `psx_buzz.csv` and `psx_sectors.csv` on a `data` branch, replaced by one fresh
commit each day. The database already holds the full history, so old copies are not kept. The leaderboard appears in
the run summary, and the report and CSVs can be downloaded from the run's artifacts. A manual run can also tick
"Retry videos earlier marked as having no captions". To work with the data locally:
`git fetch origin data && git show origin/data:psx_yt.db > psx_yt.db`.

### Getting more data

| Mode | Setup | What you get |
|------|-------|--------------|
| RSS (default) | nothing | latest ~15 videos per channel: title, description, views |
| YouTube Data API v3 | `export YOUTUBE_API_KEY=...` ([get a key](https://console.cloud.google.com/apis/library/youtube.googleapis.com)) | full upload history (`--max 200` per channel) |
| Transcripts | `fetch --transcripts` / `run --transcripts` | reads Urdu/English captions, catching stocks only mentioned out loud |

If the API fails (bad key, wrong API restrictions, quota used up), that channel is fetched from RSS instead, and
when the key itself is rejected (HTTP 400/401/403) the rest of the run uses RSS too; in GitHub Actions this shows
as a warning on the run. Error messages never include the key.

A video is marked as having no captions only when YouTube says so and it is more than 2 days old (auto-captions can
take a while). Blocked or failed requests are left for the next run, and fetching stops after 5 failures in a row.
`--retry-captions` tries the videos marked caption-less again.

#### Captions from your own computer

YouTube blocks caption requests from GitHub's servers (`RequestBlocked`), so the daily workflow can't read them.
Captions matter: most buy/hold/sell calls are spoken, not written in titles. Fetch them from a laptop or PC on a
normal internet connection (not a phone):

**One-time setup**

1. Install **Python 3.10+** ([python.org/downloads](https://www.python.org/downloads/); on Windows tick
   "Add python.exe to PATH") and **Git** ([git-scm.com/downloads](https://git-scm.com/downloads)).
2. Sign Git in to GitHub so it can push. The easiest way is **GitHub Desktop**
   ([desktop.github.com](https://desktop.github.com)): sign in, then *File → Clone repository →
   imrancalrom/Psxyoutube*. Or from a terminal: `git clone https://github.com/imrancalrom/Psxyoutube.git`
   (Git asks you to sign in on the first push).
3. In a terminal opened in the `Psxyoutube` folder (GitHub Desktop: *Repository → Open in Command Prompt/Terminal*):

   ```bash
   pip install -r requirements.txt
   git config user.name "Your Name"            # once, if Git asks who you are
   git config user.email "you@example.com"
   ```

**Each time**

- **Windows**: double-click **`captions.bat`** in the `Psxyoutube` folder.
- **Mac / Linux**: in a terminal opened in the folder, run `bash captions.sh`.

The launcher updates the code (`git pull`), then fetches captions in **rounds of 300 videos, newest first**
(about 5–10 minutes each) with a 15-minute pause between rounds, until no video is waiting or YouTube starts
limiting the connection. Each round re-runs the analysis and is pushed to the `data` branch straight away, so you
can close the window at any time and lose at most the round in progress. The dashboard shows the new data after the
next workflow run (21:17 PKT, or start one from the Actions tab); its header and the digest say how many videos have
had their captions read. The first catch-up of ~2,000 videos takes about seven rounds (roughly three hours if
YouTube doesn't interrupt); after that, run it every week or so. Each round ends like this:

```
Captions: 280 ok, 15 none, 5 blocked, 0 error
...
Pushed. The next workflow run (21:17 PKT, or start one from the Actions tab) will show it on the dashboard.
New buy/sell calls found (6):
  2026-10-30  BUY  OGDC     Stockifyy: Buy OGDC and PPL ...
Captions: 580 of 2052 videos read, 40 have none, 1432 still waiting
```

- **"YouTube is limiting this connection"**: wait a few hours (or try another network) and run it again; nothing
  is lost.
- **"The data branch changed meanwhile"**: the daily workflow finished during the round. The script adds your
  captions to the newer data and pushes again by itself.
- **"none"** means the video has no captions; those aren't asked for again (`--retry` asks again).

Without the launcher: `python scripts/local_captions.py` runs one round; add `--rounds 0` to keep going, `--rounds N`
for N rounds, `--pause M` for M minutes between rounds.

More options: `--limit N` sets the videos per round (`0` = every waiting video in one go; YouTube may block a long run), `--retry` retries videos
marked as having no captions, and `--no-push --keep out/` saves the files locally without pushing. Your files and
current branch are never changed, and the push never overwrites newer data (nor does the workflow overwrite a push
made during its run).

## Commands

| Command | Does |
|---------|------|
| `add-channel REF... [--file F]` | add channels by `@handle`, channel URL (`/@name`, `/channel/`, `/c/`, `/user/`) or `UC...` id |
| `channels` | list tracked channels and video counts |
| `fetch [--transcripts] [--retry-captions] [--max N]` | download video metadata (and captions) |
| `analyze` | detect stock and sector mentions in all stored videos |
| `top [--days 90] [--limit 25]` | print the most discussed stocks and sectors |
| `report [--days 90] [-o report.html]` | write the HTML dashboard |
| `export [--days 90] [--sectors] [-o psx_buzz.csv]` | save the stock (or sector) leaderboard as CSV (opens in Excel), or everything as `.json` |
| `digest [-o digest.md]` | short "what changed" note: last 24 hours, this week vs last week, sector shifts |
| `run` | fetch + analyze + top + report |
| `demo [--videos 300]` | synthetic data to try the dashboard |

Global options: `--db FILE`, `--api-key KEY`, `--tickers extra.csv`.

## How it works

1. **Detection** (`psx_yt/analyzer.py`, `psx_yt/tickers.py`): ~90 PSX stocks (KSE-100 heavyweights and popular names)
   with their symbol, company name and common aliases in English, Roman Urdu and Urdu script
   (`OGDC`, `ogdcl`, `Hub Power`, `hubco`, `حب پاور`, ...). Longest match wins, so "Engro Fertilizer" counts as
   EFERT rather than ENGROH. Symbols that are ordinary words (`POWER`, `LUCK`, `PPL`, `UNITY`, `MARI`...) only count
   when tagged (`$LUCK`, `#PPL`) or named in full ("Lucky Cement").
   **Sectors** are also picked up when named outright: *banks, cement, E&P, oil & gas, OMCs, refineries, IPPs,
   fertilizer, autos, pharma, textile, FMCG, steel...* plus Urdu (`سیمنٹ`, `ریفائنری`, `کھاد`...). Words that are too
   general are left out (a bare "bank" would catch "State Bank", "real estate" usually means property), and a sector word inside a stock's name
   ("Lucky Cement") counts as the stock. Description lines a channel repeats under most of its videos (links, hashtag
   blocks like `#banking`) are ignored, so they don't count for every upload, and so are bank-account details
   posted for course fees ("MCB / ACCOUNT: ... / IBAN: ..."), which would otherwise count as MCB, BOP..., and
   lines that are the title of another of the channel's videos ("WATCH OUR MOST USEFUL VIDEOS" link lists).
2. **Sentiment**: the clause around each mention is scored with bullish/bearish cue words
   (*buy, breakout, target, tezi, khareedain, منافع* vs *sell, crash, avoid, girawat, mandi, نقصان*), with simple
   negation ("don't buy", "mat khareedo"). Clauses are split on commas and contrast words (*but, vs, lekin, magar,
   لیکن*), so "Buy OGDC, sell PSO" is bullish OGDC and bearish PSO; a clause with no cue words takes the tone of
   its whole sentence ("OGDC, HUBC and PSO: buy all three"). Questions ("Is OGDC still undervalued?") and lists of
   options ("BUY & SELL & HOLD", "entry or exit") carry no tone.
   **Tone and calls are kept apart.** Tone uses the broad word list above and feeds the sentiment bar and tone trend.
   A *call* needs an explicit recommendation: *buy, accumulate, top pick, multibagger, price target 23, khareedain*
   vs *sell, avoid, exit, book profits, becho*. Market descriptions don't count as calls: money flows ("foreign
   buying", "selling pressure", "retail traders are buying"), how-to phrases ("how to buy", "buy order", "buying and
   selling", "how to find multibagger stocks"), "we break down…", "stop loss" and dividend news. Calls drive the
   YouTube call column, the digest's call lines and the channel track record.
3. **Trends** (`psx_yt/trends.py`), over the look-back period (90 days by default, `--days N` to change):
   - **Buzz**: sum over videos of `(2 if in title else 1) × (1 + log10(1 + views))`
   - **Last 7d vs prev 7d** video counts give the trend label: `NEW`, `RISING` (≥1.5×), `STEADY`, `FALLING` (≤0.67×)
   - **Sentiment**: share of bullish / neutral / bearish videos, net score from −1 to +1
   - **YouTube call**: how many videos made an explicit buy, hold or sell call ("hold", "keep holding", "stay invested",
     "hold karein/rakhein", "ہولڈ" are hold calls; buy or sell in the same clause wins, and "holding company" or
     "Engro Holdings" don't count). The label is `BUY`, `HOLD` or `SELL` when one call has at least half of 3+ calls,
     `MIXED` otherwise, `-` with fewer. It reports what the channels said; it is not a recommendation.
   - **Tone trend**: net sentiment in the last 7 days vs the 7 days before, labelled `IMPROVING` (up ≥0.25),
     `WORSENING` (down ≥0.25) or `STABLE`. Each week needs 3+ videos, otherwise it shows `-`, so one video can't
     flip the label. Useful for spotting a stock whose buzz is rising while the tone turns bearish.
   - channel breadth, total views, daily series, latest videos per stock
   - **Sectors** get the same stats, counting every video that names the sector *or* one of its stocks, so
     "Selling from Banks" and "Buy MEBL" both count for Banks. `Named` is how many videos named the sector itself.
4. **Daily digest**: each run also writes a short "what changed" note (`digest.md` on the `data` branch, the top of
   the GitHub run page, and a box at the top of the dashboard): the last 24 hours' videos, stocks and calls; stocks
   newly discussed this week; buzz rising and fading; this week's buy/hold/sell calls; sector shifts; and
   **technical signals** for the discussed stocks, those whose buzz is rising first.
5. **Channel track record** (`psx_yt/track.py`): every buy/sell call on a stock with prices is entered at the close
   of the first trading day after the video and scored 5 and 20 trading days later: the share that went the called
   way, the average move in the called direction, and that minus the average move of all priced stocks over the same
   days ("vs market"). Channels with fewer than 5 scored calls are greyed; hold calls aren't scored. Prices are
   cleaned first: Yahoo's PSX history switches between split-adjusted and unadjusted prices and has short glitches,
   so moves beyond PSX's daily limit (10%, or Rs 1) are dropped as glitches or, if lasting, only the data after them
   is kept. The scores are only as good as the keyword call detection, and past results don't predict future ones.
   The **call log** on the dashboard lists every explicit call (buy, sell and hold, including stocks without prices),
   newest first, with the entry close, the move since the call to the latest close, the 5- and 20-day moves and the
   20-day result vs the market, and a link to the video; filter it by stock, channel or call. An opened stock shows
   its own calls the same way.
6. **Dashboard** (`report.html`, one self-contained file: no internet needed, so it also opens offline, from a
   download or inside app file previews): leaderboard tiles (including tone improving / worsening most), trend chart for the top 5 (daily up to 31 days, weekly for longer periods), buzz by sector,
   a sortable sectors table and a sortable/filterable stocks table; click a row to see the videos behind it.
   A **Period** switch shows the last 7, 15, 21, 28 or 90 days (every view is computed when the report is written, so
   switching is instant; the link remembers it, e.g. `report.html#28`), and the stocks table filters by sector,
   YouTube call and minimum videos. The week-over-week columns always compare the last 7 days with the 7 before.
   Opening a stock shows a **technical chart** drawn from daily closes that each run downloads from **Yahoo Finance**
   (`<symbol>.KA`; only used after checking Yahoo says it is that symbol on the Karachi exchange in PKR, and only the
   daily closes, since Yahoo's "current price" field disagrees with them for PSX stocks; `prices` command, part of
   `run`, `--no-prices` skips it; the PSX data portal refuses GitHub's servers): close with SMA 50 / SMA 200, support (green) and
   resistance (red) levels from swing highs/lows over the past year with how often price touched them, and an RSI 14
   panel with 30/70 bands, plus a one-line summary ("Close 308 (+0.6%) · above SMA 50, below SMA 200 · RSI 62 ·
   support 290 (3×) · resistance 320 (2×)"; MACD 12/26/9, SMA 20 and the 52-week range are in the data too). It
   needs no internet to view. Every stock links to its chart and overview on **TradingView**'s site, which has PSX
   prices and indicators (Pivot Points Standard for support/resistance, moving averages, RSI, MACD). TradingView's
   embeddable chart isn't used: it doesn't carry PSX stocks and silently shows a different company (Apple) instead.
   **Technical signals** (labels on each stock, a "Signal" filter, and the list above its chart): near support or
   resistance (within 2% of a level price has touched at least twice), tight range (near both), RSI oversold (≤30) or
   overbought (≥70), golden/death cross (SMA 50 crossing SMA 200 in the last 20 trading days), and 52-week high/low.
   These are mechanical calculations, not advice.
   Each stock has a one-line summary built from its numbers (also the `summary` column in the CSVs), e.g.
   "23 videos on 8 channels · 3 this week, none the week before · calls split: 3 buy, 3 sell".

### Adding stocks

Copy `tickers_extra.example.csv` to `tickers_extra.csv` and add rows (aliases separated by `;`).
Rows override built-in stocks with the same symbol. Then run `python -m psx_yt analyze`.
Sector words live in `SECTOR_ALIASES` in `psx_yt/tickers.py`.

## Tests

```bash
python -m unittest -v
```

## Limits

- Tone and calls are keyword based: sarcasm and meaning carried across sentences are missed. Calls are deliberately
  strict, so they miss some real recommendations rather than count descriptions as calls; with captions more are found.
- Without transcripts only titles and descriptions are read, so stocks discussed only verbally are missed.
- Not investment advice.
