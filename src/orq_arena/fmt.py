"""Number formats shared by the dossier, the TUI, the headless table and the report."""

from __future__ import annotations


def fmt_duration(ms: int) -> str:
    """``45s`` under a minute, else ``2m 05s``."""
    s = max(0, int(ms)) // 1000
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def fmt_cost(usd: float, estimated: bool = False, digits: int = 2) -> str:
    """``$0.21``; ``~$0.21`` when it is a token count priced at the catalog rate, not a reported cost."""
    return f"{'~' if estimated else ''}${usd:.{digits}f}"
