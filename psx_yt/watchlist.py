"""The stocks you hold or follow: the dashboard and the digest put them first.

Listed in watchlist.txt (one or more symbols per line, # comments), and/or in the WATCHLIST environment variable
(in the daily workflow: the repository variable WATCHLIST, which unlike a committed file isn't public). Both are
merged; unknown symbols are reported and left out.
"""

import os
import re
import sys
from pathlib import Path

from .tickers import Stock

ENV = "WATCHLIST"


def parse(text: str) -> list[str]:
    """Symbols from free text: separated by spaces, commas or new lines; anything after # is a comment."""
    out = []
    for line in text.splitlines():
        for sym in re.split(r"[\s,;]+", line.split("#", 1)[0]):
            sym = sym.strip().upper()
            if sym and sym not in out:
                out.append(sym)
    return out


def load(path: str | Path | None, stocks: dict[str, Stock], env: str | None = None) -> list[str]:
    """Watched symbols in listed order, file first, then the environment variable; unknown ones skipped with a note."""
    text = ""
    if path and Path(path).exists():
        text = Path(path).read_text(encoding="utf-8")
    text += "\n" + (env if env is not None else os.environ.get(ENV, ""))
    symbols, unknown = [], []
    for sym in parse(text):
        (symbols if sym in stocks else unknown).append(sym)
    if unknown:
        print(f"Watchlist: skipped unknown symbol{'s' if len(unknown) > 1 else ''} {', '.join(unknown)} "
              "(check the spelling, or add them to tickers_extra.csv)", file=sys.stderr)
    return symbols
