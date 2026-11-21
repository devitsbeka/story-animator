# Premium-grade asset pipeline

1. **Source discovery:** official APIs for open libraries; authorized file import for commercial marketplace purchases; optional login-based integrations only with documented provider support.
2. **License and entitlements:** classify CC0 vs royalty-free licensed vs editorial-only vs restricted; record original URL, capture evidence, user account entitlement, embedded-use rights, attribution and redistributability. Source .blend files are private by default.
3. **Ingestion:** rate limit, retry/backoff, checksum verification, archive sanitation and extension allowlist, quarantine untrusted blend/scripts; malware scans where available.
4. **Normalization:** metric units, axes, pivot/origin, transforms, bounding box, collider hints, mesh validity, PBR semantic maps, color space (sRGB color; Non-Color data), relink textures, Blender asset conversion.
5. **Search:** unified taxonomy, keyword + vector embeddings + filters for style, era, dimensions, quality, license, availability and polygon size.
6. **LOD:** preserve originals and 3 optimized versions; material variants, thumbnails, proxy cards, texture footprints. Instancing and linkable libraries for performance.
7. **Preflight:** all dependencies available in worker cache; no external URLs required during render; verify license and usage; asset preview renders.
8. **Curation:** quality score from actual geometry/texture/visual inspection; duplicates via hash plus similarity, not merely filename.

## Inventory priorities

A) architecture: modular walls, façades, windows, doors, doorsets, rooftops, stairs, streets, intersections, signage, historic architectural motifs. B) vehicles: period cars, contemporary cars, trains, motorcycles, industrial, road props. C) furniture: sofas, lights, office furniture, kitchens, period-specific pieces. D) vegetation/terrain: trees, bushes, rocks, debris, grass. E) humans: licensed photorealistic characters, clothing and realistic animation. F) studio: HDRIs, calibrated lighting rigs, professional cameras. G) materials: concrete, masonry, plaster, stone, wood, metal, glass, fabric, skin, hair, wetness, imperfections.

## Conservative acquisition workflow

Start indexing metadata; fetch only selected, approved open assets with a per-source bandwidth/size cap. Store catalog entries for premium sources with purchase/manual-import status. Never treat a vendor signup as blanket access to paid objects. Schedule tests for every plugin version; failures disable that adapter while native Blender keeps working.
