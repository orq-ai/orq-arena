"""JSONL prompt loader.

Format: one JSON object per line with at least a ``prompt`` key; optional
``category`` and ``length_bucket`` metadata are preserved but not required.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_prompts(path: str | Path) -> list[str]:
    """Return the list of prompt strings in file order."""
    p = Path(path)
    out: list[str] = []
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = row.get("prompt") or row.get("text")
            if not text:
                continue
            out.append(text)
    return out
