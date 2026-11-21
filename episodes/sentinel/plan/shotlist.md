# Sentinel: director's shot list v2

The rule: every shot shows exactly what the voiceover is saying at that moment, and the hero always does something motivated by the line.
- Cuts land on VO beats (premium short-form cuts; it is not one long take). Every shot still has a continuous camera move.
- Hero dead centre in every hero shot. Insert shots (radio, beacon, switch) centre the object instead.
- Frames are at 30 fps and include the 15-frame audio offset.

Legend:
- Size: ECU (extreme close-up), CU (close-up), MCU (medium close-up), MS (medium shot), WS (wide shot), EWS (extreme wide shot), OTS (over the shoulder), POV (point of view).
- Clip: the motion clip the hero plays. A **new** clip has to be generated on the hero rig.
- Prop: a model needed beyond the yacht, island and hero.

## ACT 1: Setup (0–23 s)

| # | Frames | VO | Picture | Size / camera | Hero action (clip) | Props / FX |
|---|---|---|---|---|---|---|
| 1 | 15–75 | "You're alone on a yacht…" | Calm moonlit sea, the yacht small and dead centre, cabin lights warm. Nobody else to the horizon. | EWS, slow crane-down from 40 m | at the helm, steering (**helm_idle**) | yacht lights ON |
| 2 | 75–118 | "…in the middle of the night…" | Hero at the wheel, relaxed, moon behind. | MS, slow push-in from the stern quarter | **helm_idle** → glances at the gauges | cabin glow, moon |
| 3 | 118–150 | "…and your engine just DIED." | Engine sputters: two black smoke puffs from the stern exhaust, the boat lurches. | MCU, crash zoom on the face | **startle**, head turns back toward the engine | smoke puffs, light flicker |
| 4 | 158–226 | "No lights. No power. Nothing." | Cabin lights die in 3 steps on "No / lights / power". The hero flips a dead switch twice and nothing happens. | CU on the switch panel, then tilt up to his face lit only by the moon | **flip_switch_fail** (new) | switch panel, lights OFF |
| 5 | 241–330 | "And the current is dragging you…" | Boat drifting sideways; the wake/foam shows the current pulling. | WS, rising crane to overhead | **look_around_worried** (new), at the rail | current streaks on the water |
| 6 | 330–400 | "…toward the ONE island on Earth you are not allowed to touch." | Overhead becomes a map view: boat dot, cobalt drift line curving to the island; a red protected-zone ring draws on. | Top-down, continuing the rise | (map) | Remotion map overlay on the Blender plate |
| 7 | 404–445 | "North Sentinel Island!" | Island fills the frame from offshore: dark jungle, reef foam ring. Title card. | WS, push-in, low over the water | none | island hero shot, title |
| 8 | 455–560 | "The people who live here have refused contact… for thousands of years…" | Low lateral glide along the beach and tree line, no people. Silence and danger. | WS lateral dolly, low | none | fog in the trees |
| 9 | 560–668 | "…and they defend that. Hard." | Fires light up one by one deep in the trees on "defend… that… HARD". Cut back to the hero seeing them; he backs away from the rail. | MS reverse, push-in to MCU | **step_back_fear** (new) | 6 fires, rim of firelight |

## ACT 2: The wreck (23–27 s)

| # | Frames | VO | Picture | Size / camera | Hero action (clip) | Props / FX |
|---|---|---|---|---|---|---|
| 10 | 670–722 | "Then… CRUNCH." | Underwater-ish low angle: the hull slams onto the coral. Big shake, foam burst. | Low WS at waterline, impact shake | **fall_impact** (new): he is knocked off his feet | coral, foam spray, camera shake |
| 11 | 723–785 | "You hit the reef. You're stuck." | Boat tilted 8° on the reef, waves breaking over the side. The hero gets up holding the rail. | MS, slow orbit | **get_up_hold_rail** (new) | tilted yacht, spray |
| 12 | 786–832 | "So what do you actually do?" | Hero looks straight into the lens, breathing hard. | CU, slow push to ECU | **breathe_look_camera** (new) | none |

## ACT 3: The steps (27–68 s)

