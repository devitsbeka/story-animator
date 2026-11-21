# Style lock: the reference look, rebuilt as code

`ref/reference.jpg` is the target. This project rebuilds it as vector art drawn by React/SVG in Remotion,
split into rigged parts and depth planes so it can be animated with a camera and physics.

## Pipeline (`trace/`, Python: opencv, numpy, vtracer)
1. `extract.py`: segments the reference into parts using the ink lines (head, hands, forearms, torso,
   eyes, brows, mouth), lifts the paper ball out as a physics prop, splits the background into depth
   layers (room / desk / lamp), refills anything hidden behind a part, and writes `src/assets/rig.json`
   (pivots, head ellipse, colours).
2. `build_assets.py`: turns each layer into `src/assets/<layer>.json`:
   - `sil`: the part's silhouette, a solid underlay so no gaps show when parts move;
   - `base`: a coarse colour grid the renderer blurs, which keeps soft light and gradients;
   - `paths`: vtracer spline paths for the drawn detail.

Re-run: `../.venv/bin/python trace/extract.py && ../.venv/bin/python trace/build_assets.py`

## Engine (`src/engine/index.tsx`)
- **Rig**: `solveRig(bones, pose)`. Bones have a parent and a pivot. A `Pose` sets rot/offset/scale
  per bone. `mixPose` blends poses for keyframed acting.
- **Physics**: `simulate(key, frame, init, step)`, a fixed-substep sim cached per frame, so it's
  deterministic and safe for parallel rendering. `springStep` gives secondary motion (lag, overshoot);
  `bodyStep` is a rigid ball with gravity, bounce, friction and rolling.
- **Camera**: a 2.5D pinhole over depth planes (`Plane z=…`). At rest every plane lines up with the
  reference. Pan, zoom and dolly produce real parallax. `camAt(frame, keys)` eases between keyframes.

## Scene (`src/Study.tsx`)
`StudySquare` is the 1:1 still at rest, for comparison with the reference. `Study916` is the 9:16
motion test: push-in, a sigh driven by keyed poses plus spring physics, blinks and worried brows,
and a paper ball rolling in.

Render (point Remotion at the system Chromium, since its own browser fails the proxy certificate check):
`npx remotion render src/index.ts Study916 out/study916.mp4 --browser-executable=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome`
