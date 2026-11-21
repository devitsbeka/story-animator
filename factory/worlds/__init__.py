"""World kits: reusable sets the director can stage any idea in (see factory/worlds/kit.schema.json).

  kits.py    registry + validation (schema, library provenance, builders, lighting preset, marks/zones)
  layout.py  pure-python, deterministic build plan (terrain heights, scatter, pieces, marks on the ground)
  match.py   librarian side: breakdown location -> REUSE a kit, or a BUILD proposal for a new kit
  kits/      the kits themselves (JSON)

The Blender half is cloud/blender/set_assembly.py (render_episode.py builds a shot with "set": {...} through it).
CLI:  python -m factory.worlds list | validate [ids] | layout <id> [--seed N]
"""
