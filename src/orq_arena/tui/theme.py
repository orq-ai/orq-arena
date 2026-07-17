"""CRT-neon palette, dark arcade glass, loud neon foregrounds.

Ported from the chennai fork. One module so every widget draws from the same
colors. Side identity (owner decision 13): **A = magenta, B = cyan**;
green/orange/red stay reserved for HP states, win/loss, and errors.

Registered as a Textual theme, so all existing ``$token`` CSS re-colors:
$accent → magenta (side A), $primary → cyan (side B), $success/$warning/
$error → semantic green/orange/red.
"""

from __future__ import annotations

from textual.theme import Theme

INK = "#0b0514"  # near-black with a whisper of violet (never pure #000)
INK_RAISED = "#150a22"  # one step up, for panels
INK_DEEP = "#060310"  # one step down, for deepest wells

CHROME = "#f2ecff"  # off-white text (never pure #fff)
CHROME_DIM = "#9b8fc2"  # muted labels

MAGENTA = "#ff3bd4"  # side A + titles
CYAN = "#00e5ff"  # side B + chrome accents
YELLOW = "#ffd54d"  # highlights, ties, scoreboard rank
GREEN = "#00ff7f"  # high HP, winner announce
ORANGE = "#ff9e3b"  # mid HP / caution
RED = "#ff4d4d"  # low HP / errors / KO

CRT_THEME = Theme(
    name="crt-neon",
    dark=True,
    primary=CYAN,  # side B + default borders
    secondary=CYAN,
    accent=MAGENTA,  # side A + headings
    success=GREEN,
    warning=ORANGE,
    error=RED,
    background=INK,
    surface=INK,
    panel=INK_RAISED,
    foreground=CHROME,
)

# orq v2 brand mode: the HTML report's dark-mode design tokens (report.py
# _ROOT_CSS) mapped onto the same roles. Pulse Orange headings, indigo
# chrome, neutral black; sides keep the report's own A/B pair.
ORQ_THEME = Theme(
    name="orq-arena",
    dark=True,
    primary="#8a8dff",  # indigo: borders, progress
    secondary="#8a8dff",
    accent="#ff8f34",  # Pulse Orange: banner + headings
    success="#4bbe8e",
    warning="#e0b64a",
    error="#f28a8a",
    background="#0a0a0a",
    surface="#0a0a0a",
    panel="#171717",
    foreground="#fafafa",
)

THEMES = {t.name: t for t in (CRT_THEME, ORQ_THEME)}
