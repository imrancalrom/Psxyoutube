import argparse
import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from psx_yt import cli, db, digest, notify, prices, track, youtube
from psx_yt.analyzer import (Analyzer, analyze_video, analyze_video_sectors, boilerplate_lines, strip_lines,
                             strip_payment_details, strip_video_titles, title_key)
from psx_yt.tickers import load_tickers
from psx_yt.trends import call_label, compute, summary, tone_label, trend_label
from psx_yt.youtube import parse_rss, resolve_channel

ANALYZER = Analyzer(load_tickers())
INSERT_MENTION = ("INSERT INTO mentions (video_id, symbol, in_title, in_description, in_transcript, sentiment, holds, "
                  "calls) VALUES (?,?,?,?,?,?,?,?)")


def symbols(text):
    return [m.symbol for m in ANALYZER.find_mentions(text)]


class DetectionTests(unittest.TestCase):
    def test_symbols_and_names(self):
        self.assertEqual(symbols("OGDC and hubc look strong, also Lucky Cement"), ["OGDC", "HUBC", "LUCK"])

    def test_longest_alias_wins(self):
        self.assertEqual(symbols("Engro Fertilizer results"), ["EFERT"])
        self.assertEqual(symbols("Engro Holdings results"), ["ENGROH"])

    def test_ambiguous_symbols_need_tag(self):
        self.assertEqual(symbols("Power sector and good luck to all ppl"), [])
        self.assertEqual(symbols("$POWER and #LUCK and $PPL"), ["POWER", "LUCK", "PPL"])

    def test_no_partial_words(self):
        self.assertEqual(symbols("SYSTEMATIC approach, HUBCO"), ["HUBC"])

    def test_similar_names(self):
        self.assertEqual(symbols("Atlas Honda and Honda Atlas"), ["ATLH", "HCAR"])
        self.assertEqual(symbols("Nishat Power vs Nishat Chunian Power"), ["NPL", "NCPL"])
        self.assertEqual(symbols("TPL Properties and TPL Corp"), ["TPLP", "TPL"])
        self.assertEqual(symbols("FCCL, NATF & BOP earnings; MACPAC Films Limited (MACFL) rally"),
                         ["FCCL", "NATF", "BOP", "MACFL", "MACFL"])

    def test_roman_urdu_and_urdu(self):
        self.assertEqual(symbols("میزان بینک اور حب پاور"), ["MEBL", "HUBC"])


class SentimentTests(unittest.TestCase):
    def tone(self, text):
        return [(m.symbol, m.sentiment) for m in ANALYZER.find_mentions(text)]

    def test_bullish_bearish_per_sentence(self):
        self.assertEqual(self.tone("Buy OGDC for target 300. Avoid KEL, bearish chart."),
                         [("OGDC", 1), ("KEL", -1)])

    def test_roman_urdu(self):
        self.assertEqual(self.tone("HUBC mein tezi, abhi khareedain"), [("HUBC", 1)])
        self.assertEqual(self.tone("34:57 Top Picks - (NATF)"), [("NATF", 1)])
        self.assertEqual(self.tone("PSO mein girawat"), [("PSO", -1)])

    def test_negation(self):
        self.assertEqual(self.tone("Don't buy TRG now"), [("TRG", -1)])

    def test_clauses_within_sentence(self):
        self.assertEqual(self.tone("Buy OGDC, sell PSO"), [("OGDC", 1), ("PSO", -1)])
        self.assertEqual(self.tone("HUBC mein tezi lekin KEL mein girawat"), [("HUBC", 1), ("KEL", -1)])
        self.assertEqual(self.tone("Bullish on OGDC vs bearish on PSO"), [("OGDC", 1), ("PSO", -1)])

    def test_neutral_clause_uses_sentence(self):
        self.assertEqual(self.tone("OGDC, HUBC and PSO: buy all three"), [("OGDC", 1), ("HUBC", 1), ("PSO", 1)])
        self.assertEqual(self.tone("Weekly review | OGDC, HUBC discussed"), [("OGDC", 0), ("HUBC", 0)])

    def calls(self, text):
        return [(m.symbol, m.call, m.hold) for m in ANALYZER.find_mentions(text)]

    def test_hold_calls(self):
        self.assertEqual(self.calls("Hold OGDC for now"), [("OGDC", 0, 1)])
        self.assertEqual(self.calls("FFC ko hold rakhein"), [("FFC", 0, 1)])
        self.assertEqual(self.calls("OGDC: buy and hold"), [("OGDC", 1, 0)])  # buy wins
        self.assertEqual(self.calls("Don't hold PSO"), [("PSO", -1, 0)])

    def test_names_and_phrases_are_not_hold_calls(self):
        self.assertEqual(self.calls("Engro Holdings results"), [("ENGROH", 0, 0)])
        self.assertEqual(self.calls("Holding company TPL Corp update"), [("TPL", 0, 0)])
        self.assertEqual(self.calls("UNITY FOODS BUY SELL OR HOLD, detailed analysis"), [("UNITY", 0, 0)])
        self.assertEqual(self.calls("Should you buy or sell OGDC?"), [("OGDC", 0, 0)])
        self.assertEqual(self.calls("Lucky Cement sales hold steady"), [("LUCK", 0, 0)])
        self.assertEqual(self.calls("Property holding vs REITs: TPL Properties"), [("TPLP", 0, 0)])

    def test_calls_are_explicit_recommendations(self):
        tone_call = lambda t: [(m.symbol, m.sentiment, m.call) for m in ANALYZER.find_mentions(t)]
        self.assertEqual(tone_call("Buy OGDC, sell PSO"), [("OGDC", 1, 1), ("PSO", -1, -1)])
        self.assertEqual(tone_call("PIBTL price target 23"), [("PIBTL", 0, 1)])
        self.assertEqual(tone_call("Sazgar Looks Undervalued"), [("SAZEW", 1, 0)])          # upbeat, not a call
        self.assertEqual(tone_call("Foreign Buying & SAZEW Analysis"), [("SAZEW", 1, 0)])          # a money flow
        self.assertEqual(tone_call("Selling pressure on MEBL"), [("MEBL", -1, 0)])
        self.assertEqual(tone_call("We break down the factors behind SAZEW"), [("SAZEW", 0, 0)])  # "explain"
        self.assertEqual(tone_call("OGDC breaks below support"), [("OGDC", -1, 0)])
        self.assertEqual(tone_call("Importance of STOP LOSS, explained with PSO"), [("PSO", 0, 0)])
        self.assertEqual(tone_call("ENGROH dividend policy and payout"), [("ENGROH", 0, 0)])
        self.assertEqual(tone_call("KEL & FFC | BUY & SELL & HOLD"), [("KEL", 0, 0), ("FFC", 0, 0)])  # the options
        self.assertEqual(tone_call("FFC BUY & HOLD"), [("FFC", 1, 1)])
        self.assertEqual(tone_call("A tax on buying and selling, and a view of KAPCO"), [("KAPCO", 0, 0)])
        self.assertEqual(tone_call("How to buy MEBL shares"), [("MEBL", 1, 0)])
        self.assertEqual(tone_call("Retail traders are buying NBP"), [("NBP", 1, 0)])
        self.assertEqual(tone_call("Fauji Foods has accumulated losses"), [("FFL", 0, 0)])
        self.assertEqual(tone_call("ENGROH ENTRY OR EXIT"), [("ENGROH", 0, 0)])
        self.assertEqual(tone_call("How to find multibagger stocks like HUBC"), [("HUBC", 1, 0)])
        self.assertEqual(tone_call("SAZEW MULTIBAGGER"), [("SAZEW", 1, 1)])
        self.assertEqual(tone_call("They sell raw milk to Nestle"), [("NESTLE", -1, 0)])
        self.assertEqual(tone_call("Accumulate FFL on dips"), [("FFL", 1, 1)])
        self.assertEqual(tone_call("Is OGDC still undervalued? Buy OGDC"), [("OGDC", 0, 0), ("OGDC", 1, 1)])  # questions

    def test_analyze_video_sources(self):
        out = analyze_video(ANALYZER, "OGDC breakout", "OGDC and PPL details", None)
        self.assertEqual(out["OGDC"], {"title": 1, "description": 1, "transcript": 0, "sentiment": 1, "holds": 0, "calls": 0})  # upbeat, no call
        self.assertNotIn("PPL", out)  # untagged PPL is ambiguous


