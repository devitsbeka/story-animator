# VISUAL CANON: lighting, coverage, editing, handheld, performance, look-dev

Distilled from sources 1 to 7 of `factory/canon/SOURCES.md`. The rule IDs are the `CAN-*` IDs in
`.claude/skills/film-craft-canon/SKILL.md`. Sub-rules (`CAN-L1a`, ...) are added here, and the parent IDs stay stable.
The story, suspense and narration rules (`CAN-S*`, `CAN-N*`, sources 8 to 11) live in `STORY_SOUND_CANON.md`.

**How to read a rule.** Every rule gives the engine that implements it, the director field it reads, and the
automatic check. Each threshold is tagged as one of:
- **[SRC]**: the number is in the source and quoted below.
- **[SRC→30fps]**: a source number converted to our frame rate. Both episodes run at **30 fps** (`episode.json.fps`). The
  sources count frames at 24 fps (film) or in 35 mm feet (16 frames per foot).
- **[HOUSE]**: our own calibration of a principle the source states. Tune it with goldens, never by hand in one shot.
- **[UNVERIFIED-SRC]**: the source could not be retrieved (see below). The rule rests on the `SOURCES.md` summary plus
  the corroborating quotes given here.

**Retrieval log (2026-11-22).** These were fetched into `/tmp/canon/` and extracted with `pdftotext` / an HTML strip:
- Source 1 (Calahan, 31 pp.): OK.
- Source 2 (CML Lighting, 470 pp.): OK. "Filming at night" is printed pp.137-141.
- Source 4 (Reisz & Millar, 369 pp.): OK. Ch.3 is printed pp.49-63.
- Source 6 (Animation Mentor Vol.1, 99 pp.): OK.
- Source 7 (ASC web article, Feb 1 2018, by Jon Silberg): OK.
- **Source 3 (UW CSE456):** returns the UW NetID login page ("Choose Identity Provider") for both the 18su and 09su
  copies.
- **Source 5 (CCEA Greengrass fact file):** returns "CCEA Restrict Access" (HTTP 403), and the Wayback Machine is
  blocked by this sandbox's egress policy.

For source 5, the supplementary quotes come from the DGA Quarterly profile of Greengrass (Summer 2007, dga.org) and
are marked as such. **Action item:** someone with UW or CCEA access should drop the two PDFs into `factory/canon/src/`
(git-ignored), and the [UNVERIFIED-SRC] tags should then be re-checked against them.

Page citations: "p." is the printed folio when the document has one, and "PDF p." is the page index in the file.
Calahan's printed folios are garbled ("PIXEL CINEMATOGRAPHY 2 1"), so it is cited by **section § and PDF page**.

---

## 1. Sharon Calahan, *Storytelling Through Lighting* (Pixar): CAN-L1, CAN-L3, part of CAN-L2

### (a) Key passages
- §2, PDF p.3: "The primary purpose of cinematic lighting is storytelling. [...] It is not enough that the lighting
  designer simply illuminate the scene so the viewer can see what is happening, or to make it look pretty."
- §3, PDF p.3: "The primary objective of good lighting is to show the viewer where to look. Shots are often on-screen
  only briefly, which means the storytelling effectiveness of a shot often depends upon how well, and how quickly,
  the viewer's eye is led to the key story elements."
- §3.2, PDF p.5: "A composition may have more than one focal point, but one should dominate." Also: "Images which are
  lit with default or uniform lighting similarly feel drab and lifeless."
- §3.2.1, PDF p.5: "The primary method for achieving emphasis is by establishing contrast. [...] Contrast in value
  (brightness) is easy for the eye to see [...] It also illustrates why lighting is a major tool in the establishment
  of emphasis."
- §3.2.7, PDF p.7: "If all objects are moving except one, the eye will be drawn to the one which is not moving. The
  opposite case, of only one object moving, is more common and even more effective in attracting attention."
- §3.3.1, PDF p.8: "in a dark theatre, with our pupils dilated, a bright area will attract even more attention."
- §3.6, PDF p.12: "If a character looks toward an object, the viewer will also look. These psychic lines are very
  powerful."
- §3.7, PDF p.13: "By just hinting at a shape with a minimal amount of light, the viewer's imagination becomes engaged,
  and a mood of mystery and suspense is evoked."
- §3.10, PDF p.14: "A progressive building of visual tension can foretell that something bad is going to happen [...]
  A sudden change in visual tension can accentuate the shock of a dramatic change."
- §3.11, PDF p.14: "it may also be desirable to 'lead' the viewer's eye into the next shot."
- §3.12, PDF p.15 (Woody/Buzz): "This dark shadow area behind Buzz allows him to 'pop' from the background [...] Woody
  does not have a rim light to aide in his blending into the background, while Buzz has a nice bright one which helps
  him separate."
- §4.1, PDF p.16 (low key): "most of the scene is darkly lit, with the emphasis on the few areas which are brightly
  lit. [...] The overall impression is dark but not murky. What is seen is equally important to what is not seen.
  [...] Light is used to direct the viewer's attention, the darkness to stimulate his imagination." High key "minimizes
  suspense since nothing is left to the imagination."
- §4.2, PDF p.17: "Night scenes, especially exteriors, tend to be lit with harder lights."
- §4.3, PDF p.17: "If there is a visible source of light within the image frame, the viewer expects the overall light
  direction to emanate from the source they see, even if the lighting originated from a different source in the
  previous shot." Also: "The exact angle and intensity of the light will never be scrutinized by the audience as long
  as it is not disorienting."
- §4.4, PDF p.17: "a light should not be added to a scene without an intended purpose, and the temptation to use one
  light to serve two purposes should be avoided."
- §4.5, PDF p.18: "One shadow should still dominate, but it is usually necessary to introduce a secondary or contact
  shadow to help ground a character."
- §4.6.2.4, PDF p.20: "Backlighting should be used with thought since it tends to be overused." Also: "Consistent
  backlighting is also tricky to achieve in a wide-angle shot [...] It may be necessary to animate backlights."
- §4.7.1, PDF p.21: "A nighttime scene might reverse this sense with a strong blue key light acting as moon light with
  a soft warm fill emanating from incandescent indoor lighting." Also: "A natural feeling still can be maintained even
  when using a strongly colored light [...] as long as it appears to emanate from a visible practical source."
- §5.1, PDF p.24: "A lighting plane is essentially a collection of objects [...] lit as a unit to contrast with other
  planes. [...] Each plane is clearly defined by its brightness. This separation can be further accentuated by color
  variations between planes."
- §5.2, PDF p.24-25: "any light which emanates from the general camera direction tends to reduce the illusion of
  volume." Also: "pools of light separated by dark objects or areas" give a set depth.
- §5.3, PDF p.25: "A close-up where the background is out of focus will feel more intimate than one where the
  background is sharp. [...] depth of field is useful for directing the viewer's attention."
- §5.4, PDF p.26: aerial perspective "by minimizing color saturation and contrast" over distance.
- §5.6, PDF p.26: "A warm subject over a cool background will impart more apparent depth [...] if the brighter side of a
  subject is placed against a dark background area, it will help define the shape."
- §6, PDF p.27 (night): "The practical sources which are visible in the frame should determine the quality of the
  light. The illusion of night is created by the angle and the distribution of light. The angle of the light tends to
  be less frontal for a night effect, a three-quarters-back key light is frequently used with little frontal fill.
  Because there is less ambient and fill light in general, the percentage of well-lit areas in the frame is smaller,
  and specular glare becomes more noticeable."
- §4.6.2.2, PDF p.19: the key light "can be effectively placed as far back as 135 degrees from the camera as a
  three-quarters-back key light."
- §3.3.7, PDF p.10: "A consistent use of lenses for close-ups, medium shots and long shots helped to ensure spacial
  continuity."
- §8, PDF p.28: "The establishment of the focal point is the best place to start. In the process of creating emphasis
  for the focal point, distracting elements will need to be minimized."
- §9, PDF p.28-29: "A thirty frame shot needs to direct the eye quickly. The audience does not have time to guess where
  to look." Also: "the overall feeling of the shot should be consistent with its sequence and especially with its
  adjacent shots. [...] the more similar two shots are that cut directly together, the more important it is for the
  lighting to be same. An establishing shot [...] will usually require broad lighting strokes and often more light in
  background areas [...]. When the camera moves in for the close-ups, it is often desirable to darken the background
  slightly or move a shadow line to help the foreground subject to separate [...]. These changes should be unnoticeable
  to the viewer."
