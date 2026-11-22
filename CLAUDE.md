# Project rules (story-animator / episode factory)

This repo is an automated, code-driven film factory (see `factory/ARCHITECTURE.md`). Read these rules before any work.

1. **Craft canon is mandatory.** Any task that touches story, narration, shots, camera, acting or face, lighting, sound, previs, render settings, or a review of frames/clips **must invoke the `film-craft-canon` skill** and run its pass (`python3 -m factory.canon pass ...`). Report the pass result before calling the work done. Founding sources: `factory/canon/SOURCES.md`.
2. **Never repeat a past mistake.** `factory/lessons/lessons.yaml` lists every defect found so far, with its rule and check. Fixes go into the engines, never into one episode. Every new defect becomes a lesson, a check and stress scenarios (`factory/lessons/README.md`).
3. **No regressions.** Merge only through `tools/merge_gate.sh <branch>` (tests, lessons checks, goldens and stress scenarios). An improved golden becomes the new bar only through an explicit `python -m factory.goldens approve` with a note.
4. **Quality bar:** Pixar or Netflix-level appeal. Judge on rendered frames at 540×960 or higher, never on code alone. The hero is always dead centre. Camera motion is continuous. Captions stay readable and inside the safe area.
5. **Secrets** live only in `~/.factory_secrets.env` or in network secrets injected by the proxy. Never commit, print or paste them.
6. **Commit and push** to the session branch after meaningful changes. Rendered plates and `library_store/` stay out of git (they live in S3).