class SectorTests(unittest.TestCase):
    def sectors(self, text):
        return {k: v["sentiment"] for k, v in analyze_video_sectors(ANALYZER, text, "", None).items()}

    def test_named_sectors(self):
        self.assertEqual(self.sectors("Selling from Banks | PSX Pulse"), {"Banks": -1})
        self.assertEqual(self.sectors("Refineries in Momentum"), {"Refinery": 1})
        self.assertEqual(self.sectors("E&P stocks rally, avoid OMCs"), {"Oil & Gas E&P": 1, "Oil & Gas Marketing": -1})
        self.assertEqual(self.sectors("سیمنٹ سیکٹر میں تیزی"), {"Cement": 1})
        self.assertEqual(self.sectors("How to invest in the Oil Exploration Sector"), {"Oil & Gas E&P": 0})

    def test_not_sectors(self):
        self.assertEqual(self.sectors("State Bank keeps policy rate, power to the people"), {})
        self.assertEqual(self.sectors("Lucky Cement results"), {})  # the stock, not the sector

    def test_general_words_are_not_sectors(self):
        self.assertEqual(self.sectors("Real estate trap vs Roshan Digital Account, digital banking"), {})
        self.assertEqual(self.sectors("REITs and the banking sector"), {"Real Estate": 0, "Banks": 0})

    def test_links_to_other_videos_dropped(self):
        titles = {title_key("Watch This Before Investing in Any Bank | Meezan Bank")}
        desc = ("Khaadi IPO explained\n🎥 WATCH OUR MOST USEFUL VIDEOS\n"
                "▶ Watch This Before Investing in Any Bank | Meezan Bank https://youtu.be/x\nOGDC is also discussed")
        self.assertEqual(symbols(strip_video_titles(desc, titles)), ["OGDC"])

    def test_payment_details_dropped(self):
        desc = ("OGDC results discussed\nBank Account Details:\nTitle of Account: Some Institute\nMCB\n"
                "ACCOUNT: 0000\nIBAN: PK00MUCB0000\nBOP\nAccount No: 0000\nAccount opening in PSX via Roshan Digital Account")
        kept = strip_payment_details(desc)
        self.assertEqual(symbols(kept), ["OGDC"])
        self.assertIn("Account opening in PSX via Roshan Digital Account", kept)

    def test_boilerplate_lines(self):
        shared = "Join our WhatsApp group\n#psx #banking #trading"
        descs = [shared, shared + "\nOGDC results today", shared, "Something else"]
        lines = boilerplate_lines(descs)
        self.assertEqual(lines, {"Join our WhatsApp group", "#psx #banking #trading"})
        self.assertEqual(strip_lines(descs[1], lines), "OGDC results today")
        self.assertEqual(boilerplate_lines(descs[:2]), set())  # too few videos to tell


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <title>Some PSX Channel</title>
 <entry>
  <yt:videoId>abc123def45</yt:videoId>
  <yt:channelId>UCabcdefghijklmnopqrstuv</yt:channelId>
  <title>LUCK cement analysis</title>
  <published>2026-10-20T10:00:00+00:00</published>
  <media:group>
   <media:description>Lucky Cement results</media:description>
   <media:community><media:statistics views="1234"/></media:community>
  </media:group>
 </entry>
