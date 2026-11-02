"""Shariah-compliant stocks: the constituents of the PSX-KMI All Share Islamic Index, kept in shariah.txt.

PSX recomposes the index twice a year (notices on psx.com.pk / dps.psx.com.pk), so the file says which notice it
follows; update it when a new one comes out. Lines starting `# source:` and `# as of:` are shown on the dashboard.
"""

import re
from pathlib import Path

from .watchlist import parse


def load(path: str | Path | None) -> dict | None:
    """{"symbols": [...], "source": str, "as_of": str}, or None when there is no list (the filter is then hidden)."""
    if not path or not Path(path).exists():
        return None
    text = Path(path).read_text(encoding="utf-8")
    symbols = parse(text)
    if not symbols:
        return None
    meta = {}
    for key in ("source", "as of"):
        m = re.search(rf"^#\s*{key}\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        meta[key.replace(" ", "_")] = m.group(1).strip() if m else ""
    return {"symbols": symbols, **meta}