- §12 Suggestions, PDF p.30: "Avoid the temptation of lighting dark shots too dimly. At least part of the image needs
  to be well-lit." Also: "Avoid placing a bright light which emanates from near the camera lens." "Remember that one
  light cannot always solve two problems." "Consider that lights which animate in position, unless they are attached
  to a moving object, will not look natural."

### (b) The principle in plain words
Light exists to tell the viewer **where to look, and when**. At night that means: **one** dominant focal point per
shot, made by value contrast, inside a mostly dark frame. The story detail stays hinted (subordinate) until the beat
that should reveal it, and then light reveals it. The key comes from three-quarter back with little frontal fill.
Every light has one job and a visible or implied motive. Planes (foreground, midground, background) separate by value
and colour. A rim pops a dark subject off a dark ground. A close-up may darken its background slightly versus the wide,
but the cut must not be noticed.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-L1a** | Every sequence declares what the viewer discovers, in which shot, and by which light. | director `shotplan` schema (`factory/director/schemas/shotplan.schema.json`), `factory/director/checks.py` | `discovery_map[]`: `{detail, shot, frame, light_reveal:{source, kind ∈ reflection\|rim\|practical_pool\|lightning\|silhouette\|glint}, subordinate:[...]}` | Schema check: ≥1 entry per sequence that has a story point. `shot` exists; `frame` lies inside it, ≥10 f after the shot start (see CAN-P1c) [SRC→30fps]. `source` names a light that `lighting.py` actually builds (`_tag` motivation). FAIL if it is missing. |
| **CAN-L1b** | One focal point dominates at the reveal frame. | `cloud/blender/lighting.py` (specials/rim on the detail) + `factory/qc/plates.py` | `discovery_map[].detail` → object/cryptomatte mask | On the plate at `frame`: ≥50 % of the top-2 % luminance pixels fall inside the detail mask ∪ hero face mask, **and** the detail's local value contrast (Michelson, detail vs. its 2× dilated ring) ≥1.5× that of any other equal-area region [HOUSE; §3.2 "one should dominate"]. |
| **CAN-L1c** | The detail stays subordinate before its reveal ("hint at a shape"). | lighting.py (light keyed on `light_event` / animated special) | `discovery_map[].frame` | In shots of the sequence before `frame`: mean detail luma ≤0.5× its value at the reveal, and the detail is not the brightest region [HOUSE; §3.7, §4.1]. Exception: `subordinate:false` (deliberate flash-forward hooks such as waterspout H01). |
| **CAN-L1d** | Night frames are low key, "dark but not murky". | lighting.py presets (`moonlight_practical_mix`, `fill_ratio`) + qc/plates.py | `env.lighting.preset` family = night | Night plates (display-referred luma): well-lit fraction (luma > 0.5) between 2 % and 30 % [HOUSE; §6 "percentage of well-lit areas ... smaller"]. ≥0.5 % of pixels ≥0.75, i.e. at least one hot area [HOUSE; §12 "at least part of the image needs to be well-lit" + CML p.139 Almendros]. ≥15 % of pixels ≤0.04, i.e. real blacks [HOUSE; CML p.137 "good blacks"]. |
| **CAN-L1e** | During a reveal, the revealed thing is the only salient mover. | `cloud/blender/acting.py` (hero verbs) + `factory/direction/camera_presets.py` | `discovery_map[].frame` | In [frame−6, frame+15]: no hero `verb`/`pose` onset, and no camera preset change except `push_reveal`/`low_reveal`/`high_reveal` [HOUSE; §3.2.7]. WARN. |
| **CAN-L1f** | The eyeline points at the discovery. | acting.py gaze + `cloudrig_adapter.face_at` gaze | `discovery_map[]` + hero `face.gaze` | When the hero is in frame at the reveal, gaze yaw toward the detail is within ±20° by `frame + 8` [HOUSE; §3.6 psychic line]. Exception: the audience-first reveal (CAN-S1), where the hero must **not** look (gaze ≥45° away). |
| **CAN-L3a** | Planes of light: foreground, midground and background separate by value. | lighting.py (`_haze`, plane specials) + qc/plates.py with a depth pass | none (derived) | With the Z pass split into the 3 depth terciles of the subject range, adjacent planes differ by ≥0.5 EV in mean luma, or by ≥25° in mean hue [HOUSE; §5.1]. |
| **CAN-L3b** | A rim separates a dark subject from a dark ground. | lighting.py `build_hero_rig` (rim), `rim_energy` | none | When the background ring around the hero silhouette has luma < 0.08, the 3 px inner edge band of the silhouette must be ≥1.6× the ring luma on ≥35 % of its length [HOUSE; §3.12, §5.6]. |
| **CAN-L3c** | The rim is not overused, and no heavy blue backlight wash. | lighting.py | `rim_energy` | Hero rim irradiance ≤1.5× key irradiance at night [HOUSE; §4.6.2.4 "tends to be overused" + CML p.140 "not a big proponent of drowning an area with heavy blue backlight"]. |
| **CAN-L3d** | Background accents sit ≥1 stop under the subject. | lighting.py (tree/shore specials, fires) | none | Mean luma of lit background accents ≤0.5× the hero face mean (−1 EV) [**SRC**: CML p.140 "keep 'em at least 1 stop under so it doesn't call attention"]. |
| **CAN-L3e** | Warm subject over cool ground; aerial perspective. | lighting.py `_retint`, `_haze` | none | Hero mean hue vs background mean hue ≥30° apart at night [HOUSE; §5.6]. Far-plane RMS contrast < near-plane RMS contrast [HOUSE; §5.4]. |
| **CAN-L3f** | Close-ups are shallow and lenses are consistent. | `camera_presets.py` (dof) + `shot_validator.py` C14 | `camera.lens`, `dof` | CU/MCU: dof on, and the background circle of confusion ≥4 px at 1080 w [HOUSE; §5.3]. Hero CU lens within ±10 mm per sequence (existing **C14**) [§3.3.7]. |
| **CAN-L2c** | Every light has one motive and one job; the in-frame practical sets the key direction. | lighting.py `_tag(ob, motivation, role)` + `_checks` | `env.lighting.key_motivation`, practicals list | FAIL when a light lacks a `motivation` tag, or when two roles share one light [§4.4]. When a practical is in frame within 4 m of the hero, the key motivation is that practical, or the angle between hero→practical and the key direction is ≤45° [HOUSE; §4.3]. |
| **CAN-L2d** | Night key is three-quarter back with little frontal fill, and no bright source by the lens. | lighting.py presets | `key_az`, `fill_ratio` | Night: key azimuth relative to the camera axis 90° to 150° (WARN outside) [SRC range ≈ §4.6.2.2 "as far back as 135°", §6]. key:fill ≥4:1 on the hero face (presets use 6.5) [HOUSE]. No key or fill within 20° of the camera axis [HOUSE; §5.2, §12]. |
| **CAN-L2e** | Moving lights ride moving things. | lighting.py | none | Any light with an animated location must be parented to an animated object (yacht, torch, lightning is exempt as a `light_event`) [§12]. |

---

## 2. Cinematography Mailing List, *Lighting*, "Filming at night" (printed pp.137-141): CAN-L2, CAN-L1d, CAN-L3d

### (a) Key passages
- p.137 (JD Belinski): "Most common mistake with inexperienced 'night lighters' [...] is overlighting the scene. Think
  about your motivation at night and what night looks like to you. [...] Allow things to fall of[f] 1stop, 2 stops,
  3 stops, blackness, etc. To me, a night scene needs good blacks as much as it needs highlight (practical) areas."
- p.138 (Jim Allen): "dusk shots [...] or some sort of Day for Night to do the cover shots then use your lighting
  arsenal to supplement the MS's and CU's." Also: "Build a big fire in the middle of the compound and let the
  tungstens support the fire (similar color) and allow the HMI's to give you the overall bluish effect of a moonlight
  night."
