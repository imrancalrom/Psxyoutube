"""Detect PSX stock mentions in video text and score the tone around each mention."""

import re
from dataclasses import dataclass

from .tickers import SECTOR_ALIASES, Stock

# Bullish / bearish cue words in English, Roman Urdu and Urdu script.
# Tone: words that make talk about a stock positive or negative. "Dividend", "targets" (as in "deposit targets") and
# "break down" (as in "we break down the results") describe rather than judge, so they aren't here.
BULLISH = [
    r"buy(?:ing)?", r"bullish", r"break\s?out", r"upside", r"accumulat\w*", r"rall(?:y|ies)",
    r"up\s?trend", r"undervalued", r"rebound\w*", r"multi\s?bagger", r"top picks?",
    r"strong results", r"record profits?", r"outperform\w*", r"all[\s-]time high", r"new high", r"momentum", r"turn\s?around",
    r"khareed\w*", r"kharid\w*", r"tezi", r"taizi", r"munafa", r"خرید\w*", r"تیزی", r"منافع",
]
BEARISH = [
    r"sell(?:ing)?", r"bearish", r"break(?:s|ing)?\s+below", r"breakdown\s+below", r"downside", r"crash\w*", r"dump\w*",
    r"down\s?trend", r"overvalued", r"(?<!stop )(?<!stop-)loss(?:es)?", r"avoid", r"exit", r"underperform\w*", r"red zone",
    r"girawat", r"mandi", r"mandee", r"nuqsan", r"nuksan", r"bech do", r"becho", r"مندی", r"گراوٹ", r"نقصان",
]
# Calls: explicit recommendations only, for the YouTube call column and the channel track record.
BUY_CALL = [
    r"buy(?:ing)?", r"accumulat(?:e|ing)", r"top picks?", r"multi\s?bagger(?!s|\s+stocks)", r"khareed\w*", r"kharid\w*", r"خرید\w*",
    r"price\s+targets?", r"targets?\s*(?:price\s*)?(?:of|at|is|:|-)?\s*(?:rs\.?|pkr)?\s*\d+(?:\.\d+)?",
]
SELL_CALL = [r"sell(?:ing)?", r"avoid", r"exit", r"book (?:your )?profits?", r"bech do", r"becho"]
# Money flows describe what investors did, not advice: "foreign buying", "selling pressure", "selling from banks".
FLOWS = (r"(?:foreign|institutional|local|retail|heavy|smart\s+money|fipi|lipi|mutual\s+funds?|investors?|banks?|"
         r"traders?|individuals?|people|public|crowd)\s+(?:are\s+|were\s+)?(?:buying|selling)|"
         r"(?:buying|selling)\s+(?:pressure|interest|spree|from|by|side|seen|was|in)")
# Generic how-to and advice phrases that use call words without recommending a stock.
NOT_CALLS = (r"how\s+to\s+(?:buy|sell)|planning\s+to\s+buy|buy\s+(?:order|button)|before\s+(?:buying|you\s+buy)|"
             r"(?:everyone|people|they)\s+says?\s+(?:buy|sell)|(?:can|could)\s+(?:actually\s+)?buy|"
             r"buy\s+(?:their|there)\s+shares|(?:they|it|which|who)\s+(?:do\s+|does\s+)?sells?|"
             r"avoid\s+(?:fomo|common|these|emotional|panic|mistakes?|traps?|losses|the\s+(?:crowd|mistakes?|traps?))|"
             r"how\s+to\s+\w+(?:\s+\w+)?\s+multi\s?bagger|became\s+an?\s+(?:[\w-]+\s+)?multi\s?bagger")
# Explicit "hold" calls. Buy or sell in the same clause wins ("buy and hold" is a buy).
# Bare "holding" is left out: it is usually a noun ("holdings", "holding company", "property holding").
HOLD = [r"hold(?!\s+(?:steady|firm|support|levels?|the line|ground))(?:\s+(?:on|kar\w*|rakh\w*))?", r"holding on",
        r"keep holding", r"stay invested", r"ہولڈ"]
NEGATORS = {"not", "don't", "dont", "never", "no", "mat", "na", "nahi", "nahin"}

_BULL_RE = re.compile(r"(?<!\w)(?:" + "|".join(BULLISH) + r")(?!\w)", re.IGNORECASE)
_BEAR_RE = re.compile(r"(?<!\w)(?:" + "|".join(BEARISH) + r")(?!\w)", re.IGNORECASE)
_HOLD_RE = re.compile(r"(?<!\w)(?:" + "|".join(HOLD) + r")(?!\w)", re.IGNORECASE)
_BUY_CALL_RE = re.compile(r"(?<!\w)(?:" + "|".join(BUY_CALL) + r")(?!\w)", re.IGNORECASE)
_SELL_CALL_RE = re.compile(r"(?<!\w)(?:" + "|".join(SELL_CALL) + r")(?!\w)", re.IGNORECASE)
_NOT_CALL_RE = re.compile(r"(?<!\w)(?:" + FLOWS + "|" + NOT_CALLS + r")(?!\w)", re.IGNORECASE)
# "Buy, sell or hold?", "BUY & SELL & HOLD", "buying and selling" name the options rather than make a call ("buy and
# hold" is still a buy).
_CALL_WORD = r"(?:buy|sell|hold|exit|entry)"
_OPTIONS_RE = re.compile(rf"(?<!\w)(?:{_CALL_WORD}(?:[\s,/|]+(?:or\s+)?{_CALL_WORD}(?!\w))+|"
                         r"buy(?:ing)?\s*(?:&|and)\s*sell(?:ing)?|sell(?:ing)?\s*(?:&|and)\s*buy(?:ing)?)(?!\w)",
                         re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"[.!?\n|۔؟]+")
