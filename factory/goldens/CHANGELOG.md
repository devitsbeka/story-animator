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

## 2026-11-22 - yacht_turnaround, sentinel_A01a, sentinel_B11, sentinel_C13, sentinel_E31, stress_y_bow_point, stress_y_rail_fear, stress_y_radio_shout
yacht_v2 (detailed hull, cabin glazing that reads as glass, nav lights) and the look-dev night lighting replace the box yacht. Reviewed side by side (lead + fix agent): a real improvement. y_radio_shout also gets the authored palm hold of the radio instead of a fist (the stress hand-intent list no longer overrides pose shapes, L031).
- `yacht_turnaround`: re-approved sha256 b7193293cefe, vs previous ssim 0.68715 luma d 0.03026, commit 9b5d3a7ee7
- `sentinel_A01a`: re-approved sha256 9a42ecf819e7, vs previous ssim 0.90332 luma d 0.03484, commit 9b5d3a7ee7
- `sentinel_B11`: re-approved sha256 63730117fa59, vs previous ssim 0.5268 luma d 0.07983, commit 9b5d3a7ee7
- `sentinel_C13`: re-approved sha256 9a5403184941, vs previous ssim 0.47276 luma d 0.00104, commit 9b5d3a7ee7
- `sentinel_E31`: re-approved sha256 10497badd4ce, vs previous ssim 0.52539 luma d 0.06009, commit 9b5d3a7ee7
- `stress_y_bow_point`: re-approved sha256 3ac164b524c8, vs previous ssim 0.86063 luma d 0.05561, commit 9b5d3a7ee7
- `stress_y_rail_fear`: re-approved sha256 fc7d5f197f7d, vs previous ssim 0.88522 luma d 0.05129, commit 9b5d3a7ee7
- `stress_y_radio_shout`: re-approved sha256 40e6e09e14dc, vs previous ssim 0.76122 luma d 0.03835, commit 9b5d3a7ee7

## 2026-11-22 - hero_pose_sheet, sentinel_C21, stress_y_sit_deck, stress_j_sit_log, stress_d_sit_rock_sneeze, stress_s_sit_bench, stress_l009_abandoned_sit
Seated poses (L032): the leg opens out (knee falls out, foot turns out with it) instead of a flat foot pointed past the ankle's range with the knees caved in past the midline; feet on the deck, hands relaxed on the knees, face lighting from the look-dev pass. Better than the ref (hovering splayed hands, sunk feet) and than the merge candidate (knock-kneed). Seated stress cameras still frame Jay chest-up with the sneakers big in the foreground, as before (not changed by this). hero_pose_sheet also shows the relaxed finger cascade and the phone hold.
- `hero_pose_sheet`: re-approved sha256 b9dc205841c7, vs previous ssim 0.97389 luma d 0.00022, commit 9b5d3a7ee7
- `sentinel_C21`: re-approved sha256 a8edc15cc4e0, vs previous ssim 0.30135 luma d 0.29481, commit 9b5d3a7ee7
- `stress_y_sit_deck`: re-approved sha256 2f58d2fb9441, vs previous ssim 0.39579 luma d 0.28078, commit 9b5d3a7ee7
- `stress_j_sit_log`: re-approved sha256 d0e0f15596c4, vs previous ssim 0.74769 luma d 0.02423, commit 9b5d3a7ee7
- `stress_d_sit_rock_sneeze`: re-approved sha256 f95d43cc3e1f, vs previous ssim 0.67324 luma d 0.06822, commit 9b5d3a7ee7
- `stress_s_sit_bench`: re-approved sha256 7420b7e07803, vs previous ssim 0.75783 luma d 0.00679, commit 9b5d3a7ee7
- `stress_l009_abandoned_sit`: re-approved sha256 5ef380574d51, vs previous ssim 0.73056 luma d 0.03332, commit 9b5d3a7ee7

