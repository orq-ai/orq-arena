# vhs tape for media/demo.gif: the live show replaying the committed run.
#   vhs scripts/demo.tape   (run from the repo root)
Output media/demo.gif

Set FontSize 13
Set Width 1500
Set Height 860
Set Padding 6
Set Framerate 24

Hide
Type "uv run python scripts/record_demo_gif.py"
Enter
Show

# 5s Run Plan + ~23s replay + a leaderboard tail; the app holds the leaderboard
# longer than this on purpose, so the gif always ends there, never on a prompt
Sleep 40s
