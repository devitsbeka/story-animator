# PIXAR RECIPE — Director Rules for the Animation Factory

Target: 60–120 s, 9:16 (1080x1920), stylized 3D (Blender bpy + Remotion), survival/explainer genre.
Default frame rate: **24 fps** (all frame counts below assume 24 fps unless stated; convert with `frames = seconds * fps`).

How to read this file:
- **RULE** = enforce. **HEUR** = default heuristic, may be overridden with a logged reason.
- `[src]` tags point to sources; full URL list at the bottom. Where a number is a house heuristic rather than a sourced fact, it says so.
- Every section ends with a **CHECKLIST** of machine-validatable assertions (IDs are stable so validators can reference them).

House rules that override studio convention:
- **H1 Hero centered.** In 9:16 the hero's face/eyes sit on the vertical center line (x = 0.5 ± 0.08 of frame width). Rule-of-thirds is applied *vertically* instead: eyes on the upper-third line (y ≈ 0.33–0.42 from top).
- **H2 Safe zones.** Keep eyes and key action out of the top 12% and bottom 20% of frame (platform UI + subtitles).
- **H3 No AI video.** Everything is procedural/keyframed; rules below are expressed as parameters the code can set.

---

## 1. Pipeline Stages, Artifacts and Gates

Pixar's order: story → storyboards → story reel (animatic with scratch dialogue, temp FX) → layout (camera + staging; "where preproduction ends and production starts") → animation → lighting → effects → rendering/comp → final edit/sound [Bordwell, Pixar kitchen; Making of Toy Story; Cornell lecture]. Stages overlap, but each gate locks something so downstream work is not thrown away.

