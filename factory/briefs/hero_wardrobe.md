# Brief: hero_wardrobe (turn Jay into the series hero asset)
(Read /home/user/story-animator/factory/briefs/_common_hero.md first.)
Goal: a production hero asset built by a reproducible script from jay.blend: factory/characters/build_hero_jay.py -> /home/user/story-animator/library_store/characters/hero_v4/hero_v4.blend.
Wardrobe/style (the series identity, keep it tasteful and Pixar-appealing):
- Oversized BLACK hoodie with the word "PALENCIAGA" printed across the chest (white, bold condensed sans, slightly worn print). Reuse/modify Jay's jacket mesh (GEO-jay_jacket, has shape keys) or build a hoodie that is skinned to the same deform bones (data-transfer weights from the body) — it must deform correctly with the rig in extreme poses (arms up, sit, crouch). Black cotton material with sheen and fabric weave; drawstrings white.
- BLACK baseball cap replacing Jay's bucket hat (built in code, parented/weighted to the head control so it follows head motion; brim forward; small subtle logo or none).
- Remove the glasses and the chain/necklace (hide/delete cleanly, no orphan drivers breaking).
- Bottoms: black joggers (recolor/restyle the shorts or extend), keep white sneakers.
- Keep the face, eyes, eyelids, brows rig intact and working.
Deliverables: the build script (idempotent), the saved .blend, a turnaround render sheet (front, 3/4, side, back) and 4 extreme-pose checks (arms raised, crouch/sit, twist, reach forward) proving the clothes deform; catalog entry 'int:hero_v4' (provider internal derived from CC-BY Blender Studio Jay; licence CC-BY-4.0 with attribution text) in factory/library/catalog.json; CREDITS.md line.
To pose for the checks, key the CloudRig IK/FK controls directly (inspect bone names in RIG-jay: e.g. IK-*/FK-*/MSTR-*/ROOT/TORSO etc.).
