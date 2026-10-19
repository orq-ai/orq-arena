"""Offline check for the meetup deck. Run: python3 talks/2026-meetup/check.py

Fails on an em-dash, a network reference, a missing or reordered slide, a fixed
pixel width too wide for a laptop, or a toy whose math check throws under node.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE / "talk.html"
SLIDES = [
    "title",
    "hook",
    "build",
    "byok",
    "judges",
    "bt",
    "deciders",
    "ring",
    "result",
    "agents",
    "close",
]
MAX_PX_WIDTH = 900

# Node has no DOM: the toys block must only define things at load time.
NODE_HARNESS = """
const document = {}, window = {};
{toys}
for (const [name, check] of Object.entries(TOY_CHECKS)) check();
console.log('toy checks: ' + (Object.keys(TOY_CHECKS).join(', ') || 'none'));
"""


def problems() -> list[str]:
    if not DECK.exists():
        return [f"{DECK.name} missing"]
    html = DECK.read_text(encoding="utf-8")
    found = []
    for path in sorted(HERE.rglob("*")):
        if "fallback" in path.relative_to(HERE).parts:
            continue  # a recorded run: model output and the generated report, not our writing
        if path.is_file() and path.suffix in {".html", ".py", ".md", ".jsonl", ".yaml", ".svg"}:
            if chr(0x2014) in path.read_text(encoding="utf-8", errors="ignore"):
                found.append(f"em-dash in {path.relative_to(HERE)}")
    if m := re.search(r"""(?:src=|href=|@import|url\()\s*["']?https?:""", html):
        found.append(f"network reference: {m.group(0)}")
    sections = re.findall(r"<section\b[^>]*\bclass=\"slide\b[^>]*>", html)
    ids = [re.search(r'\bid="([^"]+)"', s).group(1) if 'id="' in s else "?" for s in sections]
    if ids != SLIDES:
        found.append(f"slide ids {ids} != {SLIDES}")
    found += [f"slide without data-chapter: {s}" for s in sections if "data-chapter=" not in s]
    for m in re.finditer(r"(?<![-\w])(?:min-|max-)?width\s*:\s*(\d+)px", html):
        if int(m.group(1)) > MAX_PX_WIDTH:
            found.append(f"fixed width over {MAX_PX_WIDTH}px: {m.group(0)}")
    found += toy_problems(html)
    return found


def toy_problems(html: str) -> list[str]:
    node = shutil.which("node")
    if not node:
        print("node not on PATH: toy math not checked")
        return []
    m = re.search(r'<script id="toys">(.*?)</script>', html, re.S)
    if not m:
        return ['no <script id="toys"> block']
    run = subprocess.run(
        [node, "-"],
        input=NODE_HARNESS.replace("{toys}", m.group(1)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if run.returncode:
        lines = run.stderr.strip().splitlines() or ["?"]
        return [
            "toy checks failed: "
            + next((x for x in lines if re.match(r"\s*\w*Error\b", x)), lines[-1])
        ]
    print(run.stdout.strip())
    return []


def main() -> int:
    found = problems()
    for p in found:
        print("FAIL", p)
    if not found:
        print("ok")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
