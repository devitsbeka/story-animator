# Golden references changelog

Every `python -m factory.goldens approve` appends an entry (why, per-golden sha256, metrics vs the previous reference, vision verdict). References live in <library_store>/goldens/refs/<id>/<sha256>.png; baseline.json pins them.

## 2026-11-22 - hero_face_sheet, hero_pose_sheet, hero_turnaround, kit_abandoned_city_street, kit_desert_canyon, kit_jungle_clearing, kit_snow_mountain_ridge, sentinel_A01a, sentinel_A02, sentinel_B11, sentinel_C13, sentinel_C21, sentinel_E31, yacht_turnaround
Initial baseline rendered from the current lead branch (claude/nice-tesla-xwtpsi @ 6253651: hero_v4 Jay rig with unposed flat fingers and the lean-back sit, box-built yacht, v5 cameras incl. A02 inside the cabin). These are NOT quality targets: the polish sprint (yacht detail, hands/pose, face, look-dev, camera) will intentionally improve several goldens and must re-render them and 'python -m factory.goldens approve --only <ids> --note ...' with a note per change. sentinel D23-D26 (set 'primrose') currently fail to render (unknown world kit 'primrose'), so E31 stands in; kit_snow_mountain_ridge uses the curated library (the full fir scatter OOMs the 15 GB cgroup).
- `hero_face_sheet`: initial reference sha256 d5c25e9b504a, commit 6253651bdb
- `hero_pose_sheet`: initial reference sha256 8be9ee32a2e0, commit 6253651bdb
- `hero_turnaround`: initial reference sha256 5e8702a3a643, commit 6253651bdb
- `kit_abandoned_city_street`: initial reference sha256 b48c403ee9ad, commit 6253651bdb
- `kit_desert_canyon`: initial reference sha256 64d2cddbf2fa, commit 6253651bdb
- `kit_jungle_clearing`: initial reference sha256 68fdf211b54c, commit 6253651bdb
- `kit_snow_mountain_ridge`: initial reference sha256 9e33bc95e792, commit 6253651bdb
- `sentinel_A01a`: initial reference sha256 e814345f7768, commit 6253651bdb
- `sentinel_A02`: initial reference sha256 ed6e032fcdb6, commit 6253651bdb
- `sentinel_B11`: initial reference sha256 f7fa12e17cfe, commit 6253651bdb
- `sentinel_C13`: initial reference sha256 77a5cf7ef75c, commit 6253651bdb
- `sentinel_C21`: initial reference sha256 64fbccffc850, commit 6253651bdb
- `sentinel_E31`: initial reference sha256 19300005b9f9, commit 6253651bdb
- `yacht_turnaround`: initial reference sha256 a392dbc1ac5d, commit 6253651bdb
