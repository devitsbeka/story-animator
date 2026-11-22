# factory/run: the one command

`factory/run` takes one idea and drives it through every factory stage to a QC-checked episode. Each stage writes its artifact under `episodes/<id>/`. The state of the run (each stage's status, artifacts, cost and time, the approval and the QC history) lives in `episodes/<id>/run.json`.

```bash
python -m factory.run "Solo sailor's yacht runs aground on North Sentinel's reef at night: what do you actually do?" \
    --format short --style pixar_night_survival --render local --quality preview
# the run pauses at the approval gate (exit code 3). Review the boards, then:
python -m factory.run approve --episode-id <id> [--note "..."]      # or --reject
python -m factory.run --resume --episode-id <id>
python -m factory.run status --episode-id <id> [--json]

# N ideas at once, under one budget ceiling
python -m factory.run batch ideas.txt --max-parallel 4 --budget 60 --render farm --quality final

# CI / offline: recorded LLM responses, the reference VO, and stubs for the heavy steps
python -m factory.run "<idea>" --offline --stub previs,render,finish --auto-approve
```

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | QC said PUBLISH |
| 3 | awaiting approval |
| 4 | QC returned the episode (RETURN) |
| 5 | budget exceeded |
| 1 | a stage failed |
| 2 | usage error |

## The DAG

```
develop(1) ──► breakdown(2) ──► library(3) ──┐
    └────────► voice(5a) ────────────────────┴─► direct(4) ──► previs(6) [APPROVAL GATE] ──► render(7) ──┐
                  └──────────────────────────────────┴────────► sound(5b) ─────────────────────────────┴─► finish(8) ──► qc(9)
```

| Stage | What runs | Artifacts |
|---|---|---|
| 1-4 develop, breakdown, library, direct | `factory.director` Runner (Claude API, or `FixtureClient` with `--offline`); stage 4 compiles `episode.json`. The orchestrator then sets `episode.id` to the run id and points `episode.audio` at this run's narration. | `story.json`, `breakdown.json`, `manifest.json`, `shotplan.json`, `episode.json`, `reports/`, `_llm/` |
| 5a voice | `factory.voice.synthesize(story_json, out_dir) -> {audio, words}` when that module exists and the run is online. With `--offline`, the reference narration `episodes/<story.id>/audio/` is used if it exists (Sentinel). Otherwise a stub: speech-like noise, with word timings laid out inside each line's `t0`..`t1`. | `audio/narration.*`, `audio/narration.words.json` |
| 5b sound | `factory.sound.designer.design`, then `factory.sound.mixer.mix` and sound QC. With `--stub mix`, the narration is loudness-normalised instead. | `sound.json`, `audio/mix_v1.m4a`, `audio/mix_v1.report.json` |
| 6 previs | One keyframe per shot (`keyFrame`, or the shot's middle frame) through `render_episode.py` at 144x256, 4 spp. Then a labelled contact sheet and an animatic: each keyframe held for its shot's length, narration underneath. | `boards/keys/<shot>/####.png`, `boards/contact_sheet.png`, `boards/animatic.mp4`, `boards/previs.json` |
| gate | Status becomes `awaiting_approval` until `approve` is run, unless `--auto-approve` is given. | `run.json.approval` |
| 7 render | **local:** `cloud/farm/jobs.py` splits the episode into jobs, and `render_episode.py --skip-existing` runs each one, with `--workers N` processes. **farm:** `cloud/farm/orchestrator.py` `Farm.submit` → `tick` until RENDERED → `pull_plates`. The farm run id is saved in `run.json` as soon as it is submitted, so `--resume` keeps watching that run and does not submit again. | `plates/<shot>/####.png`, or `episodes/<id>/runs/<run>/plates` |
| 8 finish | `factory/finish/make_plates_manifest.py --stage`, then `npx remotion render src/index.ts Finish` in `$FACTORY_STUDIO` (default `studio/`, which needs `node_modules`). With `--stub finish`, the same manifest step runs and ffmpeg then joins the plates and the mix (no captions). | `final/episode.mp4` |
| 9 qc | `factory.qc.report.run` (no vision model with `--offline`), plus the retry loop below. | `qc/report.json`, `qc/report.iter<N>.json` |

The 5a and 4 numbers keep the architecture's names, but voice runs **before** direct. Voice only needs `story.json`, so it runs in parallel with breakdown and library, and stage 4 gets the real word timings for its cut-on-word check (P-3).

Stages whose dependencies are done run at the same time (`--parallel-stages`, default 2). For example, sound runs alongside previs and render.

### Resuming

- `--resume` skips every stage that is `done` and whose artifacts still exist on disk. A stage that failed, or that was `running` when the process died, runs again.
- The director stages also reuse their own valid artifacts.
- On resume, the options the run started with are read back from `run.json`. Flags given on the command line override them.
- `--from-stage X` resets X and everything downstream of it.
- `--fresh` regenerates everything.

### The QC retry loop

| Decision | What the orchestrator does |
|---|---|
| PUBLISH | Run status `published`. |
| RETURN | Stop. `run.json.qc.returnReport` lists the hard failures, the failing rules and where to go next. Run status `returned`. |
| AUTO_FIX | Fixed **once** (`max_qc_fixes`). `plan_fix` reads the failing rules (see below). After the fix: finish runs again, then QC runs again with `iteration=1`. If the result is still not PUBLISH, the run is `returned`. |
| INCOMPLETE | Treated as `returned`. |

How `plan_fix` chooses what to re-run:

- **TECH-only failures:** stage 7 re-renders only the failing shots. Their plate dirs are deleted first.
- **Failures in a scored section, or FRAMING:** stage 4 runs again with `qc_feedback.json` (the failing rules) added to its inputs. Then stage 7 re-renders the failing shots plus every shot whose spec changed.

Failing shots are found by matching shot ids inside the failing rules' `measured`, `detail` and `expected` fields, and in the failing per-shot framing rows.

## Canon gate

`python3 -m factory.canon pass` (the film-craft canon, `.claude/skills/film-craft-canon/SKILL.md`) runs twice in every
run, and any FAIL blocks:

- **before the previs approval** (`Pipeline.canon_gate("plan")`, in stage 6 after the boards are made): the stage fails
  with `CanonFailed` and the report lands in `qc/canon_report.plan.json`;
- **before publishing** (`canon_gate("publish")`, in stage 9): a PUBLISH decision becomes RETURN. At this stage an
  unapproved or stale look-dev test FAILs CAN-T1a; approving the previs boards approves the look-dev test (its hash is
  stamped into `shotplan.json` when stage 7 starts).

`FACTORY_CANON_GATE=0` disables the gate (legacy episodes); `FACTORY_CANON=0` removes the canon from the director's
retry loop. **Merge gate:** `tools/merge_gate.sh` is not on this branch yet; when it lands it should run, for every
episode the branch touches, `python3 -m factory.canon pass --episode episodes/<id> --stage plan` and fail on a non-zero
exit, plus `python3 -m pytest tests/canon`.

## Cost and time

Every stage records `seconds` and `costUSD`. Totals are kept in `run.json.cost` and `run.json.time`. Stages that run again inside the QC loop add to their totals.

| Cost | How it is computed |
|---|---|
| LLM | Token usage from the director's `reports/<stage>.<n>.json` meta, at list price. claude-opus-5-5: $4 / $20 / $0.20 per MTok for input, output and cache reads; cache writes assumed at 1.25x input. |
| Voice | Characters x $/1k characters (estimate). |
| Farm | The farm run's `spentUsd`. |
| Local render | $0; only the time is recorded. |

Override the prices with `FACTORY_PRICES_JSON` (see `costs.py`). The defaults are estimates, not bills.

**Budget**

- `--budget USD` is checked before every stage, and the remaining amount is passed to the farm as its submit ceiling.
- If spending passes the budget, the run stops with status `budget_exceeded`.

**Batch**

- `batch` runs every idea as its own `python -m factory.run` process, at most `--max-parallel` at a time.
- An idea starts only if `spent(finished) + allowance(running) + estimate(idea) <= budget`.
- Each idea gets `--budget = min(remaining, estimate x --overrun)`.
- An idea that does not fit waits. It is retried each time another idea finishes, and is left as `budget_refused` if room never opens up.
- The batch report is written to `episodes/batch_<timestamp>.json`.
- Each line of `ideas.txt` is one idea. Blank lines and `#` comments are skipped. An optional `short|` or `docuseries|` prefix sets the format for that idea.

## Stubs (`--stub`)

| Stub | What it does |
|---|---|
| `voice` | Synthetic narration and timings. |
| `mix` | Normalised narration instead of the full ffmpeg mix. |
| `previs` | Drawn keyframe cards instead of Blender. |
| `render` | 108x192 placeholder plates: the previs keyframe with a slow push-in. |
| `finish` | ffmpeg join instead of Remotion. |

`--stub all` turns on all five. Stubs let the whole chain run in CI time.

## Quality gate (lessons, regress, delivery, ceilings)

- **per-shot gate**: before previs and before render, `factory/direction/shot_checks.py` checks EVERY shot (head
  framing with the rig's head metrics, eye band on close-ups, camera collision, hero visible; TIER at final quality).
  Failing shots are sent back to stage 4 with the failing rules as feedback (max 2 tries, `run.json.shotGate`), then
  the run blocks (enforce) or records (warn).
- **regress** (`--regress enforce|warn|off`, default enforce): before the previs approval gate and again before
  publish, `factory/lessons/regress.py` runs the episode-level lesson rules on `episode.json` (PROXY: camera inside
  yacht/prop geometry blocks; TIER: assets near the camera must be tier hero - warns, blocks at publish with
  `--quality final`), runs the **film-craft canon pass** (`python3 -m factory.canon pass`, report in
  `qc/canon_<gate>.json`; any canon rule FAIL blocks, MANUAL rules are listed for the human approval; at publish it
  also gets the plates and the final video; `FACTORY_CANON=0` disables it for debugging), records the lessons
  status and stale goldens in `run.json.regress`. Blocked previs fails the stage; blocked publish turns PUBLISH into
  RETURN.
- **delivery** (`--no-deliver` to skip): PUBLISH runs `factory/deliver.py` -> `final/delivery/episode.mp4` +
  `episode_mobile.mp4` (H.264 High, yuv420p, faststart, 1 s GOP, capped bitrate), or the stage fails (L006).
- **cost ceilings**: `costs.STAGE_CEILINGS_USD` (override `FACTORY_STAGE_CEILINGS_JSON`) per stage; over the ceiling the
  run stops with `budget_exceeded` and that stage is never started again; >= 2 attempts add an alert (L014).
- **no silent render failures**: a missing plate fails render; a missing previs keyframe fails previs (L012).

See `factory/lessons/README.md` for the whole loop and `tools/merge_gate.sh` for the merge gate.

## Tests

```bash
python -m pytest tests/run -q                               # about 4 min
RUN_BLENDER_SMOKE=1 python -m pytest tests/run -k real_previs -s   # real Blender: 2 previs keyframes at 72x128 (~3.5 min)
```

**`test_offline_sentinel_chain_cli_then_resume`** is the main end-to-end test. It runs the full Sentinel chain through the CLI with `--offline`, the real sound designer and mixer, the real QC, and stubbed previs, render and finish. It then checks every artifact, `run.json` and the cost/time fields, and that `--resume` re-runs nothing.

The other tests cover:
- the approval gate
- the AUTO_FIX re-render, limited to the failing shot
- AUTO_FIX tried once, then RETURN
- RETURN
- the budget stop
- failure, then resume
- `--from-stage`
- local render sharding through `tests/farm/fake_blender.py`
- farm submit, watch and pull, including the farm path through the pipeline, using a fake Farm
- the voice-module interface and the stub voice
- batch concurrency, and budget admission (the second idea waits for the first)
