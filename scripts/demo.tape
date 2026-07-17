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

Sleep 60s
