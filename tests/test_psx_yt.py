import sqlite3
import unittest
from datetime import date

from psx_yt import db
from psx_yt.analyzer import Analyzer, analyze_video
from psx_yt.tickers import load_tickers
from psx_yt.trends import compute, trend_label
from psx_yt.youtube import parse_rss, resolve_channel

ANALYZER = Analyzer(load_tickers())


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
        self.assertEqual(self.tone("PSO mein girawat"), [("PSO", -1)])

    def test_negation(self):
        self.assertEqual(self.tone("Don't buy TRG now"), [("TRG", -1)])

    def test_analyze_video_sources(self):
        out = analyze_video(ANALYZER, "OGDC breakout", "OGDC and PPL details", None)
        self.assertEqual(out["OGDC"], {"title": 1, "description": 1, "transcript": 0, "sentiment": 1})
        self.assertNotIn("PPL", out)  # untagged PPL is ambiguous


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


class TrendTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(trend_label(6, 2), "RISING")
        self.assertEqual(trend_label(1, 4), "FALLING")
        self.assertEqual(trend_label(3, 0), "NEW")
        self.assertEqual(trend_label(3, 3), "STEADY")

    def test_compute(self):
        conn = db.connect(":memory:")
        db.upsert_channel(conn, "UC1", "Chan 1")
        vids = [("v1", "2026-10-28T10:00:00Z", "Buy OGDC now", 1000),
                ("v2", "2026-10-27T10:00:00Z", "OGDC target", 100),
                ("v3", "2026-10-20T10:00:00Z", "OGDC sell", 10)]
        for vid, ts, title, views in vids:
            db.upsert_video(conn, {"id": vid, "channel_id": "UC1", "title": title, "published_at": ts, "views": views})
            for sym, m in analyze_video(ANALYZER, title, "", None).items():
                conn.execute("INSERT INTO mentions VALUES (?,?,?,?,?,?)",
                             (vid, sym, m["title"], m["description"], m["transcript"], m["sentiment"]))
        data = compute(conn, load_tickers(), days=30, today=date(2026, 10, 29))
        ogdc = data["stocks"][0]
        self.assertEqual((ogdc["symbol"], ogdc["videos"], ogdc["recent"], ogdc["previous"]), ("OGDC", 3, 2, 1))
        self.assertEqual((ogdc["bullish"], ogdc["bearish"]), (2, 1))
        self.assertEqual(ogdc["trend"], "RISING")
        self.assertEqual(sum(ogdc["series"]), 3)


if __name__ == "__main__":
    unittest.main()