</feed>"""


class YouTubeTests(unittest.TestCase):
    def test_parse_rss(self):
        title, videos = parse_rss(RSS)
        self.assertEqual(title, "Some PSX Channel")
        self.assertEqual(videos[0]["id"], "abc123def45")
        self.assertEqual(videos[0]["views"], 1234)
        self.assertEqual(videos[0]["description"], "Lucky Cement results")

    def test_resolve_channel_id_offline(self):
        cid = "UCabcdefghijklmnopqrstuv"
        self.assertEqual(resolve_channel(cid), (cid, None))
        self.assertEqual(resolve_channel(f"https://www.youtube.com/channel/{cid}"), (cid, None))

    def test_resolve_legacy_urls_scrape_page(self):
        page = mock.Mock(text='<meta property="og:title" content="Pakistan Stock Exchange &amp; Co">'
                              '"externalId":"UCabcdefghijklmnopqrstuv"')
        with mock.patch.object(youtube, "_get", return_value=page) as get:
            for ref, url in (("https://m.youtube.com/c/PakistanStockExchangeLimited/videos",
                              "https://www.youtube.com/c/PakistanStockExchangeLimited"),
                             ("youtube.com/user/SomeName", "https://www.youtube.com/user/SomeName")):
                self.assertEqual(resolve_channel(ref), ("UCabcdefghijklmnopqrstuv", "Pakistan Stock Exchange & Co"))
                get.assert_called_with(url)


class FetchFallbackTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        for cid in ("UC1", "UC2", "UC3"):
            db.upsert_channel(self.conn, cid, cid)
        self.args = argparse.Namespace(api_key="KEY", max=200, transcripts=False, retry_captions=False)

    def rss(self, cid):
        return cid, [{"id": f"{cid}-rss", "title": "OGDC", "published_at": "2026-10-28T10:00:00Z"}]

    def fetch(self, api):
        with mock.patch.object(youtube, "fetch_api", api), \
                mock.patch.object(youtube, "fetch_rss", side_effect=self.rss) as rss, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli.cmd_fetch(self.args, self.conn)
        return rss, out.getvalue()

    def test_rejected_key_switches_whole_run_to_rss(self):
        api = mock.Mock(side_effect=youtube.YouTubeError("HTTP 403: blocked", 403))
        rss, out = self.fetch(api)
        self.assertEqual(api.call_count, 1)  # not retried for every channel
        self.assertEqual(rss.call_count, 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 3)
        self.assertIn("rejected the key", out)

    def test_one_failing_channel_keeps_api_for_the_rest(self):
        ok = ("T", [{"id": "api", "title": "HUBC", "published_at": "2026-10-28T10:00:00Z"}])
        api = mock.Mock(side_effect=[youtube.YouTubeError("Channel UC1 not found"), ok, ok])
        rss, _ = self.fetch(api)
        self.assertEqual((api.call_count, rss.call_count), (3, 1))

    def test_error_message_leaves_out_the_key(self):
        response = mock.Mock(status_code=403, url="https://x/channels?id=UC1&key=SECRET")
        response.json.return_value = {"error": {"message": "Requests to this API are blocked."}}
        with mock.patch.object(youtube.requests, "get", return_value=response):
            with self.assertRaises(youtube.YouTubeError) as caught:
                youtube._get("https://x/channels", id="UC1", key="SECRET")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertIn("HTTP 403: Requests to this API are blocked.", str(caught.exception))
        self.assertEqual(caught.exception.status, 403)

    def test_channel_lookup_falls_back_to_page(self):
        with mock.patch.object(youtube, "_get", side_effect=youtube.YouTubeError("HTTP 403", 403)), \
                mock.patch.object(youtube, "_scrape_channel_page", return_value=("UCx", "Name")) as page:
            self.assertEqual(resolve_channel("@somehandle", "KEY"), ("UCx", "Name"))
        page.assert_called_once_with("https://www.youtube.com/@somehandle")


class ReportTests(unittest.TestCase):
    def test_dashboard_embeds_every_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbf, out = os.path.join(tmp, "t.db"), os.path.join(tmp, "r.html")
            conn = db.connect(dbf)
            db.upsert_channel(conn, "UC1", "Chan 1")
            for vid, age in (("new", 1), ("old", 40)):
                day = (date.today() - timedelta(days=age)).isoformat()
                db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": "Buy OGDC", "published_at": day + "T10:00:00Z"})
            conn.commit()
            conn.close()
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--db", dbf, "analyze"])
                cli.main(["--db", dbf, "report", "-o", out])
            html = open(out, encoding="utf-8").read()
        data, _ = json.JSONDecoder().raw_decode(html.split("const ALL = ", 1)[1])
        self.assertEqual(sorted(map(int, data["periods"])), [7, 15, 21, 28, 90])
        self.assertEqual(data["default"], 90)
        videos = {d: data["periods"][d]["stocks"][0]["videos"] for d in ("7", "90")}
        self.assertEqual(videos, {"7": 1, "90": 2})  # the 40-day-old video only shows in the 90-day view
        self.assertEqual(sorted(data["videos"]), ["new", "old"])  # each video stored once
        self.assertEqual([ref[0] for ref in data["periods"]["90"]["stocks"][0]["v"]], ["new", "old"])
        # What the channel filter rebuilds figures from: [id, call, tone, in title, sector named outright]
        self.assertEqual(data["periods"]["90"]["stocks"][0]["v"][0], ["new", "buy", 1, 1, 0])
        self.assertEqual(data["periods"]["7"]["channel_videos"], {"Chan 1": 1})
        self.assertEqual(data["periods"]["90"]["channel_videos"], {"Chan 1": 2})


class PriceTests(unittest.TestCase):
    def test_parse_eod(self):
        rows = prices.parse_eod({"status": 1, "data": [[1761868800, 310.5, 1200, 309], [1761782400000, 308.0, 900]]})
        self.assertEqual(rows, [("2025-10-30", 308.0, 900), ("2025-10-31", 310.5, 1200)])  # ms or s, oldest first
        for bad in ({"error": "x"}, {"data": [["2025-10-31", 1]]}, {"data": [[1761868800, -5]]}, []):
            with self.assertRaises(prices.PriceError):
                prices.parse_eod(bad)

    def yahoo(self, symbol="OGDC", exchange="KAR", currency="PKR", n=40):
        ts = [1761868800 - 86400 * i for i in range(n)][::-1]
        return {"chart": {"error": None, "result": [{
            "meta": {"symbol": f"{symbol}.KA", "exchangeName": exchange, "currency": currency, "regularMarketPrice": 131.87},
            "timestamp": ts + [ts[-1] + 86400],
            "indicators": {"quote": [{"close": [300.0 + i for i in range(n)] + [None], "volume": [1000] * n + [None]}]}}]}}

    def test_parse_yahoo(self):
        rows = prices.parse_yahoo("OGDC", self.yahoo())
        self.assertEqual(len(rows), 40)                       # the day with no close is dropped
        self.assertEqual(rows[-1], ("2025-10-31", 339.0, 1000))  # closes, never regularMarketPrice
        for bad in (self.yahoo(exchange="NMS"), self.yahoo(currency="USD"), self.yahoo(n=10),
                    {"chart": {"error": {"code": "Not Found"}, "result": None}}):
            with self.assertRaises(prices.PriceError):
                prices.parse_yahoo("OGDC", bad)
        with self.assertRaises(prices.PriceError):  # asked for ATRL, got OGDC
            prices.parse_yahoo("ATRL", self.yahoo())

    def test_price_step_as_called_by_run(self):
        # `run` passes its own arguments (no --probe); one stock's download fails, the other is stored.
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        today = date.today().isoformat()
        db.upsert_video(conn, {"id": "v", "channel_id": "UC1", "title": "OGDC and HUBC", "published_at": today + "T10:00:00Z"})
        conn.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_analyze(argparse.Namespace(tickers=None), conn)
        series = prices.parse_yahoo("OGDC", self.yahoo())
        fetch = mock.Mock(side_effect=lambda sym: series if sym == "OGDC" else (_ for _ in ()).throw(prices.PriceError("HTTP 404")))
        run_args = argparse.Namespace(days=90, transcripts=False, retry_captions=False, max=200, api_key=None, no_prices=False)
        with mock.patch.object(prices, "fetch_yahoo", fetch), mock.patch.object(cli.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli.cmd_prices(run_args, conn)
        self.assertIn("Prices: 1 of 2 stocks", out.getvalue())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM prices WHERE symbol = 'OGDC'").fetchone()[0], 40)

    def test_signals(self):
        base = {"close": 100.0, "rsi14": 50.0, "cross": None, "high52": 120.0, "low52": 80.0,
                "support": [{"price": 99.0, "touches": 3}], "resistance": [{"price": 110.0, "touches": 2}]}
        kinds = lambda t: [s["kind"] for s in prices.signals(t)]
        self.assertEqual(kinds(base), ["near_support"])
        self.assertEqual(kinds({**base, "support": [{"price": 99.0, "touches": 1}]}), [])           # weak level
        self.assertEqual(kinds({**base, "resistance": [{"price": 101.0, "touches": 2}]}), ["range"])  # near both
        self.assertEqual(kinds({**base, "support": [], "rsi14": 25.0, "low52": 100.0}), ["oversold", "low52"])
        self.assertEqual(kinds({**base, "support": [], "cross": {"kind": "golden", "date": "2026-10-28"}}), ["golden_cross"])
        self.assertEqual(prices.signals(base)[0]["detail"], "99 support (3×), 1.0% above")

    def test_clean_series(self):
        day = lambda i: f"2026-01-{i + 1:02d}"
        rows = lambda closes: [(day(i), c, None) for i, c in enumerate(closes)]
        # A 3-day glitch on another scale (as WTL 1.26 -> 0.12) is dropped.
        clean, note = prices.clean_series(rows([100, 101, 10.1, 10.2, 10.0, 102, 103]))
        self.assertEqual([c for _, c, _ in clean], [100, 101, 102, 103])
        self.assertEqual(note, "3 glitch days dropped")
        # A lasting change of scale (an unadjusted 5:1 split, as LUCK) keeps only what comes after it.
        clean, note = prices.clean_series(rows([1400, 1410, 1420, 284, 286, 290, 288]))
        self.assertEqual([c for _, c, _ in clean], [284, 286, 290, 288])
        self.assertEqual(note, "3 days before a change of scale dropped")
        # Normal moves, and a Rs 1 move on a cheap stock (allowed by PSX), are kept.
        ok = rows([10, 10.9, 10.2, 2.0, 2.9, 2.1])[3:]
        self.assertEqual(prices.clean_series(rows([100, 109, 99, 104]))[0], rows([100, 109, 99, 104]))
        self.assertEqual(prices.clean_series(ok)[0], ok)

    def test_moving_averages_and_rsi(self):
        self.assertEqual(prices.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])
        rising = [float(v) for v in range(1, 40)]
        self.assertEqual(prices.rsi(rising)[-1], 100.0)
        zigzag = [100.0 + (1 if i % 2 else -1) for i in range(40)]
        self.assertTrue(45 <= prices.rsi(zigzag)[-1] <= 55)
        line, sig, hist = prices.macd(rising)
        self.assertGreater(line[-1], 0)
        self.assertAlmostEqual(hist[-1], round(line[-1] - sig[-1], 2), places=1)

    def test_levels_cluster_swing_points(self):
        # Price bounces between 100 and 120: one support and one resistance level. A swing point needs `window` days
        # either side to be confirmed, so the first low (day 0) and the last one (2 days from the end) don't count.
        wave = [100, 104, 108, 112, 116, 120, 116, 112, 108, 104] * 3 + [100, 104, 108]
        lv = prices.levels([float(v) for v in wave], window=3)
        self.assertEqual([(l["price"], l["touches"]) for l in lv], [(100.0, 2), (120.0, 3)])

    def test_technicals(self):
        days = [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", float(v), None)
                for i, v in enumerate(([100, 104, 108, 112, 116, 120, 116, 112, 108, 104] * 8)[:75])]
        t = prices.technicals(days)
        self.assertEqual(t["close"], days[-1][1])
        self.assertEqual([l["price"] for l in t["support"]], [100.0])
        self.assertEqual([l["price"] for l in t["resistance"]], [120.0])
        self.assertIn("support 100 (", t["summary"])
        self.assertIsNone(prices.technicals(days[:20]))  # too little history


class DigestTests(unittest.TestCase):
    def test_digest(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        db.upsert_channel(conn, "UC2", "Chan 2")
        now = datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc)
        vids = [("a", "UC1", now - timedelta(hours=2), "Buy OGDC now"),           # last 24h, buy call
                ("b", "UC2", now - timedelta(days=2), "Buy OGDC, target 300"),   # this week
                ("c", "UC1", now - timedelta(days=3), "HUBC update"),            # this week
                ("d", "UC2", now - timedelta(days=4), "HUBC results"),
                ("e", "UC1", now - timedelta(days=9), "Sell PSO"),               # last week only
                ("f", "UC1", now - timedelta(days=10), "PSO crash"),
                ("g", "UC2", now - timedelta(days=40), "HUBC history")]          # older: HUBC isn't new
        for vid, ch, ts, title in vids:
            db.upsert_video(conn, {"id": vid, "channel_id": ch, "title": title, "published_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ")})
        conn.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_analyze(argparse.Namespace(tickers=None), conn)
        d = digest.build(conn, load_tickers(), now=now)
        items = {s["title"]: s["items"] for s in d["sections"]}
        self.assertEqual(items["Last 24 hours"], ["1 new video from 1 channel", "Stocks mentioned: OGDC", "Calls: OGDC buy (Chan 1)"])
        week = items["This week vs last week"]
        self.assertIn("Newly discussed (none in the 83 days before): OGDC (2)", week)  # HUBC was discussed 40 days ago
        self.assertIn("Buzz fading: PSO 2→0", week)
        self.assertIn("Buy calls this week: OGDC ×2 (2 channels)", week)
        self.assertIn("**Last 24 hours**", digest.markdown(d))


class TrackTests(unittest.TestCase):
    def test_track_record(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        start = date(2026, 1, 1)
        days = [(start + timedelta(days=i)).isoformat() for i in range(40)]
        # OGDC rises 1 a day from 100; PSO falls 1 a day from 200: the "market" is their average.
        conn.executemany("INSERT INTO prices VALUES (?,?,?,?)",
                         [("OGDC", d, 100.0 + i, None) for i, d in enumerate(days)] +
                         [("PSO", d, 200.0 - i, None) for i, d in enumerate(days)])
        for vid, title, day in (("a", "Buy OGDC", days[0]), ("b", "Sell PSO", days[0]), ("c", "Buy PSO", days[30]),
                                ("d", "Hold OGDC", days[5]), ("e", "Buy HUBC", days[5])):
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": title, "published_at": day + "T18:00:00Z"})
        conn.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_analyze(argparse.Namespace(tickers=None), conn)
        t = track.build(conn)
        calls = {c["video_id"]: c for c in t["calls"]}
        ogdc = calls["a"]
        self.assertEqual((ogdc["entry_date"], ogdc["entry"]), (days[1], 101.0))  # the day after the video
        self.assertEqual((ogdc["move5"], ogdc["right5"]), (round(100 * (106 / 101 - 1), 2), True))
        self.assertTrue(calls["b"]["right20"])            # a sell call is right when the price falls
        self.assertIsNone(calls["c"]["move20"])           # too recent for a 20-day result
        self.assertFalse(calls["c"]["right5"])            # bought PSO, which kept falling
        everyone = t["channels"][0]
        self.assertEqual((everyone["channel"], everyone["calls"], everyone["n20"], everyone["pending20"]), ("All channels", 3, 2, 1))
        self.assertEqual(everyone["hit20"], 100)
        # Market over OGDC's 20 days = mean of +19.8% and -10.4%; the buy beat it.
        self.assertGreater(ogdc["move20"], ogdc["market20"])
        # The call log also lists hold calls and calls on stocks without prices; neither is scored.
        self.assertEqual(ogdc["now"], round(100 * (139 / 101 - 1), 2))  # entry to the latest close
        self.assertEqual((calls["d"]["call"], calls["d"]["right5"]), ("hold", None))
        self.assertIsNotNone(calls["d"]["move5"])
        self.assertEqual((calls["e"]["call"], calls["e"]["entry"], calls["e"]["now"]), ("buy", None, None))
        self.assertEqual(len(t["calls"]), 5)


class NotifyTests(unittest.TestCase):
    D = {"title": "PSX YouTube digest, 02 Nov 2026", "headline": "5 videos", "date": "2026-11-02",
         "sections": [{"title": "Sectors", "items": ["Oil & Gas E&P: buzz rising 2→3", "<b>x</b>"]}]}

    def test_message_escapes_html(self):
        m = notify.message(self.D, link="https://github.com/o/r/actions/runs/1?a=1&b=2")
        self.assertIn("<b>Sectors</b>\n• Oil &amp; Gas E&amp;P: buzz rising 2→3\n• &lt;b&gt;x&lt;/b&gt;", m)
        self.assertIn('href="https://github.com/o/r/actions/runs/1?a=1&amp;b=2"', m)
        self.assertIn("Not investment advice", m)
        m = notify.message(self.D, link="https://o.github.io/r/", link_text="Open the dashboard")
        self.assertIn('<a href="https://o.github.io/r/">Open the dashboard</a>', m)

    def test_split(self):
        self.assertEqual(notify.split("a\nb\nc", limit=3), ["a\nb", "c"])
        self.assertEqual(notify.split("abcdefg", limit=3), ["abc", "def", "g"])
        parts = notify.split("\n".join(["x" * 50] * 200), limit=4096)
        self.assertTrue(all(len(p) <= 4096 for p in parts))
        self.assertEqual("\n".join(parts), "\n".join(["x" * 50] * 200))

    def test_send_to_each_chat(self):
        ok = mock.Mock(status_code=200, json=lambda: {"ok": True, "result": {}})
        with mock.patch.object(notify.requests, "post", return_value=ok) as post:
            self.assertEqual(notify.send("TOKEN", "1, -100200", "hello"), 2)
        self.assertEqual([c.kwargs["json"]["chat_id"] for c in post.call_args_list], ["1", "-100200"])
        self.assertEqual(post.call_args.args[0], "https://api.telegram.org/botTOKEN/sendMessage")
        self.assertEqual(post.call_args.kwargs["json"]["parse_mode"], "HTML")

    def test_errors_never_show_the_token(self):
        bad = mock.Mock(status_code=401, json=lambda: {"ok": False, "description": "Unauthorized"})
        with mock.patch.object(notify.requests, "post", return_value=bad):
            with self.assertRaises(notify.TelegramError) as e:
                notify.send("SECRET123", "1", "hi")
        self.assertIn("TELEGRAM_BOT_TOKEN", str(e.exception))
        self.assertNotIn("SECRET123", str(e.exception))
        down = notify.requests.ConnectionError("https://api.telegram.org/botSECRET123/sendMessage failed")
        with mock.patch.object(notify.requests, "post", side_effect=down):
            with self.assertRaises(notify.TelegramError) as e:
                notify.send("SECRET123", "1", "hi")
        self.assertNotIn("SECRET123", str(e.exception))

    def test_find_chats(self):
        updates = {"ok": True, "result": [
            {"message": {"chat": {"id": 42, "type": "private", "first_name": "Imran"}}},
            {"message": {"chat": {"id": 42, "type": "private", "first_name": "Imran"}}},
            {"my_chat_member": {"chat": {"id": -1001, "type": "channel", "title": "PSX alerts"}}}]}
        with mock.patch.object(notify.requests, "post", return_value=mock.Mock(status_code=200, json=lambda: updates)):
            self.assertEqual(notify.find_chats("T"), [{"id": 42, "type": "private", "name": "Imran"},
                                                      {"id": -1001, "type": "channel", "name": "PSX alerts"}])

    def test_notify_without_secrets_prints_preview(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}), \
                mock.patch.object(notify.requests, "post") as post, contextlib.redirect_stdout(out):
            cli.main(["--db", ":memory:", "notify"])
        post.assert_not_called()
        self.assertIn("this is what would be sent", out.getvalue())


class CaptionTests(unittest.TestCase):
    def test_transcript_status(self):
        def err(*names):  # an exception whose class hierarchy has these names
            cls = Exception
            for n in reversed(names):
                cls = type(n, (cls,), {})
            return cls()
        self.assertEqual(youtube.transcript_status(err("TranscriptsDisabled", "CouldNotRetrieveTranscript")), "none")
        self.assertEqual(youtube.transcript_status(err("IpBlocked", "RequestBlocked")), "blocked")
        self.assertEqual(youtube.transcript_status(ConnectionError()), "error")

    def test_fetch_transcripts_keeps_blocked_and_new_videos_for_retry(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        new = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        for vid, ts in (("ok", "2026-01-01T00:00:00Z"), ("none", "2026-01-01T00:00:00Z"),
                        ("none_new", new), ("blocked", "2026-01-01T00:00:00Z"), ("old_empty", "2026-01-01T00:00:00Z")):
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": vid, "published_at": ts})
        conn.execute("UPDATE videos SET transcript = '' WHERE id = 'old_empty'")
        results = {"ok": ("OGDC buy", "ok", ""), "none": (None, "none", "NoTranscriptFound"),
                   "none_new": (None, "none", "NoTranscriptFound"), "blocked": (None, "blocked", "IpBlocked"),
                   "old_empty": ("HUBC", "ok", "")}
        with mock.patch.object(youtube, "fetch_transcript", side_effect=lambda vid: results[vid]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli.fetch_transcripts(conn)
        stored = dict(conn.execute("SELECT id, transcript FROM videos").fetchall())
        self.assertEqual(stored, {"ok": "OGDC buy", "none": "", "none_new": None, "blocked": None, "old_empty": ""})
        self.assertIn("Captions: 1 ok, 2 none, 1 blocked, 0 error", out.getvalue())
        self.assertIn("blocked: blocked (IpBlocked)", out.getvalue())
        with mock.patch.object(youtube, "fetch_transcript", side_effect=lambda vid: results[vid]), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.fetch_transcripts(conn, retry=True)
        self.assertEqual(conn.execute("SELECT transcript FROM videos WHERE id = 'old_empty'").fetchone()[0], "HUBC")

    def test_fetch_transcripts_limit_takes_newest_first(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        for i in range(5):
            db.upsert_video(conn, {"id": f"v{i}", "channel_id": "UC1", "title": "t", "published_at": f"2026-01-0{i + 1}T00:00:00Z"})
        calls = mock.Mock(return_value=("text", "ok", ""))
        with mock.patch.object(youtube, "fetch_transcript", calls), contextlib.redirect_stdout(io.StringIO()) as out:
            cli.fetch_transcripts(conn, limit=2)
        self.assertEqual([c.args[0] for c in calls.call_args_list], ["v4", "v3"])
        self.assertIn("Fetching captions for 2 of 5 videos waiting", out.getvalue())

    def test_fetch_transcripts_stops_when_blocked(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        for i in range(10):
            db.upsert_video(conn, {"id": f"v{i}", "channel_id": "UC1", "title": "t", "published_at": "2026-01-01T00:00:00Z"})
        calls = mock.Mock(return_value=(None, "blocked", "IpBlocked"))
        with mock.patch.object(youtube, "fetch_transcript", calls), contextlib.redirect_stdout(io.StringIO()):
            counts = cli.fetch_transcripts(conn)
        self.assertEqual(calls.call_count, cli.MAX_FAILURES_IN_A_ROW)
        self.assertTrue(counts["stopped"])
        self.assertEqual(counts["blocked"], cli.MAX_FAILURES_IN_A_ROW)

    def test_caption_stats(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        for i in range(4):
            db.upsert_video(conn, {"id": f"v{i}", "channel_id": "UC1", "title": "t", "published_at": "2026-01-01T00:00:00Z"})
        conn.execute("UPDATE videos SET transcript = 'words' WHERE id = 'v0'")
        conn.execute("UPDATE videos SET transcript = '' WHERE id = 'v1'")
        self.assertEqual(db.caption_stats(conn), {"total": 4, "read": 1, "none": 1, "waiting": 2})
        self.assertEqual(db.caption_stats(db.connect(":memory:")), {"total": 0, "read": 0, "none": 0, "waiting": 0})


class TrendTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(trend_label(6, 2), "RISING")
        self.assertEqual(trend_label(1, 4), "FALLING")
        self.assertEqual(trend_label(3, 0), "NEW")
        self.assertEqual(trend_label(3, 3), "STEADY")

    def test_call_labels(self):
        self.assertEqual(call_label(4, 1, 1), "BUY")
        self.assertEqual(call_label(0, 3, 1), "HOLD")
        self.assertEqual(call_label(1, 0, 2), "SELL")
        self.assertEqual(call_label(2, 0, 2), "MIXED")  # tie
        self.assertEqual(call_label(2, 2, 2), "MIXED")  # nobody has half
        self.assertEqual(call_label(1, 0, 1), "-")      # too few calls

    def test_summary(self):
        base = {"videos": 13, "channel_count": 6, "recent": 3, "previous": 0, "trend": "NEW", "buy_calls": 2, "hold": 0,
                "sell_calls": 2, "call": "MIXED", "tone_trend": "-"}
        self.assertEqual(summary(base), "13 videos on 6 channels · 3 this week, none the week before · calls split: 2 buy, 2 sell")
        self.assertEqual(summary({**base, "videos": 1, "channel_count": 1, "recent": 1, "buy_calls": 0, "sell_calls": 0,
                                  "call": "-"}),
                         "1 video on 1 channel only · new this week (1) · no buy/sell calls yet")
        self.assertEqual(summary({**base, "trend": "RISING", "previous": 1, "buy_calls": 4, "sell_calls": 1, "call": "BUY",
                                  "tone_trend": "IMPROVING"}),
                         "13 videos on 6 channels · buzz rising (1→3 a week) · channels lean BUY (4 buy, 1 sell) · tone improving")

    def test_tone_labels(self):
        self.assertEqual(tone_label(0.5, 0.0), "IMPROVING")
        self.assertEqual(tone_label(-0.5, 0.0), "WORSENING")
        self.assertEqual(tone_label(0.1, 0.0), "STABLE")
        self.assertEqual(tone_label(None, 0.5), "-")

    def test_compute(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        vids = [("v1", "2026-10-28T10:00:00Z", "Buy OGDC now", 1000),
                ("v2", "2026-10-27T10:00:00Z", "OGDC breakout", 100),
                ("v3", "2026-10-20T10:00:00Z", "OGDC sell", 10)]
        for vid, ts, title, views in vids:
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": title, "published_at": ts, "views": views})
            for sym, m in analyze_video(ANALYZER, title, "", None).items():
                conn.execute(INSERT_MENTION,
                             (vid, sym, m["title"], m["description"], m["transcript"], m["sentiment"], m["holds"], m["calls"]))
        data = compute(conn, load_tickers(), days=30, today=date(2026, 10, 29))
        ogdc = data["stocks"][0]
        self.assertEqual((ogdc["symbol"], ogdc["videos"], ogdc["recent"], ogdc["previous"]), ("OGDC", 3, 2, 1))
        self.assertEqual((ogdc["bullish"], ogdc["bearish"]), (2, 1))
        self.assertEqual(ogdc["trend"], "RISING")
        self.assertEqual(sum(ogdc["series"]), 3)
        self.assertEqual([v["id"] for v in ogdc["video_list"]], ["v1", "v2", "v3"])  # every video, newest first
        # Last 7d: 2 bullish videos -> +1.0; previous 7d has only 1 video, too few for a tone.
        data = compute(conn, load_tickers(), days=30, today=date(2026, 10, 29), min_tone_videos=2)
        ogdc = data["stocks"][0]
        self.assertEqual((ogdc["tone_recent"], ogdc["tone_previous"], ogdc["tone_change"], ogdc["tone_trend"]),
                         (1.0, None, None, "-"))

    def test_compute_tone_change(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        vids = [("v1", "2026-10-28", "Buy OGDC now"), ("v2", "2026-10-27", "OGDC weekly review"),
                ("v3", "2026-10-20", "Sell OGDC"), ("v4", "2026-10-19", "OGDC crash")]
        for vid, day, title in vids:
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": title, "published_at": day + "T10:00:00Z"})
            for sym, m in analyze_video(ANALYZER, title, "", None).items():
                conn.execute(INSERT_MENTION,
                             (vid, sym, m["title"], m["description"], m["transcript"], m["sentiment"], m["holds"], m["calls"]))
        ogdc = compute(conn, load_tickers(), days=30, today=date(2026, 10, 29), min_tone_videos=2)["stocks"][0]
        self.assertEqual((ogdc["tone_previous"], ogdc["tone_recent"], ogdc["tone_change"], ogdc["tone_trend"]),
                         (-1.0, 0.5, 1.5, "IMPROVING"))

    def test_compute_sectors(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        vids = [("v1", "Selling from Banks", ""), ("v2", "Buy MEBL now", ""), ("v3", "OGDC update", ""),
                ("v4", "Weekly", "Join us\n#banking"), ("v5", "Daily", "Join us\n#banking"),
                ("v6", "Recap", "Join us\n#banking")]
        for vid, title, desc in vids:
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": title, "description": desc,
                                   "published_at": "2026-10-28T10:00:00Z"})
        conn.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_analyze(argparse.Namespace(tickers=None), conn)
        sectors = {s["sector"]: s for s in compute(conn, load_tickers(), today=date(2026, 10, 29))["sectors"]}
        banks = sectors["Banks"]  # the shared "#banking" description line is ignored
        self.assertEqual((banks["videos"], banks["direct_videos"], banks["bullish"], banks["bearish"], banks["stocks"]),
                         (2, 1, 1, 1, ["MEBL"]))
        self.assertEqual((sectors["Oil & Gas E&P"]["videos"], sectors["Oil & Gas E&P"]["direct_videos"]), (1, 0))


class ExportTests(unittest.TestCase):
    def test_export_csv_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbf = os.path.join(tmp, "t.db")
            conn = db.connect(dbf)
            db.upsert_channel(conn, "UC1", "Chan 1")
            db.upsert_video(conn, {"id": "v1", "channel_id": "UC1", "title": "Buy OGDC, sell PSO",
                                   "published_at": date.today().isoformat() + "T10:00:00Z", "views": 50})
            conn.commit()
            conn.close()
            cli.main(["--db", dbf, "analyze"])
            cli.main(["--db", dbf, "export", "-o", os.path.join(tmp, "out.csv")])
            cli.main(["--db", dbf, "export", "-o", os.path.join(tmp, "out.json")])
            with open(os.path.join(tmp, "out.csv"), encoding="utf-8-sig") as f:
                rows = {r["symbol"]: r for r in csv.DictReader(f)}
            self.assertEqual((rows["OGDC"]["bullish"], rows["PSO"]["bearish"]), ("1", "1"))
            self.assertEqual(rows["OGDC"]["channels"], "Chan 1")
            self.assertEqual(rows["OGDC"]["tone_trend"], "-")
            cli.main(["--db", dbf, "export", "--sectors", "-o", os.path.join(tmp, "sectors.csv")])
            with open(os.path.join(tmp, "sectors.csv"), encoding="utf-8-sig") as f:
                secs = {r["sector"]: r for r in csv.DictReader(f)}
            self.assertEqual((secs["Oil & Gas E&P"]["stocks"], secs["Oil & Gas Marketing"]["bearish"]), ("OGDC", "1"))
            with open(os.path.join(tmp, "out.json"), encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)["stocks"]), 2)


if __name__ == "__main__":
    unittest.main()
