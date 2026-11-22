# Lessons: every mistake becomes a permanent check

`lessons.yaml` is the ledger of every defect found so far: symptom, root cause, the rule that prevents it, the check
that enforces the rule, the gates where it runs, and a status (`open` / `partially-closed` / `closed`).

## The loop

```
user / QC / review finds a defect
   -> python -m factory.lessons add --symptom "..." --root-cause "..." --rule "..." --gate direct,qc     (status open)
   -> implement the check (a test that FAILS on the original defect) and register it in factory/lessons/checks.py
   -> wire it into a gate (shot_validator / QC / factory/run regress / goldens / merge gate)
   -> python -m factory.lessons close L0NN --check "what enforces it"
   -> tools/merge_gate.sh enforces it on every branch, forever
```

The rule text is injected automatically where work is planned, so nobody repeats a known mistake:
- **director prompts** (`factory/director/prompts.py`): a `LESSONS` block with the open + closed rules of the stage's
  gates (develop: develop; breakdown: develop, library; direct: direct, library, asset);
- **agent briefs**: the common brief templates (`factory/briefs/_common_*.md`) carry a generated `LESSONS` block;
  refresh with `python -m factory.lessons inject-briefs` (the merge gate fails if they are stale).

## Commands

| | |
|---|---|
| `python -m factory.lessons add ...` | append a lesson (next id, status open; comments in the YAML survive) |
| `python -m factory.lessons list [--gate G] [--open] [--block]` | the ledger, or the prompt block |
| `python -m factory.lessons status` | which lessons have a working check, which are open |
| `python -m factory.lessons check [--slow] [--only L006]` | run the checks (fast = pytest/cmd; `--slow` adds Blender + goldens) |
| `python -m factory.lessons close L0NN [--status partially-closed] --check "..."` | update the ledger |

## Where the checks run

| Gate | What runs |
|---|---|
| direct / previs | `shot_validator.py` (C-rules + **TIER** L008 + **PROXY** L012); `factory/run` **regress** check before the approval gate (blocks on PROXY; warns on TIER and stale goldens) |
| render | `render.py` / previs fail on any missing plate; Blender runs with `--python-exit-code 1` (L012) |
| qc / publish | QC report carries `details.lessons` and a DELIVERY section; on PUBLISH the regress check runs again (TIER blocks in final quality) and `factory/deliver.py` writes the final + mobile copies or refuses (L006) |
| run | per-stage cost ceilings stop the run; >= 2 attempts raise an alert (L014) |
| merge | `tools/merge_gate.sh <branch>`: pytest (per directory), lesson checks, validator + lighting (no new failures vs base), golden regression for affected goldens |

## Golden frames (`factory/goldens/`)

Canonical renders (hero turnaround / pose sheet / face sheet, yacht turnaround, 6 Sentinel keyframes, 4 world-kit
keyframes) are defined as recipes in `manifest.json` (360x640, Cycles CPU, 8 samples, seed 0, 2 threads). References
live in the gitignored store `<library_store>/goldens/refs/<id>/<sha256>.png`; `baseline.json` (in git) pins each
reference's sha256, metrics and the hash of the inputs it was rendered from.

```bash
python -m factory.goldens compare --changed-from <base>   # render + compare affected goldens; FAIL beyond thresholds; diff sheet
python -m factory.goldens approve --only hero_pose_sheet --note "hands now curl (polish sprint)"   # intended improvement
python -m factory.goldens status                           # fresh / stale per golden
```

Compare = SSIM (11-tap Gaussian, numpy) global + worst tile, mean colour / luminance deltas, edge-density change,
per-golden thresholds. With `ANTHROPIC_API_KEY` (env or `~/.factory_secrets.env`) a vision reviewer judges each
changed golden "better / same / worse" on its rubric; `approve` refuses a "worse" unless a human passes
`--accept-worse`, and `--auto-approve-better` never approves anything but "better". Every approval is logged in
`factory/goldens/CHANGELOG.md`.

## Fixes must scale: the scenario stress suite (`factory/goldens/stress/`)

A fix that only makes Sentinel look right is not a fix. `generator.py` builds, in code and seeded, one-shot scenarios
crossing **stance x hand use x world kit x shot size x emotion** (stand, brace, helm, sit on deck/log/rock/bench,
kneel, crouch, walk; relaxed, wheel, radio, phone, beacon, rail, point, wave, shush, reach, rope, hands up; all five
worlds; wide/medium/close; neutral, fear, shout, relief, determined, sneeze) into `stress_episode.json`. The camera
of every scenario is planned from the rig's head metrics and moved to a collision-free side.

`python -m factory.goldens stress [--vision]` runs on every scenario: the per-shot checks (FRAME-CROP, FRAME-EYES,
COLLIDE, VIS), VOCAB (does the renderer have the stance/hand use), Blender pose QC over the 2 s clip (seat contact,
spine, finger curl, wrist bend, palm normal, grip contact, FACE-LIFE = no frozen face > 0.5 s), the stress goldens
(`stress_<id>`, 360x640) and optionally the vision rubric (HANDS-1, FACE-2, FACE-3, FRAME-1). It FAILS on any failure
not recorded in `known_failures.json` - where every entry is owned by an open lesson - and lists known failures that
now pass (prune them when a fix lands: `--update-known --note ...`). The merge gate runs it on every branch.

**Regression cases.** Every lesson carries `regression_cases`: `lessons add` derives a stress selector from the
symptom (or takes `--case "stance=sit*,hands=radio|phone,size=close"`), writes it to `stress/cases.json`, and the
generator expands it to one scenario per world kit (reusing a matching base scenario), so the defect class is tested
in every world and pose, not only where it was first seen. `lessons attach-case L0NN --case ...` adds one later.

**Per-shot gate in the orchestrator.** `factory/run` runs the same per-shot checks on every shot of every episode
before previs and before render; failing shots go back to stage 4 with the failing rules as feedback (max 2 tries),
then the run blocks (`--regress enforce`, the default).

## Pose QC (L009 / L010)

`blender -b -P cloud/blender/test/pose_qc.py -- --spec <episode> [--shots ...] --out pose.json [--strict]` bakes each
hero shot through the production adapter and checks seat contact, spine pitch per stance, finger curl and grip
contact (`cloud/blender/pose_rules.py`). It is a slow lesson check (`check --slow`); not yet wired into previs.
