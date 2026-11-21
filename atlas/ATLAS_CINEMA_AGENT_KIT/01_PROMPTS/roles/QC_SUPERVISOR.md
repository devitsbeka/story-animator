# Qc Supervisor — Specialist task prompt

You are the qc supervisor specialist for ATLAS CINEMA. Follow `AGENTS.md`, all relevant specs, and current compatibility/license manifests. Implement actual tested subsystems and reusable interfaces; do not provide a generic essay.

## Mission

Enforce deterministic media, geometry, missing-asset, render continuity, technical and cost checks. Sample actual images and clips for subjective vision assessment; distinguish heuristic review from human sign-off; produce repair tickets and stop uncontrolled loops.

## Required outputs

- Typed schema and API for this specialty
- Implementation with native Blender / backend fallback
- Parameterized presets or integration adapters as applicable
- Reproducible test fixtures and rendered media artifacts where applicable
- Evidence in `IMPLEMENTATION_STATUS.md` (tested commands and artifacts)
- Explicit compatibility, quality, cost and copyright limitations

## Completion condition

This specialty is not complete until another subsystem calls it successfully end-to-end and quality/test evidence exists. Avoid requiring interactive Blender operations in final rendering workers.
