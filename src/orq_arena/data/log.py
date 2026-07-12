"""Battle log writer, append-only JSONL compatible with orq-battlebench."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .schemas import BattleRecord


class BattleLog:
    """Append-only JSONL sink for ``BattleRecord`` objects."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate on open, one tournament per run.
        self.path.write_text("")

    def append(self, battle: BattleRecord) -> None:
        line = battle.model_dump_json()
        with self.path.open("a") as fh:
            fh.write(line + "\n")

    def append_many(self, battles: Iterable[BattleRecord]) -> None:
        with self.path.open("a") as fh:
            for b in battles:
                fh.write(b.model_dump_json() + "\n")
