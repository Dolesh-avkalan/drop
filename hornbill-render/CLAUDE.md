# Hornbill render helper (for the agent on this PC)

Goal: render frames of the Hornbill film with headless Blender on this PC and
push them to this repo. The studio PC renders the same film from the start;
this PC renders from the END backwards. Nothing else to decide.

## Steps

1. Blender **5.2** must be installed. Find `blender.exe` (usually
   `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`). If it is
   missing, ask the user to install Blender 5.2 (portable zip is fine).
2. Check that `git push` works from this folder (this PC needs push access to
   `Dolesh-avkalan/drop`). If it is refused, stop and tell the user.
3. Run, from this folder (`hornbill-render`), and leave it running:

       python go.py --blender "<path to blender.exe>"

   It joins the scene file from its parts (checksum checked), checks textures
   (the log line `HH missing files:` should say `none`), uses the GPU, then
   renders 10 frames at a time from frame 697 downwards and pushes each batch
   (`frames/f_####.png`). It stops by itself when it meets the frames the
   studio PC already rendered (`control.json`, updated from the studio side).
4. Report to the user: the GPU line (`HH device:`), the seconds per frame it
   prints, and when it says `DONE`.

## Rules

- Do not change the scene, `render.py`, `control.json` or the settings.
- If Blender crashes or a batch fails, run `go.py` again (it skips frames that
  are already in `frames/`).
- Never push anything except `frames/`.