- p.138: "go to town on the practicals - just as Cameron added twice as many practicals to the deck of the Titanic [...]
  The practicals will do a lot of the lighting of the trailers, leaving you to concentrate on lighting the actors."
- p.139 (David Mullen): "you'll want to work in backlight or crosslight with a minimal amount of fill when needed to
  maintain a sense of darkness and a night atmosphere. Don't try to light everything up - try to balance areas of
  darkness with lit areas. [...] Nestor Almendros' advice - when a scene is very underexposed, one hot area of
  overexposure (like a bright lantern) will seem to balance the lighting to your eye, making the dark areas seem less
  murky."
- p.140: "creating some depth at night when possible is very helpful. Light up some trees far in the background. Lots of
  practicals." Also: "Don't be afraid to let parts of the scene go black, use shadows and silhouettes. I'm not a big
  proponent of drowning an area with heavy blue backlight, it rarely looks good. A fire, or multiple small fires [...]
  lanterns, maybe some strings of small lights to help guide the audience's eyes where you want it to. [...] light some
  bushes, trees, fence whatever in the far distance to give the scene some depth [...] keep 'em at least 1 stop under
  so it doesn't call attention."
- p.141: "putting little glows under or behind things if, and only if they add to the shot (which is trying to help tell
  a story)." Also (Jim Furrer): "Hate those deep-focus 'night' shots!"
- Related thread, "Lighting With Practicals", p.259: "Practicals should be something that's appropriate to the scene and
  not just objects thrown in to add light." p.260: "silhouetting the receding actors against the background."

### (b) The principle in plain words
Night is made by **what you leave dark**. Let the frame fall off in stops down to black. Let a few motivated
practicals (fire, lanterns, deck lamps) carry the set and guide the eye. A warm fire is supported by warm units, and
the moon is a cool, broad, high source. Work from back or cross with minimal fill. One hot spot makes the darkness
read as intended rather than murky. Light distant elements for depth, but keep them a stop under. The wide may be lit
broadly while the medium shots and close-ups get added shaping, and that is exactly where the **wide-to-close
mismatch** risk lives: the close-up must be supplemented *inside the same night logic*. It must not become a lit
daylight portrait. (The source's own sentence: the MS/CU are "supplemented" from the same arsenal. They are not
relit.) Night shots are not deep-focus.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-L2a** | The key direction holds across the cut within a sequence. | `cloud/blender/lighting.py --check` (`check_sequences`, existing L2/L8) | `env.lighting.cheat_reason`, `light_event` | Key Δaz ≤15°, Δel ≤10° versus the sequence key shot, and the preset is unchanged, unless `cheat_reason` or `light_event` is set (existing) [HOUSE; Calahan §9]. A `cheat_reason` may only darken the background or move a shadow line (Calahan §9). It may never raise face exposure (see L2b). |
| **CAN-L2b** | **The close-up must not feel like daylight next to its wide.** | lighting.py `build_hero_rig` + `factory/qc/plates.py` | `reserved_close_up`, per-shot `size` | For each CU/MCU, compare against the nearest WS/MS of the same sequence on hero-face-mask luma: Δ ≤ +0.5 EV and ≥ −1.0 EV [HOUSE]. Face key:fill stays ≥4:1 [HOUSE; CML p.139 "minimal amount of fill"]. Face key hue stays on the moon side (hue distance to the key colour ≤ 25°), or it is the declared practical [HOUSE]. CU background mean ≤ the wide's background mean, i.e. darker only [Calahan §9]. |
| **CAN-L2f** | Practicals carry the set, each is motivated, and they are of the right kind. | `lighting.py` practical retint + `props.py`/`yacht_v2.py` practical emitters | `world.practicals[]` with `motivation` | Night sequences with a set: ≥2 visible practicals per wide, or a declared `practicals_off` `light_event` (Sentinel S09) [HOUSE; p.138]. Every practical has a story `motivation` (e.g. "deck lamp", "village fire") [p.259/p.141]. |
| **CAN-L2g** | Fire is supported by a same-colour unit, and the moon is a cool broad source. | lighting.py `kelvin_rgb`, presets | `practical_kelvin`, `key_color` | Fill/bounce attached to a fire practical stays within ±300 K of the fire's colour temperature [HOUSE; p.138 "similar color"]. Key/practical hue separation ≥120° (existing **L5**). |
| **CAN-L1d / L3d** | See §1. The "good blacks", the "one hot area" and the **1 stop under** come from here. | | | [SRC p.137/139/140] |
| **CAN-L3g** | Night shots are not deep-focus. | `camera_presets.py` dof | `camera.fstop` | Night shots MS and tighter: dof on, f-stop ≤ f/2.8 equivalent [HOUSE; p.141]. WS/EWS are exempt (geography must read, CAN-C1). |

> **Cameron's corollary** (source 7, ASC, Feb 2018): "Some cinematographers say nights need to be dark. I believe you
> use cues like color temperature to show that it's night, but you open it up and see into the shadows." This
> **refines L1d/L2b** and does not contradict them. The *environment* keeps real blacks, while the *hero face's shadow
> side* stays readable: face shadow-side luma ≥0.03 (not crushed) [HOUSE], with night carried by colour (cool key,
> warm practicals, L5), not by murk.

---

## 3. *Basic Cinematography for Animation*, UW CSE456 (two-shot exercise p.1): CAN-C1, CAN-C2 [UNVERIFIED-SRC]

### (a) Passages
The source was **not retrievable** (UW NetID login wall, see the retrieval log). The only text seen is a web search
snippet of the 09su copy of the same handout. It refers to a "previous exercise", and says: "It is difficult to find
examples of the Two Shot Sequence because most filmmakers avoid this method of scene construction, especially in
animation." The working principle below is the `SOURCES.md` summary. These retrieved sources corroborate it:
- Reisz & Millar p.49: "it is all the more important not to confuse the audience about the geographical relationship
  between the two parallel streams of action." p.56: the "establishing long shots in which the opposing parties can be
  seen at once [...] form a useful and often indispensable feature of the editing of action scenes."
- Reisz & Millar p.60 (*Once a Jolly Swagman*, Jack Harris): "The medium and long shots were therefore used to indicate
  the ding-dong battle and the close-ups to show the riders' reactions."
- Reisz & Millar p.62: "a close shot in which the image of the figure remains still within the frame conveys all it
  has to say in a short time."
- Calahan §3.4, PDF p.10: "in a close-up shot of a character, the viewer is rarely distracted by the background. But in
  a wide shot containing many elements, the viewer must create relationships between elements."
- Animation Mentor p.20: "whenever the camera cuts to a new angle or location, it takes about 6-8 frames for the
  audience to see and understand where they are."