# Clause breaks inside a sentence: punctuation and contrast words ("buy OGDC, but sell PSO", "OGDC lo lekin PSO becho").
_CLAUSE_SPLIT = re.compile(
    r"[,;:،؛]|\s[-–—]\s|(?<!\w)(?:but|while|whereas|however|vs\.?|versus|lekin|magar|jabke|jabkay|لیکن|مگر|جبکہ)(?!\w)",
    re.IGNORECASE,
)


@dataclass
class Mention:
    symbol: str
    start: int
    end: int
    sentiment: int  # tone: +1 bullish, -1 bearish, 0 neutral
    hold: int = 0  # 1 for an explicit hold call (and no buy/sell call)
    call: int = 0  # explicit recommendation: +1 buy, -1 sell, 0 none


def _alias_pattern(alias: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", alias.strip()) if p]
    return r"(?<!\w)" + r"[\s\-]*".join(parts) + r"(?!\w)"


class Analyzer:
    def __init__(self, stocks: dict[str, Stock], sectors: dict[str, list[str]] | None = None):
        self.stocks = stocks
        sectors = SECTOR_ALIASES if sectors is None else sectors
        self._sector_patterns = [(re.compile(_alias_pattern(a), re.IGNORECASE), sector)
                                 for sector, aliases in sectors.items() for a in aliases]
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
        return self._find(self._patterns, text)

    def find_sector_mentions(self, text: str) -> list[Mention]:
        """Sectors named outright ('refineries', 'OMCs', 'سیمنٹ'); Mention.symbol holds the sector name.

        Sector words inside a stock's name ('Lucky Cement', 'Engro Fertilizer') don't count: that is the stock.
        """
        stocks = [(m.start, m.end) for m in self.find_mentions(text)]
        return [m for m in self._find(self._sector_patterns, text, stocks)
                if all(m.end <= s or m.start >= e for s, e in stocks)]

    @staticmethod
    def _find(patterns, text: str, mask: list[tuple[int, int]] = ()) -> list[Mention]:
        if not text:
            return []
        candidates = []
        for rx, symbol in patterns:
            for m in rx.finditer(text):
                candidates.append((m.start(), m.end(), symbol))
        candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
        taken: list[tuple[int, int, str]] = []
        for start, end, symbol in candidates:
            if all(end <= s or start >= e for s, e, _ in taken):
                taken.append((start, end, symbol))
        taken.sort()
        # Blank out the names themselves before scoring, so "Engro Holdings" or "Pakistan Refinery" carry no cue.
        scored = list(text)
        for s, e in [*mask, *((s, e) for s, e, _ in taken)]:
            scored[s:e] = " " * (e - s)
        scored = "".join(scored)
        return [Mention(sym, s, e, *_tone(scored, s, e)) for s, e, sym in taken]


def _score(fragment: str, up=_BULL_RE, down=_BEAR_RE, hold=None) -> tuple[int, int]:
    """(up minus down cues, hold cues) in a fragment; a negated cue counts the other way ("don't hold" is a sell)."""
    score = holds = 0
    for rx, sign in ((up, 1), (down, -1), *(((hold, 0),) if hold else ())):
        for m in rx.finditer(fragment):
            before = fragment[: m.start()].lower().split()[-2:]
            negated = any(w.strip(",;:") in NEGATORS for w in before)
            if sign == 0:
                score, holds = (score - 1, holds) if negated else (score, holds + 1)
            else:
                score += -sign if negated else sign
    return score, holds


def _span(split_re: re.Pattern, text: str, start: int, end: int, lo: int = 0, hi: int | None = None) -> tuple[int, int]:
    """Bounds of the piece of text[lo:hi], cut by split_re, that contains text[start:end]."""
    hi = len(text) if hi is None else hi
    left = max((m.end() for m in split_re.finditer(text, lo, start)), default=lo)
    right_match = split_re.search(text, end, hi)
    return left, right_match.start() if right_match else hi


def _tone(text: str, start: int, end: int) -> tuple[int, int, int]:
    """(tone, hold, call) around text[start:end]: tone +1/-1/0 from tone words; call +1 buy / -1 sell / 0 from explicit
    recommendations; hold 1 for an explicit hold call with no buy/sell call.

    The clause holding the mention decides ("Buy OGDC, sell PSO" is buy OGDC, sell PSO); when that clause has no cue
    words the whole sentence is used ("OGDC, PPL and PSO: buy all three"). A question ("Is OGDC still undervalued?")
    makes neither a tone nor a call, and nor does a list of options ("Buy, sell or hold?").
    """
    s_left, s_right = _span(_SENTENCE_SPLIT, text, start, end)
    if s_right < len(text) and text[s_right] in "?؟":
        return 0, 0, 0
    c_left, c_right = _span(_CLAUSE_SPLIT, text, start, end, s_left, s_right)

    def pick(up, down, hold=None, mask=None):
        for left, right in ((c_left, c_right), (s_left, s_right)):
            fragment = text[left:right]
            if _OPTIONS_RE.search(fragment):
                return 0, 0
            if mask:
                fragment = mask.sub(lambda m: " " * len(m.group()), fragment)
            score, holds = _score(fragment, up, down, hold)
            if score or holds:
                return score, holds
        return 0, 0

    tone_score, _ = pick(_BULL_RE, _BEAR_RE)
    call_score, holds = pick(_BUY_CALL_RE, _SELL_CALL_RE, _HOLD_RE, _NOT_CALL_RE)
    call = (call_score > 0) - (call_score < 0)
    return (tone_score > 0) - (tone_score < 0), int(call == 0 and holds > 0), call


def sentence_sentiment(text: str, start: int, end: int) -> int:
    """Tone around text[start:end]: +1, -1 or 0."""
    return _tone(text, start, end)[0]


def boilerplate_lines(descriptions: list[str], share: float = 0.5, min_videos: int = 3) -> set[str]:
    """Description lines a channel repeats under most of its videos (links, hashtag blocks, disclaimers).

    They say nothing about a particular video, and a '#banking' or '$OGDC' in them would otherwise
    count for every upload.
    """
    if len(descriptions) < min_videos:
        return set()
    counts: dict[str, int] = {}
    for d in descriptions:
        for line in {ln.strip() for ln in (d or "").splitlines() if ln.strip()}:
            counts[line] = counts.get(line, 0) + 1
    need = max(min_videos, share * len(descriptions))
    return {line for line, n in counts.items() if n >= need}


_PAYMENT = re.compile(r"\b(?:iban|title of account|account\s*(?:no\b|number|title|details|#|:)|a/c\b)", re.IGNORECASE)
_ACCOUNT_NUMBER = re.compile(r"\b(?:iban|account\s*(?:no\b|number|#|:)|a/c\b)", re.IGNORECASE)


def strip_payment_details(text: str) -> str:
    """Drop bank-account blocks ('MCB / ACCOUNT: ... / IBAN: ...') that channels post for course fees.

    An account-number line also takes the short line just above it, which usually names the bank and would
    otherwise count as MCB, BOP, HBL...
    """
    lines = (text or "").splitlines()
    drop = set()
    for i, ln in enumerate(lines):
        if _PAYMENT.search(ln):
            drop.add(i)
            if _ACCOUNT_NUMBER.search(ln) and i > 0 and len(lines[i - 1].split()) <= 3:
                drop.add(i - 1)
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)


