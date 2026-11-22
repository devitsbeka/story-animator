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

## Pose QC (L009 / L010)

`blender -b -P cloud/blender/test/pose_qc.py -- --spec <episode> [--shots ...] --out pose.json [--strict]` bakes each
hero shot through the production adapter and checks seat contact, spine pitch per stance, finger curl and grip
contact (`cloud/blender/pose_rules.py`). It is a slow lesson check (`check --slow`); not yet wired into previs.