## 2026-11-22 - hero_face_sheet, stress_j_phone, stress_s_beacon, stress_c_radio_mouth, stress_l010_desert_grip, stress_j_shush_close, stress_d_reach
Face polish (converged eyes, lids covering the top of the iris, stronger asymmetric expressions) and the hands polish: props held in the palm per hand_poses.PROP_GRIPS with the authored pose shapes (grip_flat / press / point), no longer overridden by the stress intent list (L031). Neutral to better. j_phone's phone still reads edge-on across the fingers, as in the merge candidate (staging of phone_up, not a regression).
- `hero_face_sheet`: re-approved sha256 e0b682751c81, vs previous ssim 0.97019 luma d 0.00066, commit 9b5d3a7ee7
- `stress_j_phone`: re-approved sha256 ac3038591803, vs previous ssim 0.85134 luma d 0.00852, commit 9b5d3a7ee7
- `stress_s_beacon`: re-approved sha256 5d72c4ac188c, vs previous ssim 0.88778 luma d 0.0028, commit 9b5d3a7ee7
- `stress_c_radio_mouth`: re-approved sha256 4d471281ba94, vs previous ssim 0.82505 luma d 0.0547, commit 9b5d3a7ee7
- `stress_l010_desert_grip`: re-approved sha256 0dc36cf3c9fe, vs previous ssim 0.87208 luma d 0.02409, commit 9b5d3a7ee7
- `stress_j_shush_close`: re-approved sha256 a61d5f21939b, vs previous ssim 0.86412 luma d 0.02849, commit 9b5d3a7ee7
- `stress_d_reach`: re-approved sha256 aafedeb0d214, vs previous ssim 0.90294 luma d 0.01587, commit 9b5d3a7ee7

## 2026-11-22 - kit_abandoned_city_street, kit_desert_canyon, kit_jungle_clearing, kit_snow_mountain_ridge, stress_c_cover_fear, stress_c_doorway_sneeze, stress_d_rope, stress_d_wave, stress_j_kneel, stress_j_walk, stress_s_brace_wide, stress_l022_abandoned_vocab
Look-dev lighting (face key cheat, readable skin) and relaxed hands (palms to the thighs, curled fingers). Neutral to better. j_kneel / l022_abandoned_vocab still use the 'down' fallback with the head at the frame edge (L022 vocab gap, same framing as the ref).
- `kit_abandoned_city_street`: re-approved sha256 ca50eebb5cf8, vs previous ssim 0.88449 luma d 0.02287, commit 9b5d3a7ee7
- `kit_desert_canyon`: re-approved sha256 4f9c7bc5684b, vs previous ssim 0.89057 luma d 0.04414, commit 9b5d3a7ee7
- `kit_jungle_clearing`: re-approved sha256 b3510a91b96a, vs previous ssim 0.97221 luma d 0.0037, commit 9b5d3a7ee7
- `kit_snow_mountain_ridge`: re-approved sha256 cbd04591ad03, vs previous ssim 0.99004 luma d 0.02016, commit 9b5d3a7ee7
- `stress_c_cover_fear`: re-approved sha256 32b151409893, vs previous ssim 0.76992 luma d 0.07046, commit 9b5d3a7ee7
- `stress_c_doorway_sneeze`: re-approved sha256 f7dd9415f36a, vs previous ssim 0.89261 luma d 0.02615, commit 9b5d3a7ee7
- `stress_d_rope`: re-approved sha256 664caf81a160, vs previous ssim 0.88473 luma d 0.03784, commit 9b5d3a7ee7
- `stress_d_wave`: re-approved sha256 c207a3ca3ff6, vs previous ssim 0.96622 luma d 0.0055, commit 9b5d3a7ee7
- `stress_j_kneel`: re-approved sha256 35494ab98766, vs previous ssim 0.84298 luma d 0.02518, commit 9b5d3a7ee7
- `stress_j_walk`: re-approved sha256 6a3853dc1215, vs previous ssim 0.97229 luma d 0.0025, commit 9b5d3a7ee7
- `stress_s_brace_wide`: re-approved sha256 20b25e97cdfb, vs previous ssim 0.98031 luma d 0.02727, commit 9b5d3a7ee7
- `stress_l022_abandoned_vocab`: re-approved sha256 d6c8a643a0e9, vs previous ssim 0.83118 luma d 0.03931, commit 9b5d3a7ee7
