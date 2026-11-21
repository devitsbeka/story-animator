# Fill the library with usable assets

## Bootstrap catalog (zero commercial asset purchases)

1. Query Poly Haven public `/assets`, persist metadata with User-Agent and links/credit where required by live API terms.
2. Query ambientCG v3 `/assets`, persist metadata, category and download option info (confirm current response schema).
3. Build source adapters that select the *correct* available downloads from official metadata, not guessed filenames/URLs.
4. Cap storage and bandwidth initially (e.g. 25 GB demo), download selected assets, check hashes and dependencies, normalize files, generate previews and QA.
5. Build curated themed packs: 1920s European street, contemporary urban, cozy workspace, studio product table, forest, cinematic dark interiors. Avoid asserting available assets fit an era that source catalogs don't actually contain.
6. Add approved commercial files from owner-controlled upload folders; preserve entitlement and terms. Never attach vendor download cookies/sessions to GPU jobs.

## Stocking strategy

Prioritize reusable modular packs: windows, façades, doors, sidewalks, streetlights, hero furniture, metals, glass, wood, concrete, signage, rocks, trees, HDRIs. Target 3D real-time screen coverage and art direction over arbitrary counts. Index first; fetch on demand after approval, then cache.

## Verification

A search result must link to an actual catalog entry. An asset tagged 'downloaded' must exist, match hash, have all textures, have an approved license, be Blender-loadable and have a real preview. Import must not open external network access in isolated render worker. Generate per-asset reports.
