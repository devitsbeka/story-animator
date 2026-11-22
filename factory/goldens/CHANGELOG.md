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

## 2026-11-22 - stress_y_helm_wheel, stress_y_radio_shout, stress_y_sit_deck, stress_y_rail_fear, stress_y_bow_point, stress_j_sit_log, stress_j_shush_close, stress_j_phone, stress_j_kneel, stress_j_walk, stress_d_wave, stress_d_sit_rock_sneeze, stress_d_reach, stress_d_rope, stress_s_brace_wide, stress_s_sit_bench, stress_s_beacon, stress_s_crouch_close, stress_c_radio_mouth, stress_c_cover_fear, stress_c_hands_up, stress_c_doorway_sneeze, stress_l009_abandoned_sit, stress_l010_desert_grip, stress_l022_sea_vocab, stress_l022_abandoned_vocab
stress suite baseline (quality_gate): generated scenarios rendered at 360x640/8spp from the merged lead state; they show today's open defects (flat fingers L010/L017, palms turned back L017, seated hover L009, missing kneel/crouch/walk vocab L022) and must be re-approved as those fixes land
- `stress_y_helm_wheel`: initial reference sha256 3548d4e1087d, commit 242050a7e5
- `stress_y_radio_shout`: initial reference sha256 2f4c98edaad9, commit 242050a7e5
- `stress_y_sit_deck`: initial reference sha256 68e99527d103, commit 242050a7e5
- `stress_y_rail_fear`: initial reference sha256 2ef2c0702a99, commit 242050a7e5
- `stress_y_bow_point`: initial reference sha256 937b544f0b5f, commit 242050a7e5
- `stress_j_sit_log`: initial reference sha256 472b1501c21e, commit 242050a7e5
- `stress_j_shush_close`: initial reference sha256 34d5f1a169f7, commit 242050a7e5
- `stress_j_phone`: initial reference sha256 dcec08afa94f, commit 242050a7e5
- `stress_j_kneel`: initial reference sha256 ba233d217056, commit 242050a7e5
- `stress_j_walk`: initial reference sha256 32a13bacdb71, commit 242050a7e5
- `stress_d_wave`: initial reference sha256 93df00ef2a1a, commit 242050a7e5
- `stress_d_sit_rock_sneeze`: initial reference sha256 1fe0fdc89d43, commit 242050a7e5
- `stress_d_reach`: initial reference sha256 b8b2065eada5, commit 242050a7e5
- `stress_d_rope`: initial reference sha256 a11cd0bf182b, commit 242050a7e5
- `stress_s_brace_wide`: initial reference sha256 6a475c258232, commit 242050a7e5
- `stress_s_sit_bench`: initial reference sha256 18e830dd0da5, commit 242050a7e5
- `stress_s_beacon`: initial reference sha256 e321fe02721d, commit 242050a7e5
- `stress_s_crouch_close`: initial reference sha256 d132d66bb158, commit 242050a7e5
- `stress_c_radio_mouth`: initial reference sha256 b29455d39562, commit 242050a7e5
- `stress_c_cover_fear`: initial reference sha256 c126d35d7bed, commit 242050a7e5
- `stress_c_hands_up`: initial reference sha256 edc6e59a343b, commit 242050a7e5
- `stress_c_doorway_sneeze`: initial reference sha256 624bf5b1c985, commit 242050a7e5
- `stress_l009_abandoned_sit`: initial reference sha256 1e60632770b4, commit 242050a7e5
- `stress_l010_desert_grip`: initial reference sha256 fec1c69754a8, commit 242050a7e5
- `stress_l022_sea_vocab`: initial reference sha256 3c428965139d, commit 242050a7e5
- `stress_l022_abandoned_vocab`: initial reference sha256 87b8d94fd420, commit 242050a7e5