### (b) Principle
Two shot sizes do two jobs. The **wide** shows *where everyone and everything is*: the man, the vessel, the threat.
The **close-up** is a scarce, high-value shot spent on the **one reaction or decision** the scene builds toward.
Spend it casually and it is worth nothing when the scene needs it.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-C1a** | A wide establishes the geography before any coverage. | `factory/direction/shot_validator.py` **C3/C4/CTX** | `direction.location`, `direction.sequence` | Existing C3: EWS/WS within the first 2 shots of a location. C4: re-establish after ≤6 tighter shots. |
| **CAN-C1b** | The establishing frame holds the hero, the vessel and the threat (or threat zone) **together**. | shot_validator **CTX** (projected bboxes) | `establishes: [hero, vessel, threat]` on the shot | Every listed element projects ≥60 % inside the frame on ≥80 % of sampled frames. The shot lasts ≥36 f (1.2 s) [HOUSE; 3× AM's 8 f read time at 24 → 10 f at 30 fps, plus scan time, Calahan §3.4]. |
| **CAN-C1c** | Screen direction is stable. | shot_validator **C5** | none | Existing: 180° side per sequence. |
| **CAN-C2a** | **One reserved close-up per sequence** for the decisive reaction or decision. | director shotplan schema + shot_validator **C1/C2** | `reserved_close_up: {beat, shot, reason}` | Per sequence, hero-face CU/ECU shots (inserts and POV exempt) = 1, namely `reserved_close_up.shot`; a second one FAILs unless it is declared with `extra_cu_reason` [HOUSE]. Episode-wide CU+ECU ≤25 % (existing C1), and there is never a run of more than 3 tight shots (existing C2). |
| **CAN-C2b** | The reserved CU lands on a knowledge or decision change. | `factory/director/checks.py` | `reserved_close_up.beat`, `knowledge_timeline[]` | That beat's `knowledge_timeline` entry changes `character_knows` or `who_can_act` (CAN-S2), or the beat is tagged `decision`. Otherwise FAIL. |
| **CAN-C2c** | The reserved CU is long enough to see the thought land. | shot_validator **C9** | `turn_then_change` | Duration ≥ 10 f (read) + `settle_frames` + change length + 10 f (tail), i.e. ≥45 f at 30 fps, and ≤6 s [HOUSE; AM pp.19-20, Reisz p.62]. |
| **CAN-C2d** | The wide covers the shot sizes it must; mediums do the "ding-dong". | shot_validator **DIST** | none | Existing shot-size distribution targets. |

---

## 4. Reisz & Millar, *The Technique of Film Editing*, Ch.3 "Action Sequences" (printed pp.49-63): CAN-E1

### (a) Key passages
- p.49: "There is first the elementary difficulty of keeping the spectator clearly informed of what is going on. [...]
  There may sometimes be a temptation to cut an action sequence too fast in the attempt to generate greater
  excitement: if this involves confusing the spectator about the physical details of the scene, then the editor will
  have defeated his object."
- p.49: Griffith's cross-cutting: "by timing the conflicting shots he was able to give now the pursuer, now the pursued,
  the advantage." Also: "the reaction shot—usually a static image of an observer—was used to punctuate the moving shots
  and to produce the visual contrast which accentuates the effect of movement."
- pp.50-51, *Naked City* shot list (cost before pursuit). Shot 6: "The blind man stands helpless at the top." Shot 7:
  "L.S. Blind man. [...] Dog lies dead to the right, bridge in background. [...] Halloran stoops to look at the dead
  dog" (5 ft 10 fr). Shot 8: "M.C.S. Halloran. He looks up in the direction of the bridge (trying to spot Garza)."
  Shot 9: "Shooting along bridge as from Halloran's viewpoint. Garza running away from camera in V.L.S."
- p.54, the same look → POV → reaction triad at the gunfight. Shot 26: "M.C.S. Garza as he climbs on to a fence. He
  looks down." Shot 27: "From Garza's viewpoint. Muldoon's car draws up below." Shot 28: "Garza has spotted the car and
  momentarily attempts to hide."
- p.55: "During the entire passage, the geography of the locale and each stage of the chase have been clearly conveyed.
  The rate of cutting is continuously made to underline the changing tension of the situation. [...] Finally, the rate
  of cutting is further speeded up into a climax as the gunfire begins."
- p.56: "from shot 13 onwards each cut takes us to another part of the action: there are no cuts which continue the
  action of a previous shot. This constant switching of the focus of attention creates an impression of fast action
  even though the cutting [...] is not particularly quick."
- p.60 (Jack Harris): "the audience gets a prior knowledge as to what the final result will have to be [...] This
  uncertainty made it easier for us to hold the audience's interest."
- p.61: "The use of the reaction shots [...] bridges the time gaps between the long shots [...] By cutting away from the
  race and then cutting back again, a lapse of time is implied which makes it acceptable to the spectator."
- p.62: "It is precisely through the variation of the images that an effect of speed is conveyed." Also: "the close
  shots are always left on the screen for a much briefer interval than the long shots. This is because a close shot in
  which the image of the figure remains still within the frame conveys all it has to say in a short time. A long shot,
  on the other hand, in which the movement takes place across the frame, is a source of more sustained interest."
- p.62, summary: "(1) to keep the 'plot' of the passage clearly in front of the spectator [...]; (2) to vary the pace of
  the cutting in order to obtain the desired variations of dramatic tension; (3) to cut away to reaction shots of
  static observers in order to bridge time lapses [...] and in order to guide the audience's emotional response; (4) to
  give visual variety and the illusion of continuous movement by frequent cross-cutting and by varying the angles of
  view on a single piece of action."
- p.63: "In action sequences [...] it is the pictures which tell the story."

### (b) Principle
An action sequence is an **ordered delivery of information**, and pace comes from *what each cut tells you*, not
from raw cut speed. Ch.3 does not print the four-step list in `SOURCES.md`. That list is our distillation of the
patterns Ch.3 does show. The **look → POV → reaction** triad (shots 8-9-10, 26-27-28) is how a character "sees" the
obstacle. The **cost shot** stands as its own beat (shot 7: the dead dog, held 5 ft 10 fr ≈ 3.75 s, before the pursuit
resumes). The audience-ahead knowledge is in p.60, and Hitchcock (CAN-S1) supplies "audience first". The order is:
1. the audience sees the obstacle;
2. the character sees it (look → POV);
3. impact;
4. the cost is revealed in its own shot.

Close static shots are shorter than moving long shots. Acceleration is reserved for a mounting climax. Every cut goes
to a new angle or a parallel action. Cutaways legitimise compressed time.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-E1a** | The four information steps exist, in order, as distinct shots. | director shotplan schema + `factory/director/checks.py` | `action_order: {obstacle_audience, obstacle_character, impact, cost_revealed}` (shot ids, optionally with `frame`) | All four are present for each sequence tagged `action`. They are strictly increasing in time, and no two share a shot except `obstacle_character` + `impact` in a single unbroken take (`long_take:true`). FAIL otherwise. |
| **CAN-E1b** | The audience lead is felt. | checks.py (with CAN-S1) | `action_order.obstacle_audience/obstacle_character` | Gap ≥ 60 f (2 s @30) of screen time [HOUSE]. The hero's gaze is ≥45° off the obstacle during the `obstacle_audience` shot (CAN-L1f exception). |
| **CAN-E1c** | The character sees it via look → POV/reveal → reaction. | shot_validator + acting gaze | `obstacle_character` shot, the next shot | The `obstacle_character` shot has a gaze onset toward the obstacle. The next shot is `pov`/`insert`, or frames the obstacle (CTX bbox ≥60 % in). The shot after that, or the tail of the same shot, holds the reaction ≥10 f [SRC pattern p.50-54; HOUSE numbers]. |
| **CAN-E1d** | The cost is revealed in its own held shot. | shot_validator C9 + discovery_map | `cost_revealed` + a `discovery_map` entry for the cost | The `cost_revealed` shot ≥ 75 f (2.5 s @30) [HOUSE; Naked City shot 7 = 5 ft 10 fr = 90 f@24 = 3.75 s]. It has a matching `discovery_map` entry, i.e. light reveals the damage (CAN-L1). |
| **CAN-E1e** | Geography stays clear; don't out-cut comprehension. | shot_validator **C9/P1** | none | In action sequences, no shot < 18 f unless `insert` (existing C9). The wide re-establishes ≤6 shots after the impact (C4) [p.49]. |
| **CAN-E1f** | Close static shots run shorter than moving long shots. | shot_validator P1 | none | Per action sequence: median(CU/MCU with camera speed < threshold) < median(WS/EWS with subject screen motion) [SRC p.62, the direction is sourced; the ratio is left free]. WARN. |
| **CAN-E1g** | The cutting rate follows the tension curve. | shot_validator **P1** | `sequence.tension: mounting\|plateau\|release` | `mounting`: ASL of the final third ≤0.8× the first third [HOUSE; p.55]. `plateau`/`release`: no forced acceleration (the Swagman finish, p.61). |
| **CAN-E1h** | Every cut in action goes to a new angle or a parallel action. | shot_validator (preset/azimuth diff) | none | Consecutive shots in an action sequence differ by ≥1 size class **or** by ≥30° camera azimuth about the subject, or cross-cut location [HOUSE; p.56, p.62 (4)]. |
| **CAN-E1i** | Compressed time needs a cutaway. | checks.py | `time_cut:true` on a shot | A shot that skips action time against its predecessor on the same subject must be preceded by a reaction or parallel-action cutaway [SRC p.61]. |

---

## 5. Paul Greengrass, CCEA director fact file: CAN-H1 [UNVERIFIED-SRC]

### (a) Passages
The CCEA PDF itself was **not retrievable**: HTTP 403 "CCEA Restrict Access", and the Wayback Machine is blocked by
egress. The supplementary passages below are from the DGA Quarterly director profile, Summer 2007 (dga.org), as
returned by WebFetch. Verify them against the print copy before treating them as quotations.
- Greengrass prefers "lots of handheld, and as much natural light as possible," "getting into the thick of things,
  accidental-seeming, where luck comes into play, as well as good judgment."
- "I like things to feel unconsidered, to make you feel like you're an active participant in the events."
- "With the dramatic canvas I found you could still operate with the documentarist's observational eye."
- "His camera often lurks at the fringes, as if catching the actors unaware, shuddering and gliding amongst them."
- "a very immediate and direct feeling, an emotional truthfulness, as if the camera was right in there as a
  participant."

### (b) Principle
The handheld camera behaves like a **person who did not know the hit was coming**. On impact, the subject jolts out of
the framing, because the operator could not anticipate it. The camera catches up a beat late and re-finds the subject.
The shake is *reactive*: it is caused by events, not by a constant wobble. A locked-off impact reads as staged, and a
uniformly shaky camera reads as decoration.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-H1a** | Every impact beat declares a reactive handheld event. | director shotplan schema; `camera_presets.py` (new `impact` layer on top of the `handheld` amplitude) | `impact_handheld: {shot, impact_frame, escape_frames, lag_frames, recover_frames, amplitude_deg}` | Present for each `action_order.impact` shot and each shot whose `camera.motivation == "impact"` (e.g. waterspout H29). FAIL if it is missing. |
| **CAN-H1b** | The subject briefly escapes the frame. | camera_presets impact layer; checked by shot_validator | `escape_frames` | For `escape_frames` ∈ [2, 6] f @30 [HOUSE]: ≥30 % of the subject bbox is outside the frame, or the subject centre is outside the 0.1-0.9 safe area, starting ≤2 f after `impact_frame` [HOUSE]. |
| **CAN-H1c** | The camera catches up late. | camera_presets: aim follows the subject through a first-order lag | `lag_frames` | Camera aim error peaks at `impact_frame + lag_frames`, with `lag_frames` ∈ [3, 8] f @30 (≈0.1-0.27 s) [HOUSE]. Re-centred (H1 tolerance) by `impact + lag + recover_frames`, with recover ≤15 f [HOUSE]. One overshoot ≤30 % is allowed. |
| **CAN-H1d** | No locked-off impacts. | shot_validator **P7** | none | In [impact−2, impact+lag], camera angular speed ≥ 8°/s [HOUSE]. |
| **CAN-H1e** | The shake is event-driven, not constant. | camera_presets `handheld` | `camera.handheld` | Outside impact windows, `handheld` ≤0.12 (presets default 0.1-0.12; POV 0.18). Shake RMS in the impact window ≥3× the shot's baseline [HOUSE]. |
| **CAN-H1f** | The validator must not fight the canon. | shot_validator **H1** (subject centred \|x−0.5\| < 0.08) | `impact_handheld` window | H1 and C11 eye-trace **exempt** frames [impact, impact + escape + lag + recover]. The `factory/qc/plates.py` flicker rule already exempts "camera shake". The impact window must be passed to it. |
| **CAN-H1g** | No impact handheld on the reserved CU. | checks.py | `reserved_close_up`, `impact_handheld` | They may not share a shot. The reaction needs a stable face (CAN-P1) [HOUSE]. |

---

## 6. Animation Mentor, *Animation Tips & Tricks* Vol.1: "Spotlight Your Expressions" / "Expression Changes Get Lost in Movement" (printed pp.18-20) and blinks (pp.8-10): CAN-P1, CAN-P2

### (a) Key passages
- p.19: "**Expression Changes Get Lost in Movement.** This is a fundamental concept for facial animation. Never stage an
  important face change to occur mid-motion. Ever."
- p.19: "What you'd usually want to do is slip the timing of the facial transition either earlier or later. Have her face
  start to transition into happiness just before the head turn, or leave it sad, turn the head, and then move from
  sadness to happiness once she sees the other character."
- p.19: "If the face transitions in the middle of a fast head turn, the facial performance will suddenly feel disjointed,
  or disconnected. [...] 'don't do a complete change in facial expression in the middle of a fast head movement.'"
- p.19: "give her a moment to stare at him - still sad. Frozen. [...] You have a chance for her now to have a moment to
  REALIZE what she is seeing. For it to sink in! [...] and only THEN, finally showing that joy in her face and eyes!"
- p.20: "if you have to place a change of emotion during a jog, you'd probably want to try your best to cram it into the
  hang time at the top of the character's arc. The top of that bouncing arc will be the moment of least movement in the
  character's head, which automatically makes it the best moment for any facial change."
- p.20: "**No Expression Changes in the First or Last 8 Frames of Your Scene.** [...] If you have a facial transition
  happening at the very beginning of the shot (within the first 6-8 frames) or the very end, no one in the audience is
  going to properly see or understand it. Worse, it will draw their eye (in a negative way) and will feel like a 'pop'."
- p.20: "whenever the camera cuts to a new angle or location, it takes about 6-8 frames for the audience to see and
  understand where they are. [...] avoid any kind of quick pose change or changes in direction within those 'bookend'
  frame-ranges. Just like with the face, any overall body change in direction will also read as a 'pop'."
- p.18: "probably by frame 8 the audience is looking at your character's face. [...] the first place any audience will
  be looking, will almost always be the eyes."
- p.9: "The most important use of a blink is to show thought process." Also: "1. We blink when we shift our thought
  process 2. We blink to show or hide emotion 3. We blink in the middle of a fast head turn."
- p.10: "If your character's head does a really fast head-turn, drop a blink in there near the middle or near the end of
  the head turn."
- p.8: "'animated characters should always blink every two seconds.' Well, that's just about the worst advice I ever
  got." Also: "Rapid blinks can make a character feel shy, nervous, uncomfortable, relieved [...] Not blinking at all
  can feel angry, stoned, dead, or super intense."
- p.10: (scared, searching) "you're going to be taking the 'no blinks at all' approach [...] you could get away with not
  blinking for even 10 seconds or more." When hope arrives: "what does he do first? He blinks. [...] his thought-process
  has shifted."
- p.9: "Never move ANYTHING on a character unless you know exactly why you're moving it."

### (b) Principle
The audience reads thought on the face, so **put the face change where the face is still**. Turn, arrive, let it sink
in (a held beat), **then** change, and mark the thought shift with a blink. Never change expression mid-turn, and never
in the first or last 8 film frames of a shot, which at our 30 fps is **10 frames**. Blinks are punctuation for thought,
not a metronome.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-P1a** | No key expression change during a head turn. | `cloud/blender/acting.py` (head yaw/pitch from `poses`/`verbs`) + `cloudrig_adapter.face_at` (emotion keys, `blend` 10 f) | `turn_then_change: [{shot, turn:{from,to}, settle_frames, change:{from,to}, emotion_from, emotion_to}]` | Over the emotion blend window [k, k+blend] of every `face.emotion` key in the shot, head angular speed ≤ 40°/s [HOUSE; "fast head movement"]. FAIL on overlap with a declared `turn` window. **SRC**: p.19 "Never ... mid-motion. Ever." |
| **CAN-P1b** | Turn, settle, then change. | acting.py / cloudrig_adapter | `turn_then_change.settle_frames` | `change.from − turn.to` = `settle_frames`, which must be ≥6 f @30 (0.2 s) [HOUSE; p.19 "a moment to stare ... for it to sink in"]. Alternative allowed: the change ends ≥4 f **before** `turn.from` ("just before the head turn", p.19), with `mode: "pre_turn"`. |
| **CAN-P1c** | No expression change, pose change or direction change in a shot's first or last 8 film frames. | acting.py `_env` in/out + face emotion keys; checked by shot_validator | per-shot `hero.poses[].from/in`, `stance_changes`, `face.emotion` | No emotion key onset, pose onset or stance change in [shot.from, shot.from + 10) or (shot.to − 10, shot.to] [**SRC→30fps**: p.20 "first or last 8 frames" at 24 fps = 0.33 s = 10 f @30]. Exemption: `match_action:true`, where the pose continues across the cut from the previous shot. |
| **CAN-P1d** | A blink marks the thought shift. | `cloudrig_adapter.face_at` `extra_blinks` | `turn_then_change.change.from` | A blink starts within [change.from − 4, change.from + 3] f [HOUSE; p.9 "most important use of a blink"]. Exception: `noBlink` intensity beats (fear/transfixed, p.8/10), capped at 300 f (10 s @30) [SRC p.10]. |
| **CAN-P1e** | Blink inside a fast head turn. | face.blink_at / `extra_blinks` | `turn` | Turns ≥45° in ≤10 f get a blink whose closure peaks between 50 % and 100 % of the turn [SRC p.10 "near the middle or near the end"; HOUSE 45°/10 f]. |
| **CAN-P1f** | During bounce or locomotion, a change goes at the arc apex. | acting.py verbs (`lurch`, jog) | `turn_then_change.change.from` | When the head has vertical bob > 2 cm in the window, the change onset is within ±2 f of a local head-height maximum [SRC p.20; HOUSE numbers]. |
| **CAN-P1g** | The sound-off test. | qc/vision.py (manual MANUAL item until automated) | none | Reviewer: with audio muted, can the frame of the thought landing be pointed to? The plan must log `turn_then_change` for the reserved CU (CAN-C2) at least. |
| **CAN-P2a** | Blinks are not a metronome. | face.blink_at seed | none | Coefficient of variation of inter-blink intervals per shot ≥0.35. No fixed 60-frame (2 s) cadence [SRC p.8; HOUSE number]. |
| **CAN-P2b** | Eyes lead. | cloudrig_adapter gaze + acting head | `face.gaze` | For gaze shifts ≥15° paired with a head turn, the eye onset precedes the head onset by 2-6 f [HOUSE; p.18 "eyes ... first", lessons L011/L018]. |
| **CAN-P2c** | Nothing moves without a reason. | acting.py verbs | `verbs[].why` | Every verb/pose carries `why` (beat or stimulus). Pure noise layers ("dirt") are exempt [SRC p.9]. |
| **CAN-P2d** | Hands have shapes and correct palms. | cloudrig_adapter `_clear_hand` | none | Lessons L010/L017 checks (unchanged). |

---

## 7. Russell Carpenter ASC, "Passion for the Craft" (American Cinematographer, Feb 1 2018, Jon Silberg): CAN-T1, CAN-L2

### (a) Key passages
- Photo caption: "A large model of the ill-fated luxury liner HMS Titanic was set up for lighting tests during prep [...]
  Of note is the Mylar sheeting around the model, simulating water, which rendered an accurate suggestion of how the
  huge, to-be-built ship set's complex practical lighting would play once it was positioned in the tank facility at Fox
  Baja Studios."
- James Cameron: "He's very collaborative and very meticulous in terms of testing [...] figuring out filters and stock.
  On *Titanic*, we decided that every white [light] would have Half CTO gel on it, so the blue would be richer when we
  timed it back to white. We didn't know that would be such an important aspect of the look until we tested a lot of
  things and discovered that together." Also: "These days, he's testing to create excellent LUTs."
- Cameron: "I remember liking his nights. Some cinematographers say nights need to be dark. I believe you use cues like
  color temperature to show that it's night, but you open it up and see into the shadows."
- Carpenter, on his gaffer: the set "looked like a ship from the outside, but [...] it was miles and miles of cables,
  and thousands of lights." (CML p.138 adds: "Cameron added twice as many practicals to the deck of the Titanic.")

### (b) Principle
The look of **practical light on water** is the hardest and most expensive thing to fix late, so it is **tested
first** in the cheapest stand-in: a model, its practicals, and a reflective stand-in for water. This is done in prep,
before the big build. The test is also where look decisions are *discovered* (Half CTO → richer blue night), and those
decisions become locked parameters (gels, LUT), not per-shot tweaks.

### (c) Rules
| ID | Rule | Engine | Director field | Automatic check / threshold |
|---|---|---|---|---|
| **CAN-T1a** | A look-dev test frame exists before any spray, weather, FX or animation spend. | previs look-dev step: `cloud/blender/test/yachtsea_lookdev.py` (views hull/deck/reef/wide) | `lookdev_test: {frame_png, view, elements:[boat, one_practical, water], lighting_preset, water_material, hull_material, hash, approved_by, approved_at}` | The render queue refuses shots whose `env` uses `storm`/`oceanfx` spray/funnel/rain, or that have baked acting, until `lookdev_test.approved_at` is set **and** `hash` matches the current (lighting preset params + water + hull material) hash. FAIL [SRC sequence; the gate is HOUSE]. |
| **CAN-T1b** | The test isolates the three elements. | yachtsea_lookdev.py (dressing off) | `lookdev_test.elements` | The test scene has exactly 1 practical lit (one deck lamp/binnacle), no actors, no FX, sea state ≤ the episode's calmest [SRC "test boat + one deck lamp + water"]. |
| **CAN-T1c** | The lamp's light reads on the water. | qc/plates.py on the look-dev frame | `lookdev_test.frame_png` | Within the water mask below the lamp, the reflection streak's mean luma ≥3× the water mask's mean. Water mean luma ≥0.02 (not a black hole). The lamp itself is not clipped over >0.2 % of the frame [HOUSE; ASC caption "accurate suggestion of how ... practical lighting would play"]. |
| **CAN-T1d** | Look decisions found in the test become locked parameters. | lighting.py presets / grade LUT | `lookdev_test.locks: {practical_kelvin, key_color, lut}` | After approval, per-shot overrides of the locked keys need `cheat_reason` (feeds CAN-L2a) [SRC: Half CTO "important aspect of the look"]. |
| **CAN-T1e** | Night is cued by colour, and shadows stay open. | lighting.py + grade | none | See the Cameron corollary under source 2: hero face shadow-side ≥0.03 luma, key/practical hue separation ≥120° (L5). |

---

## 8. Worked examples

### 8.1 *Sentinel*: yacht aground at North Sentinel, night (`episodes/sentinel/episode.json`, 30 fps, S01-S11)

**Look-dev first (CAN-T1).** Before the reef surf, the spray or any acting bake, run
`yachtsea_lookdev.py --views hull,reef` with only the stern deck lamp lit, the moon key, and a calm sea. Approve the
frame when the lamp's warm streak on the black water is ≥3× the water mean (T1c), the hull's waterline is readable, and
the reef breaker line catches the moon. Lock `practical_kelvin`/`key_color` in `lookdev_test.locks`.

**Discovery map (CAN-L1)**, illustrative:
```json
"discovery_map": [
  {"detail": "reef breakers ahead", "shot": "S02", "frame": 380, "light_reveal": {"source": "moon", "kind": "glint"},
   "subordinate": ["island tree line"]},
  {"detail": "fires inland in the trees", "shot": "S03", "frame": 520,
   "light_reveal": {"source": "practical:village_fire", "kind": "practical_pool"}, "subordinate": ["forest", "beach"]},
  {"detail": "split hull plank at the waterline", "shot": "S04", "frame": 790,
   "light_reveal": {"source": "moon", "kind": "reflection"}, "subordinate": ["forest stays dark"]}
]
```
- S03: the fires sit ≥1 stop under the hero face (L3d), as small warm points in a black tree mass. The forest has no
  fill (L1d blacks ≥15 %). The fires flicker, and every other element is still during the reveal (L1e). The hero's
  gaze is still on the instruments until the audience has had ≥2 s with the fires (CAN-S1/E1b), then he looks
  (L1f/E1c).
- S04 cost: the damage is revealed by the **moon's reflection off the water onto the hull**, not by a new light, so L2c
  holds (moon motive).

**Action order (CAN-E1)**, across S02 → S04:
`obstacle_audience` = S02 wide (the breaker line glints ahead of the drifting yacht; he is looking aft) →
`obstacle_character` = he hears it, turns, and the POV shows the breakers (look → POV, E1c) →
`impact` = S04 "CRUNCH" →
`cost_revealed` = a ≥75 f held shot on the split plank (E1d).

**Impact handheld (CAN-H1)** on S04:
`"impact_handheld": {"shot": "S04", "impact_frame": 700, "escape_frames": 4, "lag_frames": 5, "recover_frames": 12, "amplitude_deg": 6}`.
The hero's chest leaves the safe area at 702-704, aim error peaks at 705, and he is re-centred by 717. H1 and C11 are
exempt over 700-721 (H1f).

**Reserved close-up (CAN-C2):** S06, "do NOT go ashore". The beat where he hears something inland and changes his mind.
`"reserved_close_up": {"beat": "S06", "shot": "S06", "reason": "decision: stays aboard"}`. No other hero-face CU in that
sequence. It lasts ≥45 f (C2c).

**Turn then change (CAN-P1)** in S06 (shot 1085-1388):
`{"turn": {"from": 1140, "to": 1152}, "settle_frames": 8, "change": {"from": 1160, "to": 1172}, "emotion_from": "curious", "emotion_to": "resolve"}`.
The turn is 70° in 12 f, so it is "fast" and gets a blink at 1146-1150 (P1e). The emotion key is placed at 1160, after
the head has stopped (P1a/b). A thought blink starts at 1158 (P1d). Nothing changes before 1095 or after 1378 (P1c).

**Night continuity (CAN-L2)** at the wide→close cut into S06: face luma Δ ≤ +0.5 EV versus the S05/S06 wide, the key
stays moon-blue from three-quarter back, the background may only get darker, and the face shadow side stays ≥0.03.
**S09 "kill the lights"** is a declared `light_event: "practicals_off"`. After it, key = moon only, and the CU face
must *drop* with the wide (L2a/L2b): no relight to keep the face pretty.

### 8.2 *Waterspout* at sea, night (`episodes/waterspout/shotplan.json`, 38 shots H01-H38, 30 fps)

**Look-dev (CAN-T1).** Test the sloop, the **warm compass binnacle** (the one practical) and night water *before* the
`fx_waterspout_funnel`, `fx_spray_ring` and storm. The shotplan still has these as placeholders, which is exactly when
T1 must pass. The lightning (`lightning_per_s` 0.12) is a `light_event` and is tested in a second look-dev pass, never
in the first.

**Discovery map:** H06 "the spiral he can't see" (f252), `source: moon`, `kind: silhouette`: a dark disc against the
moonlit sea, subordinate to the hero (L1c, "hint at a shape"). Then H07 "Lightning: he sees it" (f338),
`source: lightning`, `kind: lightning`. And H20 (f1065), where the lightning strobes the full funnel.

**Action order:** `obstacle_audience` = H06 (f252), `obstacle_character` = H07 (f338). The gap is 86 f = 2.9 s ≥ 60 f
(E1b PASS). The climax is `impact` = H29 "whip into the mature vortex" (`motivation: impact`, so H1a requires an
`impact_handheld`; H29 is marked `insert`, but H1 still applies), and `cost_revealed` = H35 "It tears past the stern"
(92 f, ≥75 f PASS).

**Reserved close-up, found by applying the canon to the current plan.** Hero-face CUs are H07 (S05) and H32 (S18).
They are in different sequences, so C2a passes technically. But C2b asks whether each lands on a knowledge or decision
change:
- H32, "Hold: step three saves you", is the decision. It is the reserved CU.
- H07 is the *character sees obstacle* step. **Recommendation:** make H07 an MCU, or declare it `extra_cu_reason`, so
  that H32 keeps its value.

H33 is an ECU insert of the compass and hands, so it is exempt.

**Turn then change on the current plan, as P1c checks it:**
- **H07** (338-411): `stance_changes: [[345, "brace"]]` falls 7 f into the shot. That is inside the 10 f bookend, so it
  **FAILs P1c**. Fix: move it to ≥348, or start it in H06's tail as `match_action`.
- **H31** (1734-1794): `look_back` from 1734 with `in: 3, ease: snap`, a direction change on frame 0. It **FAILs P1c**
  unless it is flagged `match_action` from H30's `point_ahead`.
- **H33** (1836): `look_down` from frame 0 of the shot. It needs `match_action` from H32's `look_down` (1805-1836),
  which it is, so it is exempt once flagged.
- **H22** "fear lands on his face" (`dolly_zoom`): the fear emotion key must sit after any head motion has settled
  (P1a/b), with a blink at onset (P1d).

**Impact handheld on H29** (1628-1669):
`{"impact_frame": 1634, "escape_frames": 3, "lag_frames": 4, "recover_frames": 10, "amplitude_deg": 8}`. The whip pan
lands *late* on the vortex rather than dead-centre. The rest of the storm uses baseline `handheld` ≤0.12 (H1e), and
H14/H36 `handheld_subtle` stay at baseline.

**Night continuity:** the binnacle is the in-frame practical in the helm CUs (H32/H33). Under L2c the face key on H32
comes from the binnacle side, or within 45° of it. The wide's moon key is kept as the rim, ≤1.5× key (L3c). The H32 face
stays within +0.5 EV of H31 (L2b).

---

## 9. Consolidated rules table

| ID | Short rule | Engine(s) | Director field(s) | Check / threshold | Basis |
|---|---|---|---|---|---|
| CAN-L1a | Discovery map per sequence | director schema, director/checks.py | `discovery_map[]` | ≥1 entry, frame ≥10 f into shot, source is a built light | Calahan §3, §8 |
| CAN-L1b | One focal point dominates at reveal | lighting.py, qc/plates.py | `discovery_map.detail` | ≥50 % of top-2 % luma in mask; contrast ≥1.5× others | Calahan §3.2 [HOUSE] |
| CAN-L1c | Detail subordinate before reveal | lighting.py | `discovery_map.frame` | pre-reveal luma ≤0.5× reveal | Calahan §3.7, §4.1 [HOUSE] |
| CAN-L1d | Low key: dark not murky | lighting.py, qc/plates.py | `env.lighting` | well-lit 2-30 %, hot ≥0.5 % ≥0.75, blacks ≥15 % ≤0.04 | Calahan §6, §12; CML pp.137/139 [HOUSE] |
| CAN-L1e | Revealed thing is sole mover | acting.py, camera_presets.py | `discovery_map.frame` | no hero onsets in [f−6, f+15] | Calahan §3.2.7 [HOUSE] |
| CAN-L1f | Eyeline points at discovery (or away, audience-first) | acting gaze | `face.gaze` | ±20° by f+8 / ≥45° away | Calahan §3.6 [HOUSE] |
| CAN-L2a | Key holds across cut | lighting.py --check | `cheat_reason`, `light_event` | Δaz ≤15°, Δel ≤10°, same preset | Calahan §9 [HOUSE, existing L2/L8] |
| CAN-L2b | CU not daylight vs wide | lighting.py, qc/plates.py | `size`, `reserved_close_up` | face Δ +0.5/−1.0 EV, key:fill ≥4:1, CU bg ≤ wide bg | CML p.138-139; Calahan §9 [HOUSE] |
| CAN-L2c | Motivated, one job per light; practical sets direction | lighting.py `_tag` | `key_motivation` | tag present; ≤45° to in-frame practical within 4 m | Calahan §4.3, §4.4 [HOUSE] |
| CAN-L2d | Night key three-quarter back, little fill, nothing by lens | lighting.py presets | `key_az`, `fill_ratio` | key az 90-150° vs camera; nothing ≤20° of axis | Calahan §4.6.2.2, §6, §12 |
| CAN-L2e | Moving lights on moving things | lighting.py | none | animated light ⇒ animated parent | Calahan §12 |
| CAN-L2f | Practicals carry the set, each motivated | lighting.py, props | `world.practicals[]` | ≥2 visible in night wides or `practicals_off` | CML pp.138, 141, 259 [HOUSE] |
| CAN-L2g | Fire supported same colour; cool moon | lighting.py | `practical_kelvin`, `key_color` | ±300 K; hue sep ≥120° (L5) | CML p.138 [HOUSE] |
| CAN-L3a | Planes separate by value or colour | lighting.py, qc/plates.py | none | adjacent planes ≥0.5 EV or ≥25° hue | Calahan §5.1 [HOUSE] |
| CAN-L3b | Rim on dark subject vs dark ground | lighting.py hero rig | none | edge ≥1.6× ring on ≥35 % length | Calahan §3.12, §5.6 [HOUSE] |
| CAN-L3c | Rim not overused, no blue wash | lighting.py | `rim_energy` | rim ≤1.5× key | Calahan §4.6.2.4; CML p.140 [HOUSE] |
| CAN-L3d | Background accents ≥1 stop under | lighting.py | none | ≤0.5× hero face luma | **CML p.140 [SRC]** |
| CAN-L3e | Warm subject / cool ground; aerial perspective | lighting.py | none | hue ≥30°; far contrast < near | Calahan §5.4, §5.6 [HOUSE] |
| CAN-L3f | CU shallow; consistent CU lens | camera_presets.py, shot_validator C14 | `dof`, `lens` | CoC ≥4 px; ±10 mm | Calahan §5.3, §3.3.7 |
| CAN-L3g | Night shots not deep-focus | camera_presets.py | `fstop` | MS+ ≤ f/2.8 | CML p.141 [HOUSE] |
| CAN-C1a | Wide first, re-establish | shot_validator C3/C4 | `direction.location` | first 2 shots; ≤6 tighter | Reisz p.49, p.56; UW [UNVERIFIED-SRC] |
| CAN-C1b | Establishing frame holds hero + vessel + threat | shot_validator CTX | `establishes[]` | each ≥60 % in on ≥80 % frames; ≥36 f | AM p.20; Calahan §3.4 [HOUSE] |
| CAN-C1c | Screen direction | shot_validator C5 | none | 180° per sequence | existing |
| CAN-C2a | One reserved CU per sequence | director schema, shot_validator C1/C2 | `reserved_close_up` | 1 hero-face CU/sequence; CU+ECU ≤25 % | UW [UNVERIFIED-SRC]; Reisz p.60 |
| CAN-C2b | Reserved CU on knowledge/decision change | director/checks.py | `reserved_close_up.beat`, `knowledge_timeline` | beat changes knows/can-act | CAN-S2 link |
| CAN-C2c | Reserved CU long enough for the thought | shot_validator C9 | `turn_then_change` | ≥45 f, ≤6 s | AM pp.19-20 [HOUSE] |
| CAN-E1a | Four information steps in order | director schema, checks.py | `action_order{}` | all present, strictly ordered | Reisz Ch.3 pattern + SOURCES |
| CAN-E1b | Audience lead felt | checks.py | `action_order` | ≥60 f; hero gaze ≥45° off | Reisz p.60; Hitchcock [HOUSE] |
| CAN-E1c | Look → POV → reaction | shot_validator, acting gaze | `obstacle_character` | gaze onset, then POV/CTX, then reaction ≥10 f | **Reisz pp.50-54 [SRC pattern]** |
| CAN-E1d | Cost in its own held shot, light-revealed | shot_validator C9, discovery_map | `cost_revealed` | ≥75 f + discovery entry | Reisz p.50 shot 7 (3.75 s) [HOUSE] |
| CAN-E1e | Don't out-cut comprehension | shot_validator C9/C4 | none | ≥18 f unless insert; re-establish ≤6 | **Reisz p.49** |
| CAN-E1f | Close static shorter than moving long | shot_validator P1 | none | median CU < median moving WS | **Reisz p.62 [SRC direction]** |
| CAN-E1g | Cut rate follows tension | shot_validator P1 | `sequence.tension` | mounting: last-third ASL ≤0.8× first | Reisz p.55, p.61 [HOUSE] |
| CAN-E1h | Each action cut = new angle or parallel | shot_validator | none | ≥1 size class or ≥30° az | Reisz p.56, p.62 [HOUSE] |
| CAN-E1i | Compressed time needs a cutaway | checks.py | `time_cut` | reaction/parallel between | **Reisz p.61** |
| CAN-H1a | Impact declares reactive handheld | director schema, camera_presets.py | `impact_handheld{}` | required on impact shots | Greengrass [UNVERIFIED-SRC]; DGA 2007 |
| CAN-H1b | Subject escapes frame | camera_presets impact layer, shot_validator | `escape_frames` | 2-6 f, ≥30 % bbox out, ≤2 f after impact | [HOUSE] |
| CAN-H1c | Camera catches up late | camera_presets | `lag_frames`, `recover_frames` | lag 3-8 f; recover ≤15 f; overshoot ≤30 % | [HOUSE] |
| CAN-H1d | No locked-off impact | shot_validator P7 | none | ≥8°/s around impact | [HOUSE] |
| CAN-H1e | Shake event-driven | camera_presets `handheld` | `camera.handheld` | baseline ≤0.12; impact RMS ≥3× baseline | [HOUSE] |
| CAN-H1f | Validator exemptions for impact window | shot_validator H1/C11, qc/plates.py | `impact_handheld` | exempt [impact, +escape+lag+recover] | engine consistency |
| CAN-H1g | No impact shake on reserved CU | checks.py | `reserved_close_up` | not the same shot | [HOUSE] |
| CAN-P1a | No expression change during turn | acting.py, cloudrig_adapter.face_at | `turn_then_change[]` | head ≤40°/s over emotion blend | **AM p.19 [SRC]**, 40°/s [HOUSE] |
| CAN-P1b | Turn, settle, then change (or pre-turn) | acting.py, cloudrig_adapter | `settle_frames` | ≥6 f, or ends ≥4 f before turn | AM p.19 [HOUSE] |
| CAN-P1c | No change in first/last 8 film frames | acting.py, face keys, shot_validator | `poses`, `stance_changes`, `face.emotion` | none in first/last **10 f @30** unless `match_action` | **AM p.20 [SRC→30fps]** |
| CAN-P1d | Blink marks thought shift | cloudrig_adapter `extra_blinks` | `change.from` | blink in [−4, +3] f; `noBlink` ≤300 f | **AM pp.9-10** [HOUSE window] |
| CAN-P1e | Blink in a fast head turn | face.blink_at | `turn` | ≥45° in ≤10 f ⇒ blink at 50-100 % of turn | **AM p.10 [SRC]** |
| CAN-P1f | Change at bounce apex | acting.py | `change.from` | ±2 f of head-height max | **AM p.20 [SRC]** |
| CAN-P1g | Sound-off test | qc/vision.py / manual | none | thought frame identifiable | AM p.19; SKILL |
| CAN-P2a | Blinks not a metronome | face.blink_at | none | interval CV ≥0.35 | **AM p.8** [HOUSE number] |
| CAN-P2b | Eyes lead the head | cloudrig_adapter gaze | `face.gaze` | eye onset 2-6 f before head | AM p.18; L011/L018 [HOUSE] |
| CAN-P2c | Nothing moves without a reason | acting.py | `verbs[].why` | every verb has `why` | **AM p.9** |
| CAN-P2d | Hands shaped, palms correct | cloudrig_adapter | none | L010/L017 | lessons |
| CAN-T1a | Look-dev test before FX/weather/animation spend | yachtsea_lookdev.py, render queue | `lookdev_test{}` | approved + hash match, else refuse FX/acting renders | **ASC 2018 caption** [gate HOUSE] |
| CAN-T1b | Test isolates boat + one lamp + water | yachtsea_lookdev.py | `lookdev_test.elements` | exactly 1 practical, no actors/FX | ASC 2018; SOURCES |
| CAN-T1c | Lamp reads on water | qc/plates.py | `lookdev_test.frame_png` | streak ≥3× water mean; water ≥0.02; clip ≤0.2 % | [HOUSE] |
| CAN-T1d | Test findings become locks | lighting.py presets/LUT | `lookdev_test.locks` | overrides need `cheat_reason` | **ASC 2018 (Half CTO)** |
| CAN-T1e | Night by colour, open shadows | lighting.py, grade | none | face shadow ≥0.03; L5 ≥120° | **ASC 2018 (Cameron)** [HOUSE number] |

**Implementation status (2026-11-22).** Already automated: L2a (lighting.py L2/L8/L5), C1a/C1c/C2a-partial/L3f-lens
(shot_validator C1-C5, C9, C14, CTX, P1, P7), and the plate flicker/clipping checks (qc/plates.py). Everything else is
**MANUAL** in `python3 -m factory.canon pass` until `factory/canon/checks.py` lands. Each new check needs a golden and
a failing stress case (`factory/lessons/README.md`). The director schema still has to add `discovery_map`,
`reserved_close_up`, `action_order`, `impact_handheld`, `turn_then_change`, `lookdev_test`, `establishes`,
`match_action`, `time_cut` and `sequence.tension`.
