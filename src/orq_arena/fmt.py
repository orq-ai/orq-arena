"""Number formats shared by the dossier, the TUI, the headless table and the report."""

from __future__ import annotations


def fmt_duration(ms: int) -> str:
    """``45s`` under a minute, else ``2m 05s``."""
    s = max(0, int(ms)) // 1000
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def fmt_cost(usd: float, estimated: bool = False, digits: int = 2) -> str:
    """``$0.21``; ``~$0.21`` when it is a token count priced at the catalog rate, not a reported cost."""
    return f"{'~' if estimated else ''}${usd:.{digits}f}"


def harness_cells(h: dict, missing: str = "n/a") -> list[str]:
    """pass rate, $/task and min/task for one harness summary row.

    Voided trials sit beside the pass rate (a harness that voids 8 of 10 must not read 2/2),
    ``~`` marks a cost priced from tokens, and trials with no cost at all are counted beside
    the mean, which is over the priced trials only.
    """
    rate = f"{h.get('passed', 0)}/{h['verified']}" if h.get("verified") else missing
    if h.get("unverified"):
        rate += f" ({h['unverified']} void)"
    mean = h.get("mean_cost_usd")
    if mean is None:
        cost = missing
    else:
        cost = f"{'~' if h.get('estimated') else ''}{mean:.2f}"
        unpriced = h.get("trials", 0) - h.get("priced", h.get("trials", 0))
        if unpriced > 0:
            cost += f" ({unpriced} unpriced)"
    secs = h.get("mean_duration_s")
    return [rate, cost, missing if secs is None else f"{secs / 60:.1f}"]