_URL = re.compile(r"https?://\S+")


def title_key(text: str) -> str:
    """A video title or description line reduced for comparison: no links, bullets, emoji or case."""
    text = _URL.sub(" ", text)
    return " ".join(re.sub(r"[^\w\s|&%.,:'?!-]", " ", text).split()).strip(" -|:").lower()


def strip_video_titles(text: str, titles: set[str]) -> str:
    """Drop description lines that are the title of another video on the channel ('WATCH OUR MOST USEFUL VIDEOS'
    lists): they link elsewhere and say nothing about this video."""
    if not titles:
        return text or ""
    return "\n".join(ln for ln in (text or "").splitlines() if title_key(ln) not in titles)


def strip_lines(text: str, lines: set[str]) -> str:
    if not lines:
        return text or ""
    return "\n".join(ln for ln in (text or "").splitlines() if ln.strip() not in lines)


def _summarize(find, title: str, description: str, transcript: str | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for source, text in (("title", title), ("description", description), ("transcript", transcript)):
        for m in find(text or ""):
            row = out.setdefault(m.symbol, {"title": 0, "description": 0, "transcript": 0, "sentiment": 0, "holds": 0,
                                            "calls": 0})
            row[source] += 1
            row["sentiment"] += m.sentiment
            row["holds"] += m.hold
            row["calls"] += m.call
    return out


def analyze_video(analyzer: Analyzer, title: str, description: str, transcript: str | None) -> dict[str, dict]:
    """Per-symbol summary for one video: mention counts by source and net sentiment."""
    return _summarize(analyzer.find_mentions, title, description, transcript)


def analyze_video_sectors(analyzer: Analyzer, title: str, description: str, transcript: str | None) -> dict[str, dict]:
    """Same as analyze_video, keyed by sector, for sectors named outright."""
    return _summarize(analyzer.find_sector_mentions, title, description, transcript)
