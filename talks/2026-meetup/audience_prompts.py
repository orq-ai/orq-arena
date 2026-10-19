"""Seed prompts plus the audience's form export, as one prompts JSONL for orq-arena.

    python3 talks/2026-meetup/audience_prompts.py form.csv -o /tmp/meetup.jsonl
    python3 talks/2026-meetup/audience_prompts.py -o /tmp/meetup.jsonl   # seed only

Only the prompt column is read (the first header containing "prompt"); timestamps,
names and emails in the export never reach the output. Blank, over-long and repeated
prompts are dropped; newlines and tabs become one space.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

SEED = Path(__file__).with_name("seed.jsonl")


def _flat(text: str) -> str:
    return " ".join(text.split())


def audience_prompts(csv_path: Path) -> list[str]:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        col = next((i for i, h in enumerate(header) if "prompt" in h.lower()), None)
        if col is None:
            raise SystemExit(f"no column with 'prompt' in its name in {csv_path}: {header}")
        return [_flat(row[col]) for row in reader if col < len(row)]


def build(seed: Path, csv_path: Path | None, out: Path, *, max_chars: int = 600) -> int:
    lines = seed.read_text(encoding="utf-8").splitlines()
    seen = {_flat(json.loads(line)["prompt"]) for line in lines}
    for text in audience_prompts(csv_path) if csv_path else []:
        if text and len(text) <= max_chars and text not in seen:
            seen.add(text)
            lines.append(json.dumps({"prompt": text, "category": "audience"}))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return len(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("csv", nargs="?", type=Path, help="form export (CSV); omit for seed only")
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--max-chars", type=int, default=600)
    args = p.parse_args(argv)
    n = build(SEED, args.csv, args.output, max_chars=args.max_chars)
    print(
        f"{n} prompts ({n - len(SEED.read_text().splitlines())} from the audience) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
