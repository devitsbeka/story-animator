# cloud/spec: the episode spec and the exporter

This directory holds:

- **`episode.schema.json`**: the episode spec as a JSON Schema (draft 2020-12). One `episodes/<id>/episode.json` describes everything the Blender renderer needs: shots, camera keys, yacht state, actors and motion tracks, island fires, captions, audio and asset keys.
- **`cli.mjs`**: the exporter. It reads the code-driven Remotion/three.js episode in `studio/src`, then:
  1. writes `episodes/<id>/episode.json` and validates it with ajv plus semantic checks.
  2. exports the code-built props (`buildYacht`, `buildIsland`) to GLB under `studio/public/assets/props/`.
- **`validate.mjs`**: a standalone validator that CI, the API and the render worker can all use.

## Run locally (no secrets)

```bash
cd cloud/spec && npm install          # pinned: esbuild 0.28.1, three 0.169.0, ajv 8.20.0, ajv-formats 3.0.1
node cloud/spec/cli.mjs --episode sentinel              # spec + props (about 1 s)
node cloud/spec/cli.mjs --episode sentinel --no-props   # spec only
node cloud/spec/validate.mjs episodes/sentinel/episode.json [--root DIR] [--assets-root DIR] [--no-files]
```

Options: `--out FILE`, `--assets-root DIR` (default `studio/public/assets`), `--only yacht,island`, `--no-spec`, `--instanced`, `--json`.
The exit code is non-zero if the spec is invalid or a referenced file is missing.

## Run in cloud

The exporter is a pure Node step (Node 20 or later) with no GPU and no secrets. A worker can:

1. check out the repo and run `npm ci` here.
2. run `node cloud/spec/cli.mjs --episode <id> --out /tmp/ep/episodes/<id>/episode.json --assets-root /tmp/ep/assets`.
3. upload the outputs to R2 under the same keys (`episodes/<id>/episode.json`, `assets/props/*.glb`).

The upload is done by the storage component, not here. This directory needs no env vars. The storage layer that uploads the outputs uses `R2_*`.

## How it works

- `adapters/<id>.ts` turns one episode's code into the spec and lists its props (`{ key, file, build() }`).
- `adapters/<id>.inject.mjs` (optional) contains:
  - `real`: the studio modules that actually run. Everything else in `studio/src`, plus React and Remotion, is replaced by `lib/stub.cjs`.
  - `transforms`: bundle-time source transforms that expose values hidden inside component bodies. The S01 camera keys, tracks, shakes, flicker and hull kicks come from `s1_3d.tsx` this way.

  The studio files themselves are never modified.
- esbuild bundles the adapter with exactly one copy of three, so `instanceof` checks hold. Polyfills for `FileReader` and `self` let `GLTFExporter` run headless in Node, with no browser.
- **To add a future episode:** add `adapters/<id>.ts` (and `.inject.mjs` if needed), then run `--episode <id>`.

## Spec semantics (read this before writing a renderer)

**Frames and keys**
- Frames are absolute film frames at 30 fps. A shot covers `[from, to)`.
- Keyframe lists `[[f, v], ...]` are linear between keys and hold outside them. A step is written as two keys on consecutive frames.

**Camera**
- `fov` is the vertical fov in degrees and is interpolated in log space. `roll` is in degrees.
- Each key's `ease` applies to the segment arriving at that key (default `move`). The bezier eases are listed in the schema, and the reference implementation is `studio/src/kit/camrig.ts`.
- `camera.space: "yacht"`:
  - The position follows the yacht's x, z and heading, plus 0.6 × its buoyant heave.
  - The position does not follow pitch or roll.
  - `look` is transformed by the full yacht matrix.
- `handheld`, `drift` and `shakes` reproduce `rigAt()` exactly.

**Yacht**
- Yacht-local axes: +z is the bow, +x is starboard, y is up (metres). `heading = π/2` points the bow along world +x.
- The yacht matrix is `T(x, buoyY - sink, z) · R_euler_YXZ(-(pitchBuoy + pitch), heading, rollBuoy + roll)`. Buoyancy comes from `yachtPose()`.

**Lights and fires**
- The GLBs store the lights-on and fires-at-full values. `yacht.lights` and `fires` (0 to 1) multiply them:
  - Yacht: glass emission 0.32, `cabin_light` 6, nav emissive 4.
  - Each island fire: light 900 and flame emissive strength 1.6.
- Fire flicker per fire `i` at time `t` (seconds):
  - `fl = 0.85 + 0.15·sin(9t + 2i)·sin(3.7t + i)`
  - light = `v·900·fl`
  - flame scale = `(1, 0.6 + 0.4fl, 1)·v`

**Actors**
- `local` is the feet position in yacht space. `height` is the world height in metres (default 1.8).
- Tracks blend in order, and each one crossfades in over `fade` frames.
- `lookAt` aims the head at its target, weighted by `lookWeight`.

**Extensions to the shared contract** (all optional; the validator knows them):
- `version`, `source`
- `audio.offsetFrames`: the narration starts at frame 15.
- On shots:
  - `shot.title`, `shot.scene`, `shot.keyFrame`
  - `shot.island`: a per-shot override; `null` hides the island.
  - `shot.env`: per-shot `moonDir`, `seaState` and `dawn`.
- On cameras:
  - `camera.drift`
  - `camera.handheld` also accepts keys.
- `yacht.hatch`, `pitch`, `roll` and `sink`: each accepts a number or keys.
- `actor.height`, `actor.lookWeight`, `track.offset`

## Outputs (sentinel)

| File | Size | Contents |
|---|---|---|
| `episodes/sentinel/episode.json` | about 29 KB | 11 shots, 32 captions, 2416 frames |
| `studio/public/assets/props/yacht.glb` | 0.36 MB | 56 nodes, 48 meshes, 9.4k tris, 14 materials, 1 light |
| `studio/public/assets/props/island_sentinel.glb` | 14.5 MB | 297 nodes, 0.47M tris, 6 lights |

Both GLBs pass the Khronos glTF validator with 0 errors and 0 warnings.

**Yacht nodes and materials**
- The node `hatch_pivot` (`rotation.x = -hatch·1.9`) and the light `cabin_light`.
- Empties named `anchor_{cockpit,hatch,exhaust,bow,stern}`.
- Materials: `gelcoat_hull` (vertex colours), `gelcoat_white`, `teak`, `glass_cabin`, `steel`, `nav_*`.

**Island nodes**
- `fire_0..5` and `fire_light_0..5`.
- `canopy`: by default it is baked to one mesh with vertex colours, because Blender drops per-instance colours. `--instanced` keeps `EXT_mesh_gpu_instancing` instead, which makes a 0.38 MB file.
- The island is exported at true size (scale 1). The spec's `island.scale` is a uniform scale on it.
