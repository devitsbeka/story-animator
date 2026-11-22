# How the factory learns from mistakes (and never repeats them)

Principle: **a defect is never fixed in an episode. It is fixed in the engine, it gets an automatic check, it gets
regression scenarios that reproduce the whole defect class, and the gate enforces all of it forever.**

## The loop

1. **Found:** the user, QC, the vision reviewer or a render notices a defect.
2. **Ledger:** `python -m factory.lessons add --symptom ... --root-cause ... --rule ... --gate ...` gives it a lesson id in `lessons.yaml`.
3. **Root cause in the engine:** the fix goes where every future episode inherits it, never into one shot's data:
   - acting / hand / face engines (`cloud/blender/acting.py`, `hand_poses.py`, `cloudrig_adapter.py`, `face.py`)
   - camera presets and validator (`factory/direction/`)
   - lighting and materials (`cloud/blender/lighting.py`, `materials.py`)
   - library tiers (`factory/library/catalog.json`)
   - director prompts and checks (`factory/director/`)
4. **Check:** an automated test that fails on the original defect. Kinds of check:
   - geometric: pose QC (palm normal, wrist bend, finger curl, seat contact), framing, camera collision
   - temporal: face-life variance, frozen-frame detection
   - technical: QC video and audio rules
   - visual: the vision rubric item
5. **Regression cases:** the lesson attaches **stress scenarios** that reproduce the defect class across worlds, poses, props, shot sizes and emotions (`factory/goldens/stress/`), not just the shot where it was seen.
6. **Gate:** every change must pass `tools/merge_gate.sh`. That runs tests, lesson checks, Sentinel goldens and **all stress scenarios**. Every episode runs the per-shot checks before previs approval and before render. A failing shot goes back to direction automatically with the failing rule as feedback. If it still fails, it blocks.
7. **Closed:** a lesson is closed only when its check plus its regression cases run in the gate and fail on the original defect.

## Why this scales across prompts

- Rules live in the engines' **defaults and constraints**, so any new idea, world kit or style inherits them without anyone remembering.
- The stress suite is **generated combinatorially** (stance × hand shape × world × shot size × emotion), so a fix proven on one shot is proven on the class.
- The director gets the rules in its prompt **before** drafting, so most defects never get generated in the first place. The checks catch the rest.
- Goldens make **quality monotonic**: anything that degrades fails, and an improvement becomes the new bar only with explicit approval.
