"""CRT-neon palette, dark arcade glass, loud neon foregrounds.

Ported from the chennai fork. One module so every widget draws from the same
colors. Side identity (owner decision 13): **A = magenta, B = cyan**;
green/orange/red stay reserved for HP states, win/loss, and errors.

Registered as a Textual theme, so all existing ``$token`` CSS re-colors:
$accent → magenta (side A), $primary → cyan (side B), $success/$warning/
$error → semantic green/orange/red.
"""

from __future__ import annotations

from evaluatorq.common.reports.palette import COLORS
from textual.color import Color
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

# orq brand mode: roles taken from evaluatorq's report palette, the one the
# HTML report and the annotate page use, so the three read as one system.
# Sides follow the evaluatorq pairwise chips: A blue, B purple. Purple and
# red are lifted a step because the brand values are tuned for a light page
# and read too dark as text on this background.
ORQ_THEME = Theme(
    name="orq-arena",
    dark=True,
    primary=Color.parse(COLORS["purple_400"]).lighten(0.25).hex,  # side B + borders
    secondary=Color.parse(COLORS["purple_400"]).lighten(0.25).hex,
    accent=COLORS["blue_400"],  # side A + banner + headings
    success=COLORS["success_400"],
    warning=COLORS["orange_300"],  # Pulse Orange
    error=Color.parse(COLORS["red_400"]).lighten(0.15).hex,
    background=COLORS["ink_800"],
    surface=COLORS["ink_800"],
    panel=COLORS["ink_700"],
    foreground=COLORS["sand_100"],
)

THEMES = {t.name: t for t in (CRT_THEME, ORQ_THEME)}