| # | Stage | Artifact (factory file) | Locked at gate | Gate reviewer check |
|---|-------|------------------------|----------------|---------------------|
| 0 | Idea | `idea.json` (one line) | — | — |
| 1 | Story | `story.json`: logline, story spine (8 lines), stakes, ticking clock, ending, "what should he do" answer list | Premise, ending, the 3–6 survival decisions and their factual correctness | Spine is causal ("because of that"), not episodic ("and then") [Coats #4] |
| 2 | Script | `script.json`: beats with VO/dialogue text, on-screen text, est. duration | Words (VO) and beat order | Total VO at 2.3–2.8 words/s (HEUR) fits 60–120 s |
| 3 | Beat board | `beatboard/*.png` + `beats.json` (1 still per beat; shot size, angle, hero pose) | Visual idea of each beat | Every beat has a readable silhouette thumbnail |
| 4 | Story reel / animatic | `reel.mp4` + `edl.json` (shot list with in/out frames, scratch TTS, temp SFX) | **Timing** (shot count, shot durations ±10%) | Watch-through; intensity graph (§3.8) drawn |
| 5 | Color script | `colorscript.png` + `palette.json` (1 key per beat/sequence: dominant hue, saturation, value key, light direction) | Color/mood arc per act | Saturation/value arc matches intensity graph |
| 6 | Layout | `layout/*.blend` + `cameras.json` (lens mm, height, move, blocking marks) | **Camera** (lens, framing, move), character marks, set dressing | 180° line respected; establishing rule met |
| 7 | Animation | blocking → spline → polish passes | **Performance** | Acting beats per shot present (§5) |
| 8 | Lighting | key-shot lighting → master/sequence rig → shot overrides | **Light direction, ratios, color per sequence** | Continuity review of whole sequence in order |
| 9 | FX | water, spray, fire, rain, particles | Sim caches | FX reads in silhouette, does not hide eyes |
| 10 | Render/comp | EXR passes → comp (fog, glow, DOF, grain) | Pixels | Exposure continuity (§4) |
| 11 | Edit/sound/grade | Remotion composition, final mix, AgX view + look | Final | Loudness, captions, safe zones |

Key practices to copy:
- **The reel is the movie.** The story reel uses storyboards, scratch dialogue and rough FX and is iterated until it plays; only then does production start [Making of Toy Story PDF].
- **Layout lights early.** On Incredibles 2, lighting built set-level light setups that layout used to guide the eye; on Toy Story 4, nearly all departments view shots *in the context of lighting* [RenderMan "Incredible Cinematography"; Pixar Light Pruning TS4].
- **Lighting by sequence, not shot.** Production designer + lighting DP pick **key shots**, paint **color keys**, a **master lighter** builds the sequence rig (1–4 weeks), then shot lighters inherit it; shots are judged in sequence order [fxguide Inside Out]. Pixar's *Win or Lose* lit whole sections with one unified setup (Katana LiveGroups) [Foundry]; Inside Out 2 used a sequence-global setup with per-shot overrides [Foundry IO2]. Blender Studio: light key shots first; every shot must link to adjacent shots in intensity, color and style [Blender Studio lighting guide].
- **Broad to fine.** Start simple; add complexity only when images "aren't adding up" [fxguide Inside Out].

**CHECKLIST §1**
- [ ] P1 Every gate artifact exists before the next stage starts (file existence check).
- [ ] P2 After gate 4, sum of shot durations within ±10% of reel; shot count within ±15%.
- [ ] P3 After gate 6, no camera lens/height change > 10% without a `layout_change_reason`.
- [ ] P4 Every sequence has ≥1 designated `key_shot` lit first; all other shots reference its `light_rig_id`.
- [ ] P5 Survival advice in `story.json` has a `fact_source` per decision (explainer genre credibility).

---

## 2. Story Structure for 60–120 s

### 2.1 Story spine (mandatory skeleton) [Coats #4]
```
Once upon a time ___. Every day ___. One day ___.
Because of that ___. Because of that ___. Until finally ___.
(Ever since then ___.)
```
- RULE: each "Because of that" must be caused by the prior line. If two consecutive beats read as "and then", merge or cut (momentum loss) [Coats; No Film School].
- Other Coats rules made machine-checkable:
  - #1 admire trying over succeeding → hero must *attempt* ≥2 actions, at least one fails.
  - #2/#6 hero's comfort zone is challenged; what is he worst at? → hero has a stated `flaw` or `limitation` (e.g. exhausted, no radio, wounded).
  - #14/#22 essence: `story.json.essence` ≤ 20 words.
  - #19 coincidences to get *into* trouble are fine; coincidences to get *out* of it are cheating → resolution must result from hero's choice/skill.
  [Coats list via Fast Company / Farnam Street]

### 2.2 Act map for vertical short form (HEUR, % of runtime)

| Phase | % runtime | 60 s | 90 s | 120 s | Content |
|------|-----------|------|------|-------|---------|
| Hook (cold open) | 0–5% | 0–3 s | 0–4 s | 0–5 s | Danger image + question. The scroll decision happens here. |
| Setup / "Every day" | 5–15% | 3–9 s | 4–13 s | 5–18 s | Who, where, normal, what he wants |
| Inciting incident | at 10–20% | ~8 s | ~12 s | ~18 s | Hull hits reef; the problem becomes unavoidable |
| Escalation (2–4 beats) | 15–75% | 9–45 s | 13–68 s | 18–90 s | Each "what should he do" step = decision → consequence → new obstacle; stakes rise every beat |
| Climax | 75–90% | 45–54 s | 68–81 s | 90–108 s | Hardest choice, highest visual intensity |
| Resolution + takeaway | 90–100% | 54–60 s | 81–90 s | 108–120 s | Outcome + 1-line lesson card |

- Inciting incident may be **in** the hook (cold open, then rewind "3 hours earlier") — allowed if the setup ≤ 15%.
- Explainer genre: each escalation beat teaches exactly **one** actionable rule; max 5 rules per episode.

### 2.3 Stakes and suspense toolkit
- **Hitchcock bomb (suspense > surprise).** Show the audience the threat *before* the character knows → seconds of surprise become minutes of suspense [Hitchcock/Truffaut via No Film School, Bordwell]. Factory form: insert a `threat_reveal` shot (e.g. torches on the beach, a canoe silhouette, the tide rising) the hero has not yet seen; hold it ≥1.5 s.
- **Dramatic irony**: same mechanism; audience knowledge > hero knowledge. Use at least once per episode.
- **Ticking clock**: a visible, rising, countable constraint (tide height, dawn approaching, water in the cabin, battery %). RULE: clock introduced by end of setup and re-shown ≥2 more times, each time worse.
- **Reveals**: withhold-then-show. Plant/payoff: anything that solves the climax (flare, life raft, VHF) must be *planted on screen* in the first 40% (Coats #19 corollary; Chekhov).
- **Stakes ladder**: physical (injury) → legal/ethical (protected tribe, exclusion zone — never harm or contact) → mortal. Each escalation beat must raise at least one rung or add a new kind.
- **Question in the first 3 s** ("What would you do?") and **answer withheld** until the beat that pays it off.

**CHECKLIST §2**
- [ ] S1 `story.json.spine` has all 8 slots filled; ≥2 "because of that" lines.
- [ ] S2 Inciting incident timestamp ≤ 20% of runtime.
- [ ] S3 Climax starts between 70% and 90% of runtime.
- [ ] S4 ≥1 `threat_reveal` shot precedes the hero's awareness of the threat by ≥ 3 s.
- [ ] S5 Ticking clock shown ≥ 3 times with monotonically worsening value.
- [ ] S6 Every climax-solving prop appears on screen before 40% runtime.
- [ ] S7 Resolution is caused by a hero action logged in `beats.json` (no deus ex machina).
- [ ] S8 Hook (first 3 s) contains motion + hero + danger cue; no title card longer than 1 s at t=0.

---

## 3. Shot Design and Camera Language

### 3.1 Shot sizes (relative to 9:16 frame height) and use

| Code | Size | Framing (vertical) | Use for |
|------|------|-------------------|---------|
| EWS | Extreme wide | Hero < 10% frame height | Isolation, scale, establishing (island at night, yacht on reef) |
| WS | Wide / full | Head-to-toe ≈ 50–80% | Geography, blocking, physical action |
| MWS/MS | Medium | Waist/hips up | Default "doing" shot, procedural steps of the explainer |
| MCU | Medium close | Chest up | Decision moments, VO-heavy beats |
| CU | Close-up | Head + shoulders | Emotion peaks, realizations |
| ECU | Extreme CU | Eyes / hands / object detail | Insert: knot, gauge, flare cap, eyes darting |
| OTS/POV | Over-shoulder / point-of-view | — | Bridge objective → subjective; show what he sees [Mascelli] |

- Mascelli's three camera relationships: **objective** (audience observer), **subjective** (POV), **point-of-view/intermediate** (OTS) [Mascelli, Five C's]. Move to subjective as tension rises.
- **Close-up economy**: CUs are strongest when rare. Vertical video tempts constant CU; resist it.
- Vertical-format note (HEUR): in 9:16, a "wide" reads smaller on phones — EWS needs a strong silhouette or practical light to locate the hero.

### 3.2 Distribution targets (HEUR, per episode)
- EWS+WS: 25–40% of shots. MS/MCU: 35–50%. CU+ECU: **≤ 25%**. POV/OTS: ≥ 1 per escalation beat when there is a threat.
- Never more than **3 consecutive** CU-or-tighter shots.
- Climax may raise CU share locally to 40% (intensity via contrast in shot size, §3.8).

### 3.3 Establishing / re-establishing
- RULE: new location → establishing (EWS/WS) within the **first 2 shots** of that location.
- Re-establish with a WS after ≥ 6 consecutive shots tighter than WS, or after any time jump, or when a new character/threat enters the space.
- Keep a persistent geography anchor (moon position, island silhouette, the yacht's mast light) on the same side of frame throughout a sequence.

### 3.4 Screen direction, 180° rule, eyelines
- Each sequence defines `action_line` (2D vector in plan view between hero and the main subject, e.g. hero ↔ island). Camera stays on one side. Cross only by (a) a shot where the camera visibly moves across, (b) a neutral on-axis shot as a bridge, or (c) a cut on a hero's turn that resets the line [Mascelli: continuity].
- Screen direction encodes story: travel toward safety in a consistent direction (HEUR: left→right = progress, right→left = retreat/threat). The threat (shore) owns one side of frame for the whole episode.
- Eyelines: in a look → POV pair, the looker's gaze direction and the POV subject's frame position must match (looking screen-right → object enters from right/occupies right). Gaze angle off lens: 10–30° for "observed"; direct-to-lens only for deliberate address to viewer (explainer "what would you do?" moment allowed once).

### 3.5 Lens choice (35 mm full-frame equivalent; set `camera.data.lens` with sensor 36 mm)
Pixar DPs choose lenses and moves "the way a live-action DP would" and since Inside Out model real lens sets; on WALL-E layout ran anamorphic lens wedge tests and framed chaos around the hero to show he was out of his element; on *Win or Lose* lens and movement "support our character's emotion" [Collider Patrick Lin; AWN WALL-E; Pixar Win or Lose paper]. Practical table (HEUR, industry convention):

| mm | Feel | Use |
|----|------|-----|
| 14–21 | Distorted, vast, unstable when close | Isolation EWS, panic POV close to hero, cramped cabin |
| 24–28 | Environmental, energetic | WS action, establishing in 9:16 |
| 35 | Neutral-wide, "with him" | Default MS walk-and-do |
| 50 | Natural, honest | MS/MCU dialogue/VO |
| 65–85 | Intimate, flattering, compressed | CU emotion |
| 100–135 | Voyeuristic, compressed, isolating | Threat watching from distance, telephoto POV from shore |

- RULE: lens progression tracks intensity — calm scenes cluster in 35–50; climax uses extremes (≤24 or ≥85) **contrast**; resolution returns to 35–50.
- Character continuity: a given character's CU uses the same lens (±10 mm) within a sequence.
- DOF: f-stop for stylized look 2.0–4.0 on CU (background soft, eyes sharp); ≥ 5.6 on wides. Focus always on the near eye.

### 3.6 Camera height psychology
- Eye level (camera at hero eye height ±10%): neutral, empathetic — default.
- Low angle (camera below hero chest, tilt up 10–25°): power, resolve, determination (decision made).
- High angle (above head, tilt down 15–45°): vulnerability, overwhelmed, small (shipwreck reveal).
- Bird's-eye / top-down: fate, map-like explainer diagram moment.
- Dutch (roll 5–15°): disorientation; ≤ 2 shots per episode.
- RULE: hero's arc shown in height: high angles dominate escalation; first **low angle on the hero comes at the turning-point decision**.

### 3.7 Movement, rhythm, cutting
- **Motivated moves only**: every camera move must cite a motivation (`follow_subject`, `reveal`, `character_attention`, `tension_push`). Push-in = growing realization/tension; pull-out = isolation/reveal of scale; pan/tilt = following attention; handheld noise (amp ≤ 0.3°, 4–8 Hz) only for panic beats.
- Ease all moves (no linear starts); move starts ≥ 4 frames after the cut or on the subject's action.
- **Shot length (HEUR for vertical shorts)**: median 2.0–3.5 s; min 0.75 s (18 f) except flash inserts (≥ 8 f); max 6 s unless a deliberate long take/hold with motion. Escalation shortens average shot length; resolution lengthens it (rhythm contrast).
- **Cut on action**: cut during a movement (at 1/3–1/2 of the action), overlapping 2–4 frames of action across the cut so the motion feels continuous.
- **Murch's Rule of Six** priority when choosing a cut point: emotion 51% > story 23% > rhythm 10% > eye-trace 7% > 2D plane 5% > 3D space 4%; a higher criterion can excuse a violation of a lower one, not vice versa [Murch via StudioBinder/No Film School].
- **Eye-trace**: the viewer's focus point (hero eyes / brightest-contrast point) in the last frame of shot A should be within ~15% of frame width of the focus point in the first frame of shot B (centered-hero rule makes this easy).
- **J/L cuts**: audio of next shot leads by 6–18 frames (J cut) for anticipation (hear the drums before seeing the shore); outgoing audio tails 6–18 frames over the next picture (L cut) for VO continuity. Use J cuts into every threat reveal.

### 3.8 Composition and Bruce Block's visual structure
Block: every frame is built from visual components — **space, line, shape, tone, color, movement, rhythm** — and controlled by **contrast and affinity**: greater contrast → greater visual intensity; greater affinity → lower intensity [Block, The Visual Story; UT Austin RTF318 wiki]. Visual intensity should track the story's intensity graph.

Implementation:
- Build `intensity_graph[beat] ∈ [0,1]` from §2.2 (hook ~0.6, setup 0.2–0.3, escalation rising 0.4→0.8, climax 1.0, resolution 0.2).
- Per component, map intensity to a parameter:

| Component | Affinity (low intensity) | Contrast (high intensity) | Param |
|-----------|-------------------------|---------------------------|-------|
| Space | Flat/deep held constant; long lens, few planes | Sudden deep space, wide lens, strong FG/MG/BG | lens mm, # depth planes |
| Line | Horizontals | Diagonals, broken lines (mast, oars, rocks at 30–60°) | dominant line angle |
| Shape | Rounded, circles | Triangles, jagged (reef, torch flames) | shape library tag |
| Tone | Narrow value range | Full range, deep blacks next to highlights | luminance range |
| Color | Analogous, low sat | Complementary (moon blue vs fire orange), high sat accents | hue distance, sat |
| Movement | Slow, same direction | Fast, opposing directions, camera vs subject counter-move | screen-speed |
| Rhythm | Regular cutting, even beats | Irregular, accelerating cuts | ASL, variance |

- **Depth layering**: every WS/MS has ≥ 3 planes — FG (frame-edge element, darker/out of focus: rigging, rail, foliage), MG (hero, centered per H1), BG (island/sky/moon). Overlap, atmospheric perspective (fog density increases with distance) and value separation (BG lighter or darker than MG by ≥ 1 stop) sell depth.
- **Centered hero (H1)** + vertical thirds; use lines (horizon, mast, beach) to lead to the center. Symmetry heightens confrontation/stillness; to show imbalance, offset the *environment*, not the hero.
- Headroom: CU eyes at 0.35–0.42 from top; WS keep horizon off center (upper or lower third) — never splitting the hero's head.

**CHECKLIST §3**
- [ ] C1 CU+ECU shots ≤ 25% of total shots (climax sequence ≤ 40%).
- [ ] C2 No run of > 3 consecutive CU-or-tighter shots.
- [ ] C3 Each new location: shot index of first EWS/WS ≤ 2.
- [ ] C4 Re-establishing WS after ≤ 6 consecutive tighter shots or after any time jump.
- [ ] C5 Camera stays on `action_line` side for all shots in a sequence unless the crossing shot is flagged `line_cross:{moving|neutral|turn}`.
- [ ] C6 Look/POV pairs: sign(gaze_x) == sign(poi_x − 0.5).
- [ ] C7 Hero eye x ∈ [0.42, 0.58]; eye y ∈ [0.30, 0.45] for MCU/CU; key content outside top 12% / bottom 20%.
- [ ] C8 Every camera move has `motivation` ≠ null; moves use eased F-curves.
- [ ] C9 Shot durations: median 2.0–3.5 s; none < 18 f except `insert` (≥ 8 f); none > 6 s unless `long_take:true`.
- [ ] C10 ≥ 1 J-cut into each threat reveal; audio lead 6–18 f.
- [ ] C11 Eye-trace delta across cuts ≤ 0.15 frame width for ≥ 80% of cuts.
- [ ] C12 Pearson correlation between `intensity_graph` and per-shot computed visual contrast (value range × hue distance × 1/ASL) ≥ 0.5.
- [ ] C13 WS/MS shots have ≥ 3 depth planes; FG element present in ≥ 50% of WS.
- [ ] C14 Same character CU lens within ±10 mm inside a sequence.

---

## 4. Lighting Recipes

Principles from Pixar: lighting is a storytelling tool, not just illumination (Calahan's SIGGRAPH '96 "Storytelling Through Lighting" in *Pixel Cinematography* course) [SIGGRAPH history]. "Control the lighting, control the colors, control the feelings" (Feinberg profile) [Wired/Business Insider]; on Coco's night world, emotion was varied through **luminance** when hue was fully used [Daily Princetonian/BI]. Believability beats physical accuracy: cheat lights to keep the hero appealing and readable — Riley stays "cute and vulnerable" even when unpleasant [fxguide Inside Out].

### 4.1 Three-point baseline (intensities in exposure ratios measured on the hero's face)
- **Key**: motivated source (moon, cabin lamp, flare, torch). Defines direction.
- **Fill**: total fill ≈ 25–50% of key for neutral (a common CG guideline is ~40% of key [Pluralsight]); complementary-tinted fill adds depth [UW CSE458].
- **Rim/kicker**: separates silhouette from BG. At night rim may be 1–2× key brightness (stylized "moon kiss").

Key:fill ratio by mood (HEUR, convention):
| Mood | Key:Fill | Stops difference |
|------|----------|------------------|
| Bright/comedic setup | 2:1 | 1 |
| Neutral/day drama | 3:1–4:1 | 1.6–2 |
| Tense night | 6:1–8:1 | 2.6–3 |
| Climax / horror | 12:1–16:1 | 3.6–4 |
Never let the hero's shadow side go to pure black: shadow-side face ≥ 3% scene-linear reflectance-equivalent (still readable on a phone at low brightness).

### 4.2 Motivated sources and night conventions
- Every light in `light_rig` has `motivation` (moon, sky, practical:cabin, practical:headlamp, fire, flare, bounce:water). Unmotivated lights allowed only as fill/rim with ≤ 50% key intensity.
- **Moonlight convention**: cool blue key (Blender color ≈ RGB(0.55, 0.70, 1.0), roughly 6500–9000 K-looking relative to warm practicals) — a film convention, not physics (moonlight is reflected sunlight, slightly warm; the eye's scotopic shift reads night as blue). High and to the side/back of action; Deakins placed his "moonlight" on a bluff above the set so it hits from side or back, rarely from the front [British Cinematographer masterclass].
- **Warm practicals** (2700–3200 K look: RGB ≈ 1.0, 0.65, 0.35) for cabin lights, headlamp, torches on shore, flares (flare: saturated red-orange). Warm = safety/human; on the island, warm torches = threat — use the same hue but higher contrast and flicker (noise 6–12 Hz, ±15% intensity).
- Keep a clear **warm/cool split**: hero side lit by one temperature, threat/environment by the other. Hue separation ≥ 120° on the color wheel for night climax.
- **Exposure at night**: don't make night dark by crushing everything — make it dark by *few* bright areas. Target ≤ 15% of frame above middle grey; hero face at or slightly below middle grey; black point lifted to a dark blue (not 0) for stylized readability.
- Water: specular moon path (glint road) leading to the hero = free compositional line and depth cue.

### 4.3 Consistency across a sequence (how Pixar does it, applied)
1. Pick **key shots** per sequence (1 per ~8–10 shots, always including the widest and the closest) [Blender Studio; fxguide].
2. Paint/approve **color key** for each key shot (from §6 palette).
3. Build one **sequence light rig** (Blender collection linked into every shot = LiveGroup equivalent [Foundry Win or Lose]).
4. Per-shot **overrides** only for: rim cheat, eye lights, kicker on face, bounce card. Store as deltas [Foundry IO2].
5. **Continuity review**: render all shots of the sequence as a contact sheet in cut order and as a playblast; adjacent shots compared [fxguide; Blender Studio].

Rules:
- Key light azimuth (world space) constant within a sequence ±15°; elevation ±10°. Cheating per shot is allowed in *camera-relative* terms only if world-space stays within tolerance or the shot is flagged `cheat_reason`.
- Exposure continuity: hero face mean luminance across adjacent shots within ±1/3 stop (unless story beat changes the light, e.g. flare ignites).
- Color temperature of the key within a sequence: hue ±5°, saturation ±10%.
- **Eye lights**: a small catchlight in both eyes in every MCU or tighter (spec-only light, does not affect diffuse). Without it eyes read dead (cf. Feinberg on WALL-E's eye needing black pupil/aperture to "have a soul") [Harvard Magazine].

### 4.4 Silhouettes, shape readability, atmosphere
- Squint test: at 64x114 px downsample, hero pose silhouette must be recognizable; hero must differ from the immediate background by ≥ 1 stop luminance or ≥ 60° hue.
- Rim or a lit BG (moon sky, fog glow) behind dark hero; or dark hero against lit BG (silhouette shot) — choose one per shot, don't put a mid-grey hero on a mid-grey BG.
- Atmosphere/volumetrics: low-density volume (Blender Volume Scatter density 0.002–0.02 m⁻¹, anisotropy 0.3–0.6) to get god-rays from the moon/torch and atmospheric perspective. Fog density increases distance separation; BG island values ≥ 1 stop lifted toward sky color.
- Avoid flat ambient: world/sky fill contributes ≤ 30% of hero face illumination.

**CHECKLIST §4**
- [ ] L1 Every light has `motivation`; unmotivated lights ≤ 0.5× key.
- [ ] L2 Key azimuth Δ ≤ 15°, elevation Δ ≤ 10° across all shots of a sequence (world space) or `cheat_reason` set.
- [ ] L3 Measured hero-face key:fill ratio within the band for the beat's mood.
- [ ] L4 Adjacent-shot hero face luminance delta ≤ 0.33 stop unless `light_event` logged.
- [ ] L5 Night sequences: warm/cool hue separation ≥ 120° between key and practicals; ≤ 15% of pixels above 0.18 linear.
- [ ] L6 MCU/CU/ECU shots have catchlights in both eyes (spec light present & visible).
- [ ] L7 Silhouette test: hero mask vs background contrast ≥ 1 stop or ΔHue ≥ 60° in ≥ 90% of frames.
- [ ] L8 Each sequence has key shots lit first; all shots link the same `light_rig` collection.
- [ ] L9 Hero shadow-side face never clips to 0 (min ≥ 0.03 linear before view transform).

---

## 5. Character Performance

### 5.1 The 12 principles → parameters
From Thomas & Johnston, *The Illusion of Life* (Disney): squash & stretch, anticipation, staging, straight-ahead/pose-to-pose, follow-through & overlapping action, slow in/slow out, arcs, secondary action, timing, exaggeration, solid drawing, appeal.

| Principle | Factory rule |
|-----------|--------------|
| Squash & stretch | Volume preserved (scale x·y·z ≈ 1 ± 0.05); stylized cheeks/body 5–15% on impacts |
| Anticipation | Every major action has a counter-move 4–12 f before it (bigger action → longer) |
| Staging | One idea per shot; the action reads in silhouette (§4.4); hero centered (H1) |
| Pose-to-pose | Key poses from beat board → breakdowns → spline; holds explicit |
| Follow-through/overlap | Hair, clothes, straps, hands lag 2–6 f; secondary chains via spring constraints |
| Slow in/out | No linear interpolation on body controls except mechanical props |
| Arcs | Wrists, head, and center-of-mass trace arcs (validator: path curvature non-zero, no zig-zag) |
| Secondary action | ≥ 1 secondary per held shot > 2 s (breath, finger fidget, wiping water) — must not upstage primary |
| Timing | Weight via frames: light objects 4–8 f, heavy 12–24 f to settle |
| Exaggeration | Push key poses 10–30% beyond realistic for stylized readability |
| Solid drawing | Avoid twinning: L/R limbs offset ≥ 2 f and different angles |
| Appeal | Clear, simple shapes; face lit and readable (§4) |

### 5.2 Acting beats: thought → action
- Hooks: "Thinking tends to lead to conclusions, and emotion tends to lead to action" (principle 1 of 7) [Hooks, via adweaver blog / ArtStation]. Characters must be seen to **think before they act**.
- Beat structure inside a shot (HEUR): **perceive (eyes) → think (eye darts / brow, 8–24 f) → decide (blink or head settle) → act (anticipation → action) → react**.
- Every shot has an `objective` (what he wants right now) and an `obstacle`. The performance plays the objective, not the emotion label.
- Eyes lead: gaze shifts first, head follows 2–6 f later, then torso 4–10 f after head ("eyes → head → shoulders → hips") [Animation Mentor].

### 5.3 Eyes, blinks, saccades
**Blinks** (Trutoiu et al., *Modeling and Animating Eye Blinks*, Disney Research / ACM TAP 2011) [Disney Research PDF]:
- Real spontaneous blinks are **asymmetric**: fast close (high velocity, short), slower decelerating open. Model-based asymmetric profiles were rated most natural; symmetric linear least.
- Duration: in perceptual tests at 30 fps, 9-frame blinks (~300 ms) rated most natural for the realistic character; **7 frames (~230 ms) preferred for the cartoon character**. At 24 fps for stylized characters → **5–6 frames total**: close 2 f, (optional 0–1 f closed hold), open 3 f.
- Blink rate varied 6.6–27 blinks/min across actors in conversation → stylized baseline 10–20/min (one every 3–6 s), never periodic.
- Animation Mentor guideline: ~3–5 f down, brief hold, 2–4 f up; slower blinks for fatigue/sadness, quicker for nerves/excitement; upper lid does most of the motion [Animation Mentor] (prefer the asymmetric fast-close variant above).

Blink placement rules:
- Blink **on head turns and gaze shifts** (blinks frequently coincide with head turns and changes of focus) [Animation Mentor; Eyes Alive model links blinks and gaze moves].
- Blink to punctuate a **thought change / decision**; withhold blinks during intense focus or shock (stare 2–4 s).
- Exhaustion/sadness: slow blink, 10–16 f, with partial-open hold.
- Both eyes blink together (no L/R offset); offset upper vs lower lid by ~1 f instead, since the upper lid does most of the motion.
- No blink cut in half by an edit (blink must complete within shot or start ≥ 3 f before cut).

**Saccades and eye darts** (Lee, Badler & Badler, *Eyes Alive*, SIGGRAPH 2002; main-sequence oculomotor literature) [Eyes Alive / normbadler.com; PMC main-sequence]:
- Saccade duration grows with amplitude ("main sequence"); approx. D ≈ 25 ms + 2.4 ms/° × amplitude → a 10° saccade ≈ 50 ms ≈ **1–2 frames at 24 fps**. Eyes *pop* between targets; never ease an eye saccade over > 3 f.
- Fixations between saccades ~200–400 ms (5–10 f) typical; corrective micro-fixations ~100–130 ms [PMC].
- Large gaze shifts (> 15–20°): eyes jump first, head follows (VOR keeps eyes on target while head catches up — eyes counter-rotate during the head turn).
- **Eye darts** while thinking: 2–4 small saccades (2–8°) between the two eyes of the other character or between candidate objects, every 6–12 f. Use for "deciding what to do."
- Avoid "dead eyes": in any shot > 2 s, either a saccade, blink, or micro-dart (≥ 1 per 2 s) or a deliberate stare flagged `stare:true`.
- Convergence: both eyes converge on the actual 3D target (aim constraint to target empty), not parallel.

### 5.4 Holds
- **Moving hold**: never freeze; after reaching a pose, keep drifting 1–3% toward a settle over 12–36 f (breath, slight sink).
- Hold length to read a pose: ≥ 6–8 f for a key pose to register; ≥ 16–24 f for an emotional "accent" pose.

### 5.5 Line of action, silhouette, poses
- Each key pose has a clear **line of action** (C or S curve through spine/head); straight-vertical poses only for deliberate stiffness/fear.
- Silhouette readability: arms separated from torso in key poses (negative space visible) in ≥ 70% of key poses.
- Weight: center of mass over support polygon when still; outside it only in transition/falling.

### 5.6 Facial expression (FACS-based shape keys)
Use FACS action units (Ekman & Friesen) as the rig's shape-key vocabulary. Core emotion recipes (AU combos, standard Ekman/EMFACS):
| Emotion | AUs |
|---------|-----|
| Fear | 1+2+4+5+7+20+26 (brows up & together, upper lid raise, lip stretch, jaw drop) |
| Surprise | 1+2+5+26 |
| Determination/anger | 4+5+7+23 (brow lower, lids tight, lips pressed) |
| Sadness | 1+4+15 (inner brow up, lip corner down) |
| Relief/joy | 6+12 (cheek raise + lip corner pull = genuine "Duchenne" smile) |
| Concentration | 4 + 7 + slight 24 |
- Asymmetry 5–15% L/R on every expression (perfect symmetry reads robotic).
- Expressions change via **brows first** (2–4 f ahead of mouth).
- Transitions 6–12 f; shock 2–4 f.

### 5.7 Lip sync (if on-screen dialogue)
- Phoneme→viseme map with ~10–12 mouth shapes; hit consonant shapes (M/B/P closed, F/V lip-on-teeth) **1–2 frames before** the audio (pre-lead reads as in-sync).
- Don't animate every phoneme: hold vowels, drop unstressed syllables; jaw moves on stressed syllables only.
- Mouth closes on pauses ≥ 6 f. Head accents on stressed words, preceded by eyebrow accent.
- VO-only (narrator) episodes: hero does not lip sync; instead act the thought (no "talking head mouthing").

**CHECKLIST §5**
- [ ] A1 Major actions have anticipation 4–12 f (detected: reverse-velocity on root/COG before action).
- [ ] A2 No linear F-curves on character body controls.
- [ ] A3 Blink count per shot consistent with 10–20/min; no two blinks < 1.5 s apart except deliberate flutter; blink close-phase frames < open-phase frames.
- [ ] A4 Blinks: ≥ 50% coincide (±3 f) with a head turn or gaze shift > 10°.
- [ ] A5 Saccade transitions ≤ 3 f; eyes converge on a target empty.
- [ ] A6 Gaze shift leads head rotation by 2–6 f for shifts > 15°.
- [ ] A7 No shot > 2 s with eyes static unless `stare:true`.
- [ ] A8 Every shot ≥ 2 s has a moving hold (no zero-velocity spans > 12 f on spine/head).
- [ ] A9 L/R facial shape key values differ by 5–15% on emotional poses.
- [ ] A10 Every shot has `objective` and a thought → action sequence in `beats.json`.
- [ ] A11 Lip sync: closed-mouth visemes lead audio by 1–2 f.

---

## 6. Color and Grade

### 6.1 Color script practice
- Pixar makes a color script for every film mapping hues of all scenes to the story arc; viewed in sequence it shows the emotional arc [StudioBinder; Ceros]. Eggleston on Finding Nemo: explosive color at the start, color pulled out until "almost monochromatic" in the middle — "it suited the film emotionally" [MoMA Eggleston interview]. WALL-E: limited tan/orange palette with **no green anywhere** so the plant would hit as a visual punch [TED Ideas]. A Bug's Life: saturated grasshopper shots make grey Ant Island feel greyer (contrast between sequences) [fxguide].
- Lesson: **reserve** a hue (or saturation level) for the story's key payoff and withhold it until then.

### 6.2 Palette per act (default for "night survival" episodes; HEUR)
| Act | Dominant | Accent | Saturation (mean HSV S) | Value key |
|-----|----------|--------|------------------------|-----------|
| Hook | deep blue-teal night | single warm danger point | 0.35–0.5 | low-key |
| Setup (before wreck, dusk) | warm golden/magenta dusk | teal sea | 0.5–0.65 | mid-key |
| Inciting / escalation | desaturated blue-grey moonlight | warm cabin/headlamp | 0.25–0.4 | low-key, rising contrast |
| Climax | moon-blue vs fire/torch/flare orange (complementary) | **reserved** flare red | 0.5–0.7 accents only | highest contrast |
| Resolution (dawn/rescue) | pink-gold dawn, soft cyan | first green/warm sun (reserved) | 0.45–0.6 | high-key, low contrast |
- `palette.json` per beat: `dominant_hue`, `accent_hue`, `sat_mean`, `value_mean`, `contrast` (p95–p5 luminance), `reserved_hue_used: bool`.

### 6.3 Saturation and contrast as storytelling
- Saturation tracks emotional "aliveness": high in safety/normal, drained in despair, a single saturated accent for hope/danger.
- Contrast (tone range) tracks intensity graph (Block): affinity in calm beats (narrow range), contrast at climax.
- Skin/hero face stays within a protected hue band across the whole film (never goes grey-green), even in moonlight — cheat warmth into skin by +5–10% (appeal rule).

### 6.4 Tone mapping and grade (Blender)
- Use **AgX** view transform (Filmic is deprecated and superseded by AgX; ~16.5 stops; desaturates very bright colors like film) [Blender manual Color Management]. Looks: `AgX - Punchy` darkens/adds contrast (good for night climax), `Medium High/High Contrast` for intensity, `Base` or low-contrast looks for calm [AgX repo / Blender manual].
- Light in scene-linear; set exposure so the hero's face sits at ~0.18 linear (middle grey) before view transform in neutral scenes; night 0.06–0.12.
- Grade in a single, sequence-level pass (Remotion or compositor): lift/gamma/gain per sequence, not per shot; per-shot only exposure trims ≤ ±0.3 stop to match.
- Output Rec.709/sRGB, 8-bit with ≥ 0.5% film grain or dither to prevent banding in dark gradients (night skies band badly on phones).

**CHECKLIST §6**
- [ ] K1 `colorscript.png` exists with one key per beat; measured renders' mean hue within ±15° of key, sat within ±0.1.
- [ ] K2 Reserved hue (e.g. flare red, sunrise green) pixel share < 0.5% before its payoff beat and ≥ 3% at payoff.
- [ ] K3 Mean saturation per act follows the planned arc (sign of delta between acts matches plan).
- [ ] K4 Contrast (p95–p5 luminance) correlates with intensity graph (r ≥ 0.5).
- [ ] K5 View transform = AgX; look chosen per sequence, not per shot.
- [ ] K6 Hero skin hue within protected band (±12° of master skin hue) in all shots.
- [ ] K7 No visible banding: dark gradient regions have grain/dither enabled.

---

## 7. Sound and Edit

### 7.1 Sound layers (build in this order; stems kept separate in Remotion)
1. **Ambience bed** (continuous across cuts within a location; never cut with picture): surf, wind, rigging creak, distant jungle insects. −30 to −24 LUFS-short relative to final.
2. **Spot FX** (sync to on-screen events): hull scrape, wave slaps, flare pop.
3. **Foley** (body/cloth/props: footsteps on deck, rope, wet hands) — sells weight; every hero contact with an object gets a foley hit.
4. **Dialogue/VO**: always on top; music/FX ducked 6–10 dB under VO (side-chain).
5. **Score**: motif-based; the theme returns in resolution.
6. **Risers/hits/stingers**: riser 2–6 s into a reveal; hit on the cut.
7. **Silence**: the strongest effect. Drop music (and reduce ambience by ≥ 12 dB) for 0.5–1.5 s right before the climax reveal or the key decision; then hit.

### 7.2 Music cues to emotion (HEUR)
| Beat | Music |
|------|-------|
| Hook | Low pulse/drone + one tension motif |
| Setup | Light melodic, major or modal, 80–100 BPM |
| Inciting | Music cuts out → impact SFX → low drone |
| Escalation | Ostinato building in layers; tempo/feel push 100–130 BPM; percussion enters on 2nd escalation beat |
| Climax | Full texture, then silence gap, then hit |
| Resolution | Theme reprise, sparse, warm; resolves to tonic on the final card |
- Cut points of picture land on musical beats/bars for ≥ 50% of cuts in music-driven passages (rhythm criterion, Murch).
- Music starts/ends motivated by story change (never mid-beat randomly); use J-cuts so music for the next beat starts 6–18 f early.

### 7.3 Pacing and edit
- Emotion first when choosing frames (Murch 51%).
- Vertical retention: a "pattern interrupt" (new shot size, angle, reveal, sound event) at least every 3–5 s; the first 3 s contain the hook.
- VO density 2.3–2.8 words/s; leave ≥ 1 s VO-free pockets at each beat transition for sound/score to breathe.
- Captions (burned-in) synced ±2 f to VO, max 2 lines, within safe area (H2).
- Loudness (HEUR for social platforms): integrated −14 LUFS, true peak ≤ −1 dBTP; dialogue intelligible on phone speaker (high-pass music < 80 Hz under VO).

**CHECKLIST §7**
- [ ] D1 Ambience stem continuous across every cut within a location (no gap > 2 f).
- [ ] D2 Every on-screen contact/impact has a spot FX or foley event within ±2 f.
- [ ] D3 Music ducked ≥ 6 dB under VO.
- [ ] D4 ≥ 1 silence gap (music off, ambience −12 dB) of 0.5–1.5 s within 5 s before the climax hit.
- [ ] D5 Pattern interrupt interval ≤ 5 s throughout.
- [ ] D6 Final mix −14 LUFS ±1, true peak ≤ −1 dBTP.
- [ ] D7 Captions within safe area and ±2 f of VO word timings.
- [ ] D8 Resolution contains theme reprise (motif id matches hook/setup motif).

---

## 8. Master Validation Order (for the director agent)

1. Story gate: S1–S8, P5.
2. Reel gate: P2, C1–C4, C9, C12, D5 (on animatic).
3. Layout gate: C5–C8, C10–C11, C13–C14, P3.
4. Animation gate: A1–A11.
5. Lighting gate: L1–L9, P4.
6. Color/grade gate: K1–K7.
7. Final mix gate: D1–D4, D6–D8.
Any RULE failure blocks the gate; HEUR failures require a logged `override_reason`.

---

## Sources
- Emma Coats, Pixar's 22 Rules of Storytelling (story spine #4, #1, #19, #22): https://www.fastcompany.com/3018559/pixars-22-rules-of-storytelling-visualized · https://fs.blog/22-rules-pixar-uses-to-create-appealing-stories/ · https://nofilmschool.com/2012/06/22-rules-storytelling-pixar
- Pixar in a Box (Khan Academy / Pixar): https://pixar.com/pixar-in-a-box · https://www.khanacademy.org/computing/pixar
- Pixar pipeline descriptions: https://www.davidbordwell.net/blog/2008/04/10/a-glimpse-into-the-pixar-kitchen/print/ · https://people.uncw.edu/ricanekk/teaching/spring09/csc100/lectures/pattersone/TheMakingOfToyStory.pdf · https://www.graphics.cornell.edu/academic/art2907/secure/22_LECTURE_3D_Animation.pdf
- RenderMan, "Incredible Cinematography" (Incredibles 2 lighting/layout): https://renderman.pixar.com/stories/incredible-cinematography
- Pixar, Light Pruning on Toy Story 4: https://graphics.pixar.com/library/LightPrune/paper.pdf
- fxguide, Inside a scene in Inside Out (key shots, color keys, master lighting, shot lighting): https://www.fxguide.com/?p=183623
- Foundry, Win or Lose lighting (LiveGroups): https://www.foundry.com/insights/film-tv/win-or-lose-animation-lighting-pixars-first-episodic
- Foundry, Inside Out 2 lighting (sequence globals + shot overrides): https://colorway.foundry.com/insights/film-tv/inside-out-2-lighting-creating-emotion-characters
- Blender Studio artist guide, Lighting (key shots, adjacent shot continuity): https://studio.blender.org/tools/artist-guide/shot-production/lighting
- Sharon Calahan, Storytelling Through Lighting, SIGGRAPH '96 Course 30 *Pixel Cinematography*: https://history.siggraph.org/wp-content/uploads/2021/08/1996-30-Contents-Pixel-Cinematography-A-Lighting-Approach-for-Computer-Graphics.pdf · https://history.siggraph.org/person/sharon-calahan/
- Danielle Feinberg: https://www.harvardmagazine.com/2015/06/action-camera-lights · https://www.businessinsider.in/4-genius-ways-pixar-uses-lighting-to-tell-breathtaking-stories/articleshow/50114232.cms · https://www.dailyprincetonian.com/article/2018/02/feinberg-talks-pixar-technology-and-art-coco · https://nofilmschool.com/2016/04/pixar-director-of-photography-danielle-feinberg
- Three-point lighting guidance: https://www.pluralsight.com/blog/film-games/understanding-three-point-lighting · https://courses.cs.washington.edu/courses/cse458/10au/content/projects_458/project5a/index.html
- Roger Deakins moonlight (No Country / True Grit): https://britishcinematographer.co.uk/?p=33310 · https://theasc.com/blog/the-film-book/sicario-interview-with-roger-deakins-asc-bsc
- Ralph Eggleston / color scripts: https://www.moma.org/interactives/redstudio/interviews/behind/content/eggleston/assets/transcripts.php · https://ideas.ted.com/how-color-helps-a-movie-tell-its-story/ · https://www.studiobinder.com/blog/what-is-a-color-script-definition/ · https://www.ceros.com/inspire/originals/lessons-in-story-design-from-pixars-creative-team
- Patrick Lin / Jeremy Lasky / Pixar layout: https://collider.com/inside-out-interview-director-of-photography-patrick-lin/ · https://www.awn.com/print/animationworld/hello-wall-e-pixar-reaches-stars · https://theasc.com/articles/toy-story-4-creating-a-virtual-cooke-look · https://graphics.pixar.com/library/WinOrLoseCinema/paper.pdf
- Bruce Block, *The Visual Story* (contrast & affinity, 7 components): https://www.oreilly.com/library/view/the-visual-story/9780240807799/009_9780080551692_chapter2.html · https://cloud.wikis.utexas.edu/wiki/spaces/rtf318/pages/80021989/Graphing+Visual+Structure · https://betterposters.blogspot.com/2022/07/review-visual-story.html
- Joseph V. Mascelli, *The Five C's of Cinematography*: https://www.silmanjamespress.com/catalogs/the-five-cs-of-cinematography
- Walter Murch, Rule of Six: https://www.studiobinder.com/blog/walter-murch-rule-of-six/ · https://cloud.wikis.utexas.edu/wiki/spaces/rtf318/pages/80022510/Murch+s+Rule+of+Six
- Hitchcock bomb theory (Hitchcock/Truffaut): https://nofilmschool.com/alfred-hitchcock-and-francois-truffaut-explain-surprise-vs-suspense · https://davidbordwell.net/blog/2013/11/29/hitchcock-lessing-and-the-bomb-under-the-table/
- Ed Hooks, *Acting for Animators*: https://adweaver.blogspot.com/2012/12/7-acting-principle-ed-hooks.html · https://magazine.artstation.com/2020/01/acting-for-animators-with-ed-hooks/
- Trutoiu et al., Modeling and Animating Eye Blinks (Disney Research, ACM TAP 2011): https://la.disneyresearch.com/wp-content/uploads/Modeling-and-Animating-Eye-Blinks-Paper.pdf
- Animation Mentor, blinks & eye movement: https://www.animationmentor.com/blog/tutorial-animate-blinks-eye-movement/
- Lee, Badler & Badler, Eyes Alive (SIGGRAPH 2002): https://www.cis.upenn.edu/~badler/papers/EyesAlive.pdf (now redirects to https://normbadler.com/) · saccade main sequence/fixations: https://pmc.ncbi.nlm.nih.gov/articles/PMC3625326
- Blender Color Management / AgX: https://docs.blender.org/manual/en/4.2/render/color_management.html · https://github.com/EaryChow/AgX
- Cinemetrics (shot-length measurement method): https://cinemetrics.uchicago.edu/how-to-use
- Thomas & Johnston, *The Illusion of Life* (12 principles); Ekman & Friesen, FACS — standard references, not fetched here.

Notes on certainty: frame counts for blinks come from Trutoiu et al. (30 fps study, converted to 24 fps) and Animation Mentor. The saccade formula is the commonly cited Eyes Alive / main-sequence approximation; the Eyes Alive PDF could not be fetched directly in this session. Shot-distribution percentages, ASL targets, key:fill bands, loudness and act timings are house heuristics built from the sources' principles, not published Pixar numbers.
