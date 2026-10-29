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

from psx_yt import cli, db, youtube
from psx_yt.analyzer import (Analyzer, analyze_video, analyze_video_sectors, boilerplate_lines, strip_lines,
                             strip_payment_details, strip_video_titles, title_key)
from psx_yt.tickers import load_tickers
from psx_yt.trends import call_label, compute, summary, tone_label, trend_label
from psx_yt.youtube import parse_rss, resolve_channel

ANALYZER = Analyzer(load_tickers())
INSERT_MENTION = ("INSERT INTO mentions (video_id, symbol, in_title, in_description, in_transcript, sentiment, holds) "
                  "VALUES (?,?,?,?,?,?,?)")


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
        return [(m.symbol, m.sentiment, m.hold) for m in ANALYZER.find_mentions(text)]

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

    def test_analyze_video_sources(self):
        out = analyze_video(ANALYZER, "OGDC breakout", "OGDC and PPL details", None)
        self.assertEqual(out["OGDC"], {"title": 1, "description": 1, "transcript": 0, "sentiment": 1, "holds": 0})
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

    def test_fetch_transcripts_stops_when_blocked(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        for i in range(10):
            db.upsert_video(conn, {"id": f"v{i}", "channel_id": "UC1", "title": "t", "published_at": "2026-01-01T00:00:00Z"})
        calls = mock.Mock(return_value=(None, "blocked", "IpBlocked"))
        with mock.patch.object(youtube, "fetch_transcript", calls), contextlib.redirect_stdout(io.StringIO()):
            cli.fetch_transcripts(conn)
        self.assertEqual(calls.call_count, cli.MAX_FAILURES_IN_A_ROW)


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
        base = {"videos": 13, "channel_count": 6, "recent": 3, "previous": 0, "trend": "NEW", "bullish": 2, "hold": 0,
                "bearish": 2, "call": "MIXED", "tone_trend": "-"}
        self.assertEqual(summary(base), "13 videos on 6 channels · 3 this week, none the week before · calls split: 2 buy, 2 sell")
        self.assertEqual(summary({**base, "videos": 1, "channel_count": 1, "recent": 1, "bullish": 0, "bearish": 0,
                                  "call": "-"}),
                         "1 video on 1 channel only · new this week (1) · no buy/sell calls yet")
        self.assertEqual(summary({**base, "trend": "RISING", "previous": 1, "bullish": 4, "bearish": 1, "call": "BUY",
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
                ("v2", "2026-10-27T10:00:00Z", "OGDC target", 100),
                ("v3", "2026-10-20T10:00:00Z", "OGDC sell", 10)]
        for vid, ts, title, views in vids:
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": title, "published_at": ts, "views": views})
            for sym, m in analyze_video(ANALYZER, title, "", None).items():
                conn.execute(INSERT_MENTION,
                             (vid, sym, m["title"], m["description"], m["transcript"], m["sentiment"], m["holds"]))
        data = compute(conn, load_tickers(), days=30, today=date(2026, 10, 29))
        ogdc = data["stocks"][0]
        self.assertEqual((ogdc["symbol"], ogdc["videos"], ogdc["recent"], ogdc["previous"]), ("OGDC", 3, 2, 1))
        self.assertEqual((ogdc["bullish"], ogdc["bearish"]), (2, 1))
        self.assertEqual(ogdc["trend"], "RISING")
        self.assertEqual(sum(ogdc["series"]), 3)
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
                             (vid, sym, m["title"], m["description"], m["transcript"], m["sentiment"], m["holds"]))
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
