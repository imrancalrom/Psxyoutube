"""Detect PSX stock mentions in video text and score the tone around each mention."""

import re
from dataclasses import dataclass

from .tickers import Stock

# Bullish / bearish cue words in English, Roman Urdu and Urdu script.
BULLISH = [
    r"buy(?:ing)?", r"bullish", r"break\s?out", r"targets?", r"upside", r"accumulat\w*", r"rall(?:y|ies)",
    r"up\s?trend", r"undervalued", r"dividends?", r"payout", r"rebound\w*", r"multi\s?bagger", r"top pick",
    r"strong results", r"record profits?", r"outperform\w*", r"all[\s-]time high", r"new high",
    r"khareed\w*", r"kharid\w*", r"tezi", r"taizi", r"munafa", r"خرید\w*", r"تیزی", r"منافع",
]
BEARISH = [
    r"sell(?:ing)?", r"bearish", r"break\s?down", r"downside", r"crash\w*", r"dump\w*", r"down\s?trend",
    r"overvalued", r"loss(?:es)?", r"avoid", r"exit", r"underperform\w*", r"red zone",
    r"girawat", r"mandi", r"mandee", r"nuqsan", r"nuksan", r"bech do", r"becho", r"مندی", r"گراوٹ", r"نقصان",
]
NEGATORS = {"not", "don't", "dont", "never", "no", "mat", "na", "nahi", "nahin"}

_BULL_RE = re.compile(r"(?<!\w)(?:" + "|".join(BULLISH) + r")(?!\w)", re.IGNORECASE)
_BEAR_RE = re.compile(r"(?<!\w)(?:" + "|".join(BEARISH) + r")(?!\w)", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"[.!?\n|۔؟]+")


@dataclass
class Mention:
    symbol: str
    start: int
    end: int
    sentiment: int  # +1 bullish, -1 bearish, 0 neutral


def _alias_pattern(alias: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", alias.strip()) if p]
    return r"(?<!\w)" + r"[\s\-]*".join(parts) + r"(?!\w)"


class Analyzer:
    def __init__(self, stocks: dict[str, Stock]):
        self.stocks = stocks
        patterns = []  # (compiled regex, symbol)
        for s in stocks.values():
            sym = re.escape(s.symbol)
            if s.ambiguous:
                # Everyday-word symbols only count when tagged like $LUCK or #LUCK.
                patterns.append((re.compile(r"(?<![\w$#])[$#]" + sym + r"(?!\w)", re.IGNORECASE), s.symbol))
            else:
                patterns.append((re.compile(r"(?<![\w$#])[$#]?" + sym + r"(?!\w)", re.IGNORECASE), s.symbol))
            for alias in s.aliases:
                patterns.append((re.compile(_alias_pattern(alias), re.IGNORECASE), s.symbol))
        self._patterns = patterns

    def find_mentions(self, text: str) -> list[Mention]:
        """All non-overlapping stock mentions; longer matches win (so 'engro fertilizer' is EFERT, not ENGROH)."""
        if not text:
            return []
        candidates = []
        for rx, symbol in self._patterns:
            for m in rx.finditer(text):
                candidates.append((m.start(), m.end(), symbol))
        candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
        taken: list[tuple[int, int, str]] = []
        for start, end, symbol in candidates:
            if all(end <= s or start >= e for s, e, _ in taken):
                taken.append((start, end, symbol))
        taken.sort()
        return [Mention(sym, s, e, sentence_sentiment(text, s, e)) for s, e, sym in taken]


def _score(fragment: str) -> int:
    score = 0
    for rx, sign in ((_BULL_RE, 1), (_BEAR_RE, -1)):
        for m in rx.finditer(fragment):
            before = fragment[: m.start()].lower().split()[-2:]
            negated = any(w.strip(",;:") in NEGATORS for w in before)
            score += -sign if negated else sign
    return score


def sentence_sentiment(text: str, start: int, end: int) -> int:
    """Tone of the sentence containing text[start:end]: +1, -1 or 0."""
    left = max((m.end() for m in _SENTENCE_SPLIT.finditer(text, 0, start)), default=0)
    right_match = _SENTENCE_SPLIT.search(text, end)
    right = right_match.start() if right_match else len(text)
    score = _score(text[left:right])
    return (score > 0) - (score < 0)


def analyze_video(analyzer: Analyzer, title: str, description: str, transcript: str | None) -> dict[str, dict]:
    """Per-symbol summary for one video: mention counts by source and net sentiment."""
    out: dict[str, dict] = {}
    for source, text in (("title", title), ("description", description), ("transcript", transcript)):
        for m in analyzer.find_mentions(text or ""):
            row = out.setdefault(m.symbol, {"title": 0, "description": 0, "transcript": 0, "sentiment": 0})
            row[source] += 1
            row["sentiment"] += m.sentiment
    return out
