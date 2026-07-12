"""JSONL prompt loader.

Format: one JSON object per line with at least a ``prompt`` key; optional
``category`` feeds the per-category ELO slices (untagged rows land in
``"general"``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptItem:
    text: str
    category: str = "general"


def load_prompts(path: str | Path) -> list[PromptItem]:
    """Return the prompts in file order."""
    p = Path(path)
    out: list[PromptItem] = []
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = row.get("prompt") or row.get("text")
            if not text:
                continue
            out.append(PromptItem(text=text, category=row.get("category") or "general"))
    return out