| # | Frames | VO | Picture | Size / camera | Hero action (clip) | Props / FX |
|---|---|---|---|---|---|---|
| 13 | 834–877 | "Step one. MAYDAY!" | Hero grabs the VHF handset and shouts into it. STEP 1 tracker. | MCU, whip-pan into the radio | **radio_shout** (new) | VHF radio, coiled cord |
| 14 | 877–940 | "Grab your radio, channel 16…" | Insert: the radio display glows "16", his thumb pressing PTT. | ECU insert, slow push | (hand only) | radio display "CH 16" |
| 15 | 940–1001 | "…and fire off your emergency beacon." | He pulls the EPIRB beacon tab; the strobe starts flashing white. | MS, low angle | **activate_beacon** (new) | EPIRB beacon, strobe light |
| 16 | 1010–1075 | "The Indian Coast Guard patrols these waters." | Pull out and up: beacon pulse rings rise; far on the horizon a Coast Guard ship's searchlight turns toward us. | Big crane-up pull-back | **radio_wait** (new) | Coast Guard ship, searchlight beam |
| 17 | 1086–1160 | "Step two. Do NOT go ashore." | Hero at the bow looks at the beach 300 m away. A dotted path draws toward shore and is X'd out red. | OTS from behind him toward the island | **look_at_shore** → **shake_head_no** (new) | Remotion dotted path + red X |
| 18 | 1168–1228 | "Not for a photo. Not to say hi." | He lifts a phone as if to take a photo, then thinks better of it and puts it away; a half wave dies. | MS, frontal, push | **phone_photo_abort** (new), **wave_stop** (new) | phone |
| 19 | 1236–1305 | "They have almost no immunity to our germs." | Graphic: germ particles around the hero drift toward the island and stop at the protected-zone ring. | WS from the side, slow track | **cover_mouth** (new) | particle germs (Remotion) |
| 20 | 1314–1385 | "Even a common cold could be deadly for them." | Hero sneezes; the germ cloud puffs out, the camera follows it toward the island, and the ring blocks it. | MCU → follow the cloud | **sneeze** (new) | germ cloud, ring |
| 21 | 1389–1460 | "Step three. Stay with your boat." | Hero sits down on the tilted deck, back against the cabin, holding on. The boat is solid. | MS, slow arc | **sit_down_hold** (new) | none |
| 22 | 1461–1520 | "And this has actually happened before." | Camera rises away from the yacht; the night sky turns to an archival sepia grade. | Crane-up transition | sitting idle | grade transition |
| 23 | 1523–1650 | "In 1981, a cargo ship called the Primrose ran aground right here." | Huge cargo ship stranded on the same reef in a storm; "PRIMROSE · 1981" label. Rain. | EWS slow pull-back to reveal scale | none | **Primrose cargo ship** (new prop), rain, storm sea |
| 24 | 1650–1760 | "The crew saw armed islanders on the beach…" | From the ship's deck: the beach at a distance, only torches and shadows (never people). | POV from the bridge window, slow push | none | torches, rain on glass |
| 25 | 1760–1840 | "…so they stayed inside their steel hull and waited for days…" | Inside the hull: a lamp swings, day counter DAY 1 → 7. | MS interior, slow drift | none (crew silhouettes) | cargo hold interior, day counter |
| 26 | 1840–1925 | "…until helicopters lifted every single one of them out." | Helicopter hovering over the ship's deck in daylight, winching people up. | WS, crane-up with the helicopter | none | **helicopter** (new prop), rotor wash |
| 27 | 1931–1990 | "Step four. Kill the lights." | Back on our yacht at night: the hero switches off the last lamp (anchor light) and the frame goes dark. | CU on the switch, then MCU of the face | **switch_off** (new) | lamp OFF |
| 28 | 1995–2025 | "Stay quiet." | Finger to lips, in moonlight only. | CU, slow push | **shush** (new) | none |
| 29 | 2029–2070 | "Leave nothing behind." | He ties a trash bag closed and stows it in a locker. | MS, top-down tilt | **stow_bag** (new) | trash bag, locker |

## ACT 4: Escape and payoff (68–80 s)

| # | Frames | VO | Picture | Size / camera | Hero action (clip) | Props / FX |
|---|---|---|---|---|---|---|
| 30 | 2076–2140 | "And if the tide lifts your boat?" | Water rises up the hull, the boat levels and floats. | Low WS at the waterline, rising | **look_down_relief** (new) | tide rise |
| 31 | 2140–2195 | "Drift out past the reef, and get gone!" | Boat drifts out over the reef foam into open water; first dawn glow. | Aerial chase, pull-back | **stand_brace** at the helm | dawn light begins |
| 32 | 2200–2340 | "Because on North Sentinel… the smartest way to survive…" | Dawn. The island small and dead centre, the yacht a dot leaving. | EWS, slow drift | none | dawn sky |
| 33 | 2340–2416 | "…is to never be there at all." | Hold on the island; quote typography, end card. | Hold with micro-drift | none | end card |

## Asset build list (from the shots above)

**Motion clips (new, about 20, on the existing hero rig):**
1. helm_idle
2. flip_switch_fail
3. look_around_worried
4. step_back_fear
5. fall_impact
6. get_up_hold_rail
7. breathe_look_camera
8. radio_shout
9. activate_beacon
10. radio_wait
11. look_at_shore
12. shake_head_no
13. phone_photo_abort
14. wave_stop
15. cover_mouth
16. sneeze
17. sit_down_hold
18. switch_off
19. shush
20. stow_bag
21. look_down_relief
22. stand_brace

**Props (new):**
- VHF radio and handset
- EPIRB beacon with strobe
- switch panel
- phone
- trash bag and locker
- Coast Guard patrol ship
- Primrose cargo ship (1981 bulk carrier)
- cargo-hold interior
- helicopter
- coral reef heads

**Environment:**
- Poly Haven night HDRI
- real deck wood
- island rocks, sand and palms (ambientCG / Poly Haven)
- rain and storm variant for 1981
- dawn variant

**Overlays (Remotion):**
- map with drift line and zone ring
- dotted path and red X
- germ particles
- day counter
- STEP tracker
- titles and kinetic captions

## Why v1 failed (do not repeat)
- Only 3 motion clips (brace, startle, panic) were reused for 11 beats, so the hero flailed while the VO talked about radios and beacons.
- Every beat used the same deck spot and orbit move, so nothing shown matched the words.
- Story props were never built: no radio, beacon, Primrose, helicopter or switch.
- Each beat ran for a whole scene with no cuts on the VO.
