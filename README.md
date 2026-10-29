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

### Getting more data

| Mode | Setup | What you get |
|------|-------|--------------|
| RSS (default) | nothing | latest ~15 videos per channel: title, description, views |
| YouTube Data API v3 | `export YOUTUBE_API_KEY=...` ([get a key](https://console.cloud.google.com/apis/library/youtube.googleapis.com)) | full upload history (`--max 200` per channel) |
| Transcripts | `fetch --transcripts` / `run --transcripts` | reads Urdu/English captions, catching stocks only mentioned out loud |

## Commands

| Command | Does |
|---------|------|
| `add-channel REF... [--file F]` | add channels by `@handle`, URL or `UC...` id |
| `channels` | list tracked channels and video counts |
| `fetch [--transcripts] [--max N]` | download video metadata (and captions) |
| `analyze` | detect stock mentions in all stored videos |
| `top [--days 30] [--limit 25]` | print the most discussed stocks |
| `report [--days 30] [-o report.html]` | write the HTML dashboard |
| `run` | fetch + analyze + top + report |
| `demo [--videos 300]` | synthetic data to try the dashboard |

Global options: `--db FILE`, `--api-key KEY`, `--tickers extra.csv`.

## How it works

1. **Detection** (`psx_yt/analyzer.py`, `psx_yt/tickers.py`): ~90 PSX stocks (KSE-100 heavyweights and popular names)
   with their symbol, company name and common aliases in English, Roman Urdu and Urdu script
   (`OGDC`, `ogdcl`, `Hub Power`, `hubco`, `حب پاور`, ...). Longest match wins, so "Engro Fertilizer" counts as
   EFERT rather than ENGROH. Symbols that are ordinary words (`POWER`, `LUCK`, `PPL`, `UNITY`, `MARI`...) only count
   when tagged (`$LUCK`, `#PPL`) or named in full ("Lucky Cement").
2. **Sentiment**: the sentence around each mention is scored with bullish/bearish cue words
   (*buy, breakout, target, tezi, khareedain, منافع* vs *sell, crash, avoid, girawat, mandi, نقصان*), with simple
   negation ("don't buy", "mat khareedo").
3. **Trends** (`psx_yt/trends.py`), over the look-back period:
   - **Buzz**: sum over videos of `(2 if in title else 1) × (1 + log10(1 + views))`
   - **Last 7d vs prev 7d** video counts give the trend label: `NEW`, `RISING` (≥1.5×), `STEADY`, `FALLING` (≤0.67×)
   - **Sentiment**: share of bullish / neutral / bearish videos, net score from −1 to +1
   - channel breadth, total views, daily series, latest videos per stock
4. **Dashboard** (`report.html`): leaderboard tiles, daily trend chart for the top 5, buzz by sector,
   and a sortable/filterable table; click a stock to see the videos behind it.

### Adding stocks

Copy `tickers_extra.example.csv` to `tickers_extra.csv` and add rows (aliases separated by `;`).
Rows override built-in stocks with the same symbol. Then run `python -m psx_yt analyze`.

## Tests

```bash
python -m unittest -v
```

## Limits

- Sentiment is keyword based and sentence level: a title like "Buy OGDC, sell PSO" gives both the same tone.
- Without transcripts only titles and descriptions are read, so stocks discussed only verbally are missed.
- Not investment advice.
