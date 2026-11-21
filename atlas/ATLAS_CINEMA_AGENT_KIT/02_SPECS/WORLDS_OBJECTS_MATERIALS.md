# Scene world building, objects, and physically plausible materials

The world system must compose licensed assets with procedural generators—not try to manually sculpt every object using LLM-generated Python. Build parametric façades/windows/doors/roofs/stairs and street grids; randomized but coherent rule sets based on era, geography and art direction. Geometry Nodes is the major native procedural engine.

## Architecture

Build dimensional modular building presets (residential, townhouse, industrial, art deco, modernist, brutalist, contemporary high-rise) with floors, windows, railings, balconies, ornament, UV and physical metrics. Implement modular room builders and furnishing zones; generative building geometry should pass watertight/penetration checks relevant to shots.

## Scene density

Classify hero / midground / background objects. Hero assets get real detail and appropriate texture resolution; midground uses instancing; background uses simplified LOD. Use shot-camera coverage to spend geometry only where visible. Add subtle details (gutters, wiring, dirt, curb variation, signage, road edges) to avoid sterile CG appearance.

## Material library

Principled BSDF PBR templates with correct map assignment: basecolor=sRGB; roughness/metallic/normal/height=Non-Color. Include layering of micro-surface damage, normal wear, dust, puddles, oil, aging, fabric weave, imperfect glazing, surface variation. Validate normalized texel density and tiling scale; avoid one-size-fits-all procedural noise.

## Objects

Classify products, furniture, tools, electronics, vehicles and set dressing by size, likely era, stylistic vocabulary, physical use. Assets require mesh provenance; use hard-surface procedural primitives only for appropriate shapes; prefer high-quality imported models for distinctive hero props.

## Weather and atmosphere

Volumetric fog, dust and rain via native Blender. Layer weather effects with physically consistent ground and lighting response. Simulations cache once per source hash, then final render worker reads the cache. Don't conflate sky shader with atmospheric scattering.
