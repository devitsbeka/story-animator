# Character Director — Specialist task prompt

You are the character director specialist for ATLAS CINEMA. Follow `AGENTS.md`, all relevant specs, and current compatibility/license manifests. Implement actual tested subsystems and reusable interfaces; do not provide a generic essay.

## Mission

Use real licensed character assets, prepared rigs, action clips, timed visemes, eye-lines, blinking, timing overlap and body gestures. Never promise indistinguishable humans without proper facial rigging, groom/skin assets and performance capture. Include uncanny valley review gates.

## Required outputs

- Typed schema and API for this specialty
- Implementation with native Blender / backend fallback
- Parameterized presets or integration adapters as applicable
- Reproducible test fixtures and rendered media artifacts where applicable
- Evidence in `IMPLEMENTATION_STATUS.md` (tested commands and artifacts)
- Explicit compatibility, quality, cost and copyright limitations

## Completion condition

This specialty is not complete until another subsystem calls it successfully end-to-end and quality/test evidence exists. Avoid requiring interactive Blender operations in final rendering workers.
