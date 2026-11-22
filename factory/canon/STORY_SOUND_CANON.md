# Story and Sound Canon (sources 8-11)

Distilled from the founding sources 8-11 in `factory/canon/SOURCES.md`, for the code-driven pipeline:
**director** (`factory/director`: writes `story.json` + `shotplan.json`) → **voice** (`factory/voice`: ElevenLabs, word timings `narration.words.json` as `[{w, s, e}]`) → **sound designer** (`factory/sound/designer.py`: `sound.json` beds, cues, silences, reveals) → **gates** (`factory/qc`, `python3 -m factory.canon pass`).

Rule IDs CAN-S1..S3 and CAN-N1..N4 are the stable IDs from `.claude/skills/film-craft-canon/SKILL.md`. Sub-rules (CAN-S1a, CAN-N2c, ...) are new here. A threshold marked **[HOUSE]** is our engineering number and is not in the source. Everything else is backed by the quoted passage.

Page conventions: "PDF p.N" is the page index in the downloaded file; "printed p.N" is the number on the page.

| # | Source | Fetched | Pages read |
|---|---|---|---|
| 8 | W. Bligh, *Remaking The 39 Steps* (UTS thesis), `02whole.pdf`, 394 pp. | yes | printed pp.24, 35-43, 84-85 (PDF 32, 43-51, 92-93) |
| 9 | CCEA GCE Moving Image Arts 2019 AS2 mark scheme | **no: HTTP 403, "Your IP or Country has been blocked by CCEA"**. An archive.org copy exists but fetching it was refused in this session. | none |
| 10 | M. Rabiger, *Directing the Documentary* 4th ed., Ch.33 "Narration" | yes | printed pp.443-454 (PDF 458-469) |
| 11 | T. Das, *How to Write a Documentary Script* (UNESCO) | yes | pp.21-23, 41-45, 51 |

Source 9 is still **unverified**. The rules attributed to it below rest only on the user's own summary in SOURCES.md, and on source 8 where the thesis covers the same Hitchcock ideas (shared suspense versus dramatic irony, and the hand-over at the airport in *North by Northwest*). Re-read source 9 and quote it once someone can download it.

---

## Source 8: Hitchcock, "the bomb underneath the table" (Bligh, *Remaking The 39 Steps*)

### (a) Quoted passages

- **Printed p.40 (PDF 48), quoting Truffaut 1984 p.73:**
  > "Let us suppose that there is a bomb underneath the table … then all of a sudden, 'Boom!' The public is surprised, but prior to this surprise, it has seen an absolutely ordinary scene … Now let us take a suspense situation. The bomb is underneath the table and the public knows it. The public is aware that the bomb is going to explode at one o'clock and there is a clock in the decor. The public can see that it is a quarter to one. In the first case we have given the public fifteen seconds of surprise … in the second we have provided fifteen minutes of suspense. The conclusion is that whenever possible the public must be informed."
- **Printed p.40:** "suspense is sustained while surprise is a sudden experience." Hitchcock: there "is no terror in the bang, only in the anticipation of it."
- **Printed p.35 (PDF 43):** "In the usual form of suspense it is indispensable that the public be made perfectly aware of all of the facts involved. Otherwise there is no suspense." and "Knowing what to expect, they wait for it to happen. This conditioning of the viewer is essential to the build-up of suspense."
- **Printed p.36 (PDF 44), the Sabotage error:** "I once committed a grave error in having a bomb for which I had extracted a great deal of suspense. I had the thing go off and kill someone, which I should never have done because they needed the relief from their suspense. Bad technique; never repeated it."
- **Printed p.36, chase and race:** in shared suspense "the character and audience share the same awareness of the 'pursuer'". When the chase "involves reaching a particular point, or by a particular time, it becomes a 'race'". "In North by Northwest's crop-dusting scene, Hitchcock deliberately left time between plane attacks to build suspense … indicating—via point of view shots—that Thornhill has no cover close to him."
- **Printed p.37 (PDF 45), dramatic irony:** "the audience is privy to information the character is unaware of, while during a chase or shared suspense, the audience and character have the same information". The snooper example: "you show the person who lives in that room coming up the stairs. Then you go back to the person who is searching and the public feels like warning him, 'Be careful, watch out.'" And: "If the audience does know … they'll work like the devil for you because they know what fate is facing the poor actors."
- **Printed p.39 (PDF 47), mystery:** mystery is "void of emotion", "an intellectual puzzle". "Suspense is concerned with the events taking place in the character's present and engages a spectator with dramatic questions about what will happen next."
- **Printed p.40 (PDF 48), three knowledge relations:** "With shared, the characters and spectators have equivalent knowledge; dramatic irony, the audience has more knowledge; while suppression, characters (usually antagonists) possess knowledge unknown to the audience".
- **Printed p.41 (PDF 49):** "Let's put ourselves in the minds of our audience". Allen: suspense works "by dramatising the gap between character point of view and spectator point of view, by constantly shifting the forms and modes of suspense".
- **Printed pp.42-43 (PDF 50-51):** *North by Northwest* written as a beat-by-beat list of modes ("a. Surprise: Thornhill is abducted. b. Mystery … c. Shared … f. Suppression …").
- **Printed p.85 (PDF 93), the hand-over:** "At the airport, Thornhill receives all the information that the audience has been privy to (making the rest of the film shared suspense)".
- **Printed p.24 (PDF 32), pace:** "pace in a film is made entirely by keeping the mind of the spectator occupied. You don't need to have quick cutting … but you do need a very full story and the changing of one situation to another."

### (b) Principle
Tell the audience about the danger first, and show them the clock. Suspense is the gap between what the audience knows and what the character knows, held over time. A surprise buys seconds, while an informed audience gives you minutes. Once the audience has been made to fear something, they are owed relief. Each beat's mode (shared, irony, suppression, mystery, surprise) is chosen on purpose and listed, the way the thesis lists *North by Northwest*.

### (c) Machine-enforceable rules

**CAN-S1: show the threat to the audience first.** Engine: director (`story.json.knowledge_timeline`, `threats[]`), shotplan, gate `factory/canon/checks.py`.
- **CAN-S1a Planted before noticed.** For every `threats[i]`: `planted_shot` (a shot whose frames show the threat while the character is not looking: `hero.gaze` away, or the threat occluded from him) must start before `noticed_at`, the time the character notices. The lead is `noticed_at - planted_t` and must be **≥ 2.0 s** for a short and **≥ 4.0 s** for a long-form episode [HOUSE]. The threat must be visibly on screen for **≥ 1.0 s** in total inside that window [HOUSE]. Source: "the public must be informed"; "fifteen seconds of surprise … fifteen minutes of suspense".
- **CAN-S1b Audience-only window is real.** In every beat between `planted_t` and `noticed_at`, `knowledge_timeline[].audience_knows` contains the threat id and `character_knows` does not. Check: a set difference per beat.
- **CAN-S1c Relief owed.** Every threat with a `planted_shot` resolves in a beat with `mode: "relief"` or `payoff` of **≥ 1.5 s** [HOUSE] after its peak. A planted threat may not kill or maim an innocent or the protagonist (`outcome` ∈ {`escaped`, `averted`, `survived_with_cost`}). Source: the Sabotage error.
- **CAN-S1d Surprise is budgeted.** A danger event with no `planted_shot` must be declared `mode: "surprise"`. Allowed: **≤ 1 per 90 s**, and never the climax [HOUSE]. Source: "suspense is sustained while surprise is a sudden experience". Hitchcock uses surprise "more sparingly".

**CAN-S2: who knows and who can act, so the audience's question changes.** Engine: director prompt + `story.schema.json`; gate.
- **CAN-S2a Per-beat record (required).** Each beat has `audience_knows[]`, `character_knows[]`, `who_can_act` (`character` | `nobody` | `other:<id>`), `audience_question` (a string), `mode` ∈ {`shared`, `dramatic_irony`, `suppression`, `mystery`, `surprise`, `relief`}, and `threat_planted_shot` (a shot id or null). If any field is missing, the beat FAILs.
- **CAN-S2b Mode follows the knowledge sets.** `mode == "dramatic_irony"` ⇔ `audience_knows ⊋ character_knows` on a threat item. `shared` ⇔ the sets are equal on threat items. `suppression` ⇔ the beat declares `withheld_from_audience[]` (non-empty). Check: computed from the sets, and the declared value must match. Source: printed p.40, the three relations.
- **CAN-S2c The question changes on purpose.** Whenever `character_knows` gains a threat item (the hand-over) or `who_can_act` changes, `audience_question` must change in the same beat. The new question must be about the present or future: it starts with or contains `will|can|how|before|in time` and not `who did|why did|what happened` [HOUSE]. Typical pivot: "Will he look up?" → "Can he turn in time?". Source: the airport hand-over (p.85); suspense is about "what will happen next" (p.39).
- **CAN-S2d Keep the mind occupied.** The audience question or the mode must change at least every **12 s** [HOUSE; matches qc R-2 re-hook max gap]. Source: "the changing of one situation to another" (p.24).
- **CAN-S2e Disclosure in pieces.** At most **2 new `audience_knows` items per beat** [HOUSE]. Source 11 p.44 ("never too much at the same time").
- **CAN-S2f Mode map (Allen, "constantly shifting the forms and modes").** A short with no `dramatic_irony` beat FAILs. A short whose mode never changes FAILs.

**CAN-S3: a ticking clock the viewer can feel.** Engine: director (`ticking_clock`), shotplan badges/props, gate.
- **CAN-S3a The clock is in the decor.** `ticking_clock.kind` ∈ {`diegetic_prop`, `environment` (for example the tide line, reef distance or spray ring), `badge`}, plus `deadline` (what happens when it runs out). The deadline must be in `audience_knows` by the first reading. The first reading comes at **≤ 20 % of runtime** [HOUSE]. Source: "there is a clock in the decor. The public can see that it is a quarter to one."
- **CAN-S3b It only gets worse.** `readings[]` have strictly increasing `severity` and are re-shown at least every **20 s** [HOUSE].
- **CAN-S3c Ordinary actions cost visible time.** Every `attempts[]` item after the threat is known has `clock_before` and `clock_after` readings that differ, and **≥ 1.5 s** of screen time [HOUSE]. Example: restarting the engine is three key turns, and the reef is closer each time.
- **CAN-S3d Leave time between attacks.** Successive threat hits (impacts, near-misses) are **≥ 3.0 s** apart, with an anticipation shot in between [HOUSE]. Source: the crop-duster, "deliberately left time between plane attacks".
- **CAN-S3e The anticipation is longer than the bang.** For each impact, (impact time − time the threat was first known) **≥ 3 ×** the impact's own on-screen duration [HOUSE]. Source: "no terror in the bang, only in the anticipation of it."

---

## Source 9: Hitchcock, dramatic irony and shared suspense (CCEA MIA mark scheme). NOT READ

**(a) Quoted passages:** none. The download was blocked (HTTP 403, CCEA geo/IP block), and fetching the archived copy was refused in this session.
**(b) Principle (from the user's summary in SOURCES.md only):** "Who knows and who can act changes the audience's question ('will he look up?' → 'can he turn in time?')."
**(c) Rules:** these are covered by CAN-S2a-c above and backed by source 8 (pp.36-37, 40, 85). Status: *pending source verification*. Change nothing in CAN-S2 on the strength of source 9 until it has been read.

---

## Source 10: Rabiger, *Directing the Documentary*, Ch.33 "Narration"

### (a) Quoted passages

- **p.443, when narration is justified:** "Difficulty getting the film started (the setup …)", "Failure to establish background or historical context", **p.444:** "Failure to identify the origin and therefore authenticity of material", "Film lacks momentum", "Audience wants to know more about a participants thoughts, feelings, and choices", "Complicated story line is incomprehensible", "Getting from one good sequence to the next takes too much explaining", "Lack of resolution".
- **p.444, authority:** "the disembodied voice becomes a mediating presence standing between audience and the film's 'evidence.' This, of course, is the voice of authority". "Viewers take the narrator's voice as the voice of the film itself." The search is for a voice that "can act as a surrogate for your own attitude toward the subject."
- **pp.444-445, acceptable narration:** "Is limited to useful factual information", "Is nonmanipulative emotionally", "Avoids value judgments, unless first established by evidence in the footage", "may justifiably draw our attention to those aspects of the evidence … whose significance might otherwise be overlooked", "Lets the audience draw its own conclusions". Strategies include "the voice-over of one of the characters whose authority to have an opinion is never in doubt".
- **p.445, faults:** "Verbosity", "Heavy or literary writing", "Doubt over who or what the narrator represents (a question of the narrator's authority)". **p.446:** "Something distracting in the narrator's voice".
- **p.446, "The Scripted Narration":** "There should not even be a redundant syllable." Bad narration uses "The passive voice", "Long sentences", "Over-information that robs the audience of time to imagine or guess (regularly inflicted in films for children)", "Description of what is already evident".
- **p.447, the tryout:** "read your words aloud against each section … it must be the right length so you don't have to speed up or slow down to fill the space. Ends and beginnings of scenes sometimes need adjusting to accommodate narration."
- **p.447, "Adjusting syntax to match screen logic":** "invert the syntax so that the narration follows the audience's order of perception … the viewer notices the sun long before noticing the human being. You might first write, 'She goes out before anyone else is about.' But this immediately sets the viewer looking for the 'she.' … 'Before anyone else is up, she goes out.'"
- **p.447, "Accommodating sound features":** "Another reason to alter phrasing or to break sentences apart is to open up spaces for featured sound effects, such as a car door closing or a phone beginning to ring. Effects frequently create a powerful mood and drive the narrative forward, so don't obscure them with talking."
- **pp.447-448, "The power in each first word":** "the first word to fall on each new image exerts a major influence on how the audience interprets the whole shot." "the crux lies in which word hits the incoming shot". **p.448:** "By altering the relationship of narration to incoming image by a single word, the second sculpture can be made either just 'different' or 'provocatively different.'"
- **p.449, operative words:** "in any section of speech, there are strong places and weak places against which to make a picture cut … each new shot punches in against a strong operative word." There is a split-page example (Picture | Sound).
- **p.450, "Complement, don't duplicate":** "Narration should add to the image, never duplicate by describing anything in the image's content … never say that the child … is wearing a red raincoat (blatantly obvious) or that she is hesitant (subtly evident), but you might well say that she has just celebrated her sixth birthday."
- **p.450, the scratch recording:** "Lay in the scratch narration and watch it … In some places, you see that the narrator has to hurry, so here you must thin the narration out".
- **p.450, a script for the narrator:** "Set blocks of narration apart on the page and number them".
- **p.451, recording:** "Record … with the picture running so that the narrator can key into the rhythms". **p.452:** "The narrator should read each block of narration and wait for a cue", "Name the quality or emotion you are after", "When all narration has been recorded, play everything back against the film".
- **pp.453-454, presence track:** "you will have the right quality of 'silence' should the editor want to extend a pause … No two presence tracks … are ever exactly alike".
- **p.454, "Fitting the narration":** "Lay narration carefully against picture so that operative words hit each new image to maximum effect … adding to or reducing the natural pauses in the narration can sometimes stretch or compress a section … Be very careful, however, not to disrupt the natural rhythms of the speaker."

### (b) Principle
The narrator is the voice of the film, so its authority has to be explicit and earned. A line exists only to add something the picture and sound cannot carry. The line follows the viewer's order of perception, and its operative words are placed on the cuts. Phrases are broken apart to make room for featured sounds. Every line is tried out against picture before it is final.

### (c) Machine-enforceable rules (these sharpen CAN-N2, N3 and N4)
See CAN-N* in the combined section below. Specific to Rabiger: N2b (spaces for featured SFX), N2e (presence fill), N3a (operative word on cut), N3b/c (perception order), N4a-f (authority, purpose, complement, style lint, tryout, value judgements after evidence).

---

## Source 11: Das, *How to Write a Documentary Script* (UNESCO)

### (a) Quoted passages

- **p.42, narration is secondary:** "as crucial as sound is to films, the visual always comes first. Narration, therefore, is secondary to visual. It is a part of the overall narrative, but does not lead the narrative."
- **p.43, choosing the narrator:** "The most important decision the scriptwriter has to make concerning narration is deciding who will be the narrator/s." First-person narration "should follow the rules of first-person narrative, which is that only one character's POV can be shown at a time". "The 'Voice of God' … an all-knowing, omnipresent entity".
- **p.43, complement:** "narration should back up a visual instead of trying to overpower it. Also, if something is being shown visually, then there is no need for the narration to mention it as well. The narration should say what the visual doesn't say". "Information should be given on a need basis only".
- **p.44, read aloud and timed:** "This practice also gives an indication of how much time the narration will take to speak out aloud and will allow him to time the narration according to the length of visual sequences."
- **p.44, "Writing Sound":** sound can "make a point on its own, like the sound of a train whistle when the visual only shows a train track", or "reinforce a point that the visual is already making". "the scriptwriter should try and keep a more or less continuous presence of ambiance or natural sound."
- **p.44, "Disclosure":** "withholding as much information as possible until the point when it is absolutely necessary … in bits and piece, as and when required and never too much at the same time."
- **p.45, set up then pay off:** "planting insights or 'visual clues' … Later on, the scriptwriter provides the larger picture … closing that gap in knowledge".
- **p.23, silence:** "The lack of any sound over a particular moment in a film forces the audience to focus on the visual and heightens their anticipation for the moment when the something happens or when sound re-enters … this element should be used sparingly. Too long a gap between sounds will struggle to hold audience attention."
- **p.51, "Script Format" (worked script):** three columns, **Narration | Visuals | Sound**, with row-aligned entries: "Continuous Ambiance", "FX : Echoing footsteps on floor", "MUSIC: Faint note of string instrument". The row "CU of Rob's eyes. / Rob closes his eyes." carries "FX : Echoing sigh" after the last line "It's driving me crazy". The sequence then ends on a sound row, and the next sequence opens with "Continuous Park Ambiance".

### (b) Principle
Write the film in three parallel columns. Picture leads, narration only adds what the picture does not say, and sound is a column you write, not decoration. Sound can make a point on its own, ambience runs continuously, and silence is a deliberate, rare event. A sound beat may sit in its own row with no line next to it. That row is the reserved gap.

Note: the source's column order is Narration | Visuals | Sound. We use **PICTURE | NARRATION | SOUND** because Das p.42 says "the visual always comes first". The content is the same.

---

## Combined machine rules: CAN-N1..N4 (narration and sound)

Data comes from `story.json.script_columns`, `story.json.narration[]`, `shotplan.shots[]`, `narration.words.json` (`[{w,s,e}]`, seconds, after the voice offset), and `sound.json` (frames at `fps`).

**CAN-N1: three-column script.** Engine: director → `story.json.script_columns[]`; gate.
- **N1a** Each beat has ≥ 1 row `{row_id, beat, picture, narration, sound, t0, t1}`. `picture` and `sound` are never empty, and `narration` may be empty (a sound-only row). Check: a non-empty string after trimming, with `t0 < t1` inside the beat.
- **N1b** Each sequence has **≥ 1 sound-only row** (narration empty) of **≥ 0.6 s** [HOUSE]. Source: Das p.51, the sigh row.
- **N1c** `sound` names at least one bed (`AMB:`) per row, and every row either continues or changes the bed. Ambience is continuous (Das p.44). The sound designer turns `AMB:/FX:/MUSIC:` tokens into `sound.json.beds/cues/music`. Check: every frame is covered by ≥ 1 ambience bed except inside declared `silences[]`.
- **N1d** Every `narration[].id` appears in exactly one row, and every row's `t0..t1` contains its lines' `t0..t1`.

**CAN-N2: sound before words; reserved gaps.** Engines: director (declares the gaps), voice (creates them), sound designer (fills them), gate (verifies them against word timings).
- **N2a Sound-led lines.** A line with `sound_lead: {cue, lead_s}` puts the cue's anchor (onset) **0.4-2.5 s before the line's first word** `s` [HOUSE]. Check: `first_word.s − cue_onset_s ∈ [0.4, 2.5]`. No word may start within 0.15 s after the onset [HOUSE]. Source: Rabiger p.447 ("don't obscure them with talking"); Das p.44 (sound "make a point on its own").
- **N2b Reserved narration gaps.** `narration_gaps[] = {id, after_line, start_s, len_s, purpose ∈ {breath, key_sfx, reaction, music_swell}, filled_by: cue_id|bed_id|"room_tone"}`. Minimums [HOUSE]: `breath` ≥ 0.45 s, `key_sfx` ≥ the cue's active duration + 0.25 s and ≥ 0.6 s, `reaction` ≥ 1.0 s, `music_swell` ≥ 0.8 s (matches sound S-2 `bridgeGapS`). Each beat that has narration needs **≥ 1 gap ≥ 0.6 s**, and each suspense beat needs ≥ 1 `reaction` or `key_sfx` gap [HOUSE].
- **N2c Gaps survive voicing.** After TTS, recompute each gap from `narration.words.json`: `gap_real = next_word.s − prev_word.e`. Require `gap_real ≥ len_s − 0.05` [HOUSE]. If it is shorter, the voice engine splices presence or room tone into the stem at the gap point. It may lengthen a gap by **≤ +0.8 s** and never shortens a natural pause below 0.12 s (Rabiger p.454, "not to disrupt the natural rhythms") [HOUSE]. The gate then re-verifies.
  - *How ElevenLabs makes the gap:* synthesize per numbered block (Rabiger p.450, "number them"), with one block per contiguous run between gaps. Either concatenate with exact silence or room tone of `len_s`, or put `<break time="{len_s}s"/>` in the text for models that honour it. Always trust the measured words.json over the request.
- **N2d Gaps are filled.** Each gap's `filled_by` cue starts inside the gap (`onset ∈ [start, start + len − 0.15]`). The cue's peak may not overlap the next word by more than 0.05 s, and its tail must be ≥ 12 dB down by the next word's `s` [HOUSE]. A `room_tone` fill means the ambience bed continues with no duck. In the mix, the duck releases in gaps ≥ `bridgeGapS`.
- **N2e Never dead air.** No digital silence anywhere. Inside a gap, the ambience or presence bed stays at its bus level (Rabiger p.453-454 presence track; Das p.44 continuous ambiance). Deliberate full silences (`sound.json.silences` with all buses) last ≤ 2.0 s each, with **≤ 2 per short** [HOUSE]. Each needs a `reason` and must be followed by a sound re-entry cue (Das p.23).
- **N2f Narration does not lead.** Voiced speech (Σ(e−s) of words) ≤ **80 %** of runtime, and ≤ 85 % within any 20 s window [HOUSE]. Source: Das p.42, "Narration … does not lead the narrative"; Rabiger p.450, "thin the narration out".

**CAN-N3: key word versus reveal; operative words on cuts; no talking over reactions.** Engines: director (per-line `reveal_order`, per-cut `cut_word`), shotplan/compile (cut frames), gate (words.json × cut times).
- **N3a Operative word on the cut.** For each cut that the shotplan marks `cut_word: {line, word_idx}`, the cut frame time must fall in `[word.s − 0.10, word.s + 0.03]` s, about 3 frames before to 1 frame after at 30 fps [HOUSE]. Check: shot `from`/fps against words.json. Source: Rabiger pp.447-449, 454.
- **N3b Reveal order.** Each line has `reveal_order: {key_word_idx, reveal_shot, reveal_frame, order ∈ {before, after, on}}`, where `key_word = words[key_word_idx]` and `reveal_t = reveal_frame / fps` [HOUSE windows]:
  - `before` (the word primes the eye; the picture pays it off): `reveal_t − key_word.s ∈ [0.2, 1.5]`.
  - `after` (the picture reveals; the word names its significance): `key_word.s − reveal_t ∈ [0.25, 2.0]`.
  - `on` (a hit): `|key_word.s − reveal_t| ≤ 0.067` (2 frames).
  - Default for a threat or danger reveal: **after**, so the audience sees it before it is named. A narrator that names a threat before the audience can see it breaks CAN-S1, because the information comes through words rather than through the picture. Default for an instructional step verb: **before**, so the verb lands and then the demonstrating shot cuts in on the operative word.
- **N3c Perception order.** A line that names ≥ 2 visible things lists them in `perception_order[]`, and that order must match the line's mention order and the shot's `discovery_map` order. Source: Rabiger p.447, sun → landscape → woman.
- **N3d The first word on a new image.** For each cut that falls during speech, record `first_word_on_image`. It must not be a pronoun whose referent is not yet on screen [HOUSE]. Source: Rabiger p.447 ("sets the viewer looking for the 'she'") and p.447-448 ("the first word to fall on each new image").
- **N3e No talking over reactions.** `reaction_windows[]` come from the shotplan: the reserved close-up (CAN-C2), the turn-then-change settle (CAN-P1), character breaths and gasps, and any `narration_gaps` with purpose `reaction`. No word may overlap them, with a 0.15 s pad on each side [HOUSE]. Check: interval intersection with words.json.

**CAN-N4: narrator authority; when to cut a line.** Engines: director (`narrator` spec + per-line `purpose`/`adds`), voice (casting and direction tags), gate (lint + knowledge-scope check).
- **N4a Who speaks.** `story.json.narrator = {person ∈ {first, second, third_omniscient}, persona, authority (why we trust them), knowledge_scope ∈ {character, omniscient}, voice_id, direction}`. If it is missing, FAIL. Source: Rabiger p.445 ("doubt over who or what the narrator represents"); Das p.43 ("the most important decision").
- **N4b Knowledge scope.** If `knowledge_scope == "character"` (first person, or second person speaking as the hero), no line may assert a threat fact that is not in that beat's `character_knows`. An omniscient narrator may, but N3b still governs its timing.
- **N4c Purpose or cut.** Each line declares `purpose` from Rabiger's list (`setup`, `context`, `authenticity`, `momentum`, `inner_state`, `clarify`, `bridge`, `resolution`, `step` [house addition for survival instruction]) and an `adds` field (the information that is not in the picture or the sound). If `purpose` or `adds` is empty, the line is cut. Redundancy check: content-word overlap between the line and the union of the shot's declared visible items and the beat's sound tokens must be **≤ 50 %** [HOUSE]. Source: Rabiger p.450 ("complement, don't duplicate"); Das p.43.
- **N4d Lines the picture or sound already carries are cut.** If a `key_sfx` gap's cue already makes the point (a dry ignition click), any following line that restates it (for example "Nothing.") FAILs. Source: Das p.44, sound "make a point on its own".
- **N4e Value judgements only after the evidence.** Judgement tokens (`mistake`, `wrong`, `right`, `good`, `bad`, `stupid`, `smart`, `saved`, ...) may only occur at or after the `reveal_t` of the evidence shot that proves them [HOUSE token list]. Source: Rabiger p.445.
- **N4f Style lint.** No passive voice (`be` + past participle), sentences of **≤ 14 words**, speech rate **2.2-3.3 words/s** per block, no cliché list hits [HOUSE thresholds]. The ElevenLabs `speed` parameter must stay within **0.9-1.1**: the line has to fit its window without speeding up or slowing down (Rabiger p.447).
- **N4g Tryout and playback.** A scratch voicing of every line is laid against the animatic before the final voicing (an `animatic_tryout` record with the date and the gate result). After the final voicing, all of N2c, N3a, N3b and N3e are re-run against the final words.json (Rabiger pp.450, 452).
- **N4h When to cut narration entirely.** No line inside: the reserved close-up; the 0.4 s lead of a sound-led line; the planted-threat window if the line names the threat (N3b); any declared silence; or the payoff reaction beat. A beat whose information is fully carried by picture and sound has `narration: ""` in all of its rows.

---

## Required designs

### KNOWLEDGE TIMELINE (director output, `story.json.knowledge_timeline[]`)
One record per beat:
```json
{"beat":"B2","t0":3.3,"t1":11.2,"mode":"dramatic_irony",
 "audience_knows":["T_spout_forming","clock_800m"],"character_knows":[],
 "withheld_from_audience":[],"who_can_act":"character",
 "audience_question":"Will he look back before it is on him?",
 "threat_planted_shot":"H05","changes":["audience_knows+T_spout_forming"]}
```
`threats[] = {id, desc, planted_shot, planted_t, noticed_shot, noticed_at, peak_t, outcome}`. The gate computes the lead, the audience-only window, the mode consistency, the question pivots and the relief beat (CAN-S1a-d, S2a-f), and the clock properties (S3a-e) from `ticking_clock.readings[]` and `attempts[]`.

### THREE-COLUMN SCRIPT (`story.json.script_columns[]`)
Rows are `PICTURE | NARRATION | SOUND`, sound-only rows are allowed, and gaps are declared as their own rows that point at `narration_gaps[]`. The sound designer reads `FX:` tokens with `@gap:<id>` or `@lead:<line>` anchors and places `sound.json.cues[].at` from the measured word timings, not from the planned `t0`.

### REVEAL ORDER (per line, `narration[].reveal_order`, plus per cut `shots[].cut_word`)
The gate needs the key word index, the reveal shot and frame, and the order. It is verified against words.json and the compiled cut frames (N3a-b). Reaction windows come from the shotplan (N3e).

### NARRATOR (`story.json.narrator`) and the cut list
Authority, person and scope (N4a-b); per-line purpose and adds (N4c); the auto-cut list produced by N4d, N4e and N4h, written to `qc/canon_report.json` as `narration_cuts[]`.

---

## Worked examples

### 1. North Sentinel, night: "He heard the shore before he saw it."
Third-person omniscient narrator (`authority`: "a calm survival instructor who has read the incident reports"). fps 30.

| t (s) | PICTURE | NARRATION | SOUND |
|---|---|---|---|
| 0.0-1.1 | S01 WIDE: black-blue sea, dead-engine boat adrift, man at the stern facing seaward. Low on the horizon, the reef line is invisible. **A torch glows once on the dark tree line, frame left, behind him** (`threat_planted_shot: S01`, planted_t 0.4). | (none: sound-led row) | AMB: night swell, low. **FX: first breaker detonates on the reef, offscreen left, onset 0.10.** |
| 1.1-2.33 | S01 holds. The man's head lifts toward the sound. | "He heard the **shore** before he saw it." (first word s = 1.10; "shore" s = 1.62) | AMB continues; breaker tail. |
| 2.33-3.8 | S02 cut on **"saw"** (cut_word, word s = 2.38; cut 2.33 → in window). Moon clears and white water is revealed on the reef (`reveal_frame` 75 = 2.50 s). | (cont.) | FX: second breaker, nearer. |
| 3.8-4.9 | S03 MCU hands on the ignition key. | "He turned the key." | AMB. |
| 4.85-5.75 | S03 holds. | **gap G1 (key_sfx, start 4.85, 0.9 s)** | **FX: dry ignition click, no catch, onset 5.00, active 0.18 s.** |
| 5.75-6.6 | ~~"Nothing."~~ **cut by N4d**: the click already said it. | | AMB; breaker 3, closer (clock). |
| 6.6-9.45 | S04 reserved CU (CAN-C2): he turns, settles, and the thought lands (CAN-P1). He has noticed the torch: `noticed_at` 8.2. | **gap G2 (reaction, 2.0 s), no words** | FX: faint drum inland, under the surf. Breath (character). |
| 9.6-... | S05 WIDE: reef, boat, tree line in one frame. | "Every set of waves pushes him closer. **Do not** go ashore." | AMB; breaker 4. |

Checks:
- **S1a**: lead = 8.2 − 0.4 = 7.8 s ≥ 2.0. PASS.
- **S2c**: the question pivots at 8.2 from "Will the engine start before the reef?" to "Will he go ashore for help, where the torches are?". PASS.
- **S3a/b**: the clock is the breakers, louder and nearer (`environment` clock, severity 2 → 4 → 6). PASS.
- **N2a**: lead = 1.10 − 0.10 = 1.0 s. PASS.
- **N2c**: G1 measured as `"key."` e = 4.85 → next word s = 9.60 (after G2 and the cut line). PASS.
- **N2d**: click onset 5.00 ∈ [4.85, 4.85 + 0.9 − 0.15 = 5.60]. PASS.
- **N3b** for "shore": the order is `before` (the word primes, then the moon reveals the reef); reveal_t − s = 2.50 − 1.62 = 0.88 s ∈ [0.2, 1.5]. PASS. The syntax also follows the order of perception (heard → saw), which is Rabiger's p.447 rule applied to sound.
- **N3e**: no word in [6.45, 9.60) ("key." e = 4.85, next word s = 9.60). PASS.

### 2. Waterspout (`episodes/waterspout`), measured against the current files
- **S1a** PASS on paper: `suspense_devices` plants the spiral during L03 (about 7.0-9.0 s, held 2.0 s), and Theo sees it at 11.25 s, so the lead is ≥ 2.25 s. For the gate, it needs `threats[]` / `knowledge_timeline[]` records, which `story.json` does not have yet.
- **S3** PASS: the badge readings 800 → 400 → 200 → 60 → 30 M start at 3.4 s (4.5 % of runtime) and are re-shown at ≤ 20 s intervals, with severity rising strictly.
- **N2b/N2c/N2f FAIL (measured):** the planned gaps between lines are only 0.15-0.20 s. The largest inter-word gap in the voiced `audio/narration.words.json` is **0.37 s** ("found." → "Then", 13.61 s). Voiced speech is 56.85 s, but the planned line spans cover **71.6 of 75 s (95 %)**. There is no room anywhere for a breath, for the engine-start key SFX at L08, or for a reaction after the payoff L19 → L20 (0.20 s). The voiced track also ends at 76.31 s against a 75 s plan. Fix in the director: reserve G-gaps (≥ 1 per beat), for example a 0.9 s key_sfx gap after "Fire up the engine" for the starter and catch, and a 1.2 s reaction gap after L19's "turn ninety degrees" while the helm goes over. Then cut or merge lines to pay for them.
- **N4c candidate:** L06 "A spinning column of sea and cloud, taller than your mast." describes what the midpoint picture shows (Rabiger's "red raincoat"). Keep only information the picture cannot give, taken from `facts[]`, or cut the line and let the lightning reveal carry it.
- **N4e FAIL:** L08 "…Fire up the engine and run. **Mistake.**" passes judgement before the evidence. The proof is L10 ("slides … right down your wake", about 28.3 s). Move the judgement to after that reveal, or let the picture say it.
- **N3b:** for L05 "Then lightning flashes, and you see it." use `order: on` for "flashes" (the strobe frame within ±2 frames of the word), then `after` for "see it" (the funnel is visible ≥ 0.25 s before "see").

### 3. Survival steps (instructional lines)
For each step line (L15, L16, L19):
- `purpose: "step"`, `reveal_order.order: "before"` on the instruction verb (`never`, `track`, `turn`), with the demonstrating shot cutting on the operative word (N3a). For example, the L19 cut to the helm-over lands on "turn", at word s − 0.10 to + 0.03 s.
- The step badge (`sound.json.reveals[].kind = "step"`, `word`) is `on` the step number word.
- The "because" clause is the `adds` (N4c): information the picture cannot show.
- After each step demonstration there is a `breath` gap ≥ 0.45 s before the next line, and after step 3 a `reaction` gap ≥ 1.0 s with the hit filled by the near-miss roar (N2b/d). The judgement "saved you" comes only after the miss is on screen (N4e).

---

## Rules table

| ID | Rule | Engine / data | Automatic check | Threshold |
|---|---|---|---|---|
| CAN-S1a | Threat planted before noticed | director `threats[]`, shotplan gaze | `noticed_at − planted_t`; visible time | ≥ 2.0 s short / 4.0 s long; ≥ 1.0 s on screen [HOUSE] |
| CAN-S1b | Real audience-only window | `knowledge_timeline` | set difference per beat | threat ∈ A \ C |
| CAN-S1c | Relief owed | beats `mode: relief` | relief after peak; outcome enum | ≥ 1.5 s [HOUSE] |
| CAN-S1d | Surprise budget | beats `mode: surprise` | count, not climax | ≤ 1 / 90 s [HOUSE] |
| CAN-S2a | Per-beat knowledge record | `knowledge_timeline` | schema | all fields |
| CAN-S2b | Mode matches sets | same | computed vs declared | exact |
| CAN-S2c | Question pivots on knowledge/agency change | same | diff | same beat; future-tense |
| CAN-S2d | Keep the mind occupied | same | max interval without change | ≤ 12 s [HOUSE] |
| CAN-S2e | Disclosure in pieces | same | new items per beat | ≤ 2 [HOUSE] |
| CAN-S2f | Modes shift | same | ≥ 1 irony beat; ≥ 2 modes | count |
| CAN-S3a | Clock in the decor, deadline known | `ticking_clock` | first reading time | ≤ 20 % runtime [HOUSE] |
| CAN-S3b | Clock only worsens | `readings[]` | monotonic; re-show interval | ≤ 20 s [HOUSE] |
| CAN-S3c | Actions cost time | `attempts[]` | clock before ≠ after; duration | ≥ 1.5 s [HOUSE] |
| CAN-S3d | Time between attacks | threat hits | spacing | ≥ 3.0 s [HOUSE] |
| CAN-S3e | Anticipation > bang | impacts | anticipation / impact | ≥ 3× [HOUSE] |
| CAN-N1a-d | Three columns, sound-only rows, continuous ambience | `script_columns[]`, `sound.json.beds` | schema; coverage | ≥ 1 sound-only row ≥ 0.6 s/seq [HOUSE] |
| CAN-N2a | Sound before line | `narration[].sound_lead`, cues | first_word.s − onset | 0.4-2.5 s [HOUSE] |
| CAN-N2b | Reserved gaps | `narration_gaps[]` | min lengths; per-beat count | 0.45/0.6/1.0/0.8 s [HOUSE] |
| CAN-N2c | Gaps survive TTS | words.json | measured gap ≥ planned − 0.05; splice ≤ +0.8 s | [HOUSE] |
| CAN-N2d | Gaps filled | `sound.json.cues` | onset in gap; tail −12 dB at next word | [HOUSE] |
| CAN-N2e | No dead air; rare silence | beds, `silences` | coverage; silence length/count | ≤ 2.0 s, ≤ 2/short [HOUSE] |
| CAN-N2f | Narration doesn't lead | words.json | speech share | ≤ 80 % total, ≤ 85 %/20 s [HOUSE] |
| CAN-N3a | Operative word on cut | `shots[].cut_word`, words | cut − word.s | [−0.10, +0.03] s [HOUSE] |
| CAN-N3b | Key word vs reveal | `narration[].reveal_order` | key_word.s vs reveal_t | before 0.2-1.5; after 0.25-2.0; on ±2 f [HOUSE] |
| CAN-N3c | Perception order | `perception_order`, `discovery_map` | sequence equality | exact |
| CAN-N3d | First word on image | words × cuts | no dangling pronoun | [HOUSE] |
| CAN-N3e | No talk over reactions | `reaction_windows[]` | interval overlap | 0 overlap, 0.15 s pad [HOUSE] |
| CAN-N4a-b | Narrator spec and scope | `narrator` | schema; scope ⊆ character_knows | exact |
| CAN-N4c-d | Purpose/adds; redundancy cut | `narration[].purpose/adds` | content-word overlap | ≤ 50 % [HOUSE] |
| CAN-N4e | Judgement after evidence | lines × evidence shot | token time ≥ reveal_t | exact |
| CAN-N4f | Style and fit | text, words.json, voice params | passive, length, wps, speed | ≤ 14 words; 2.2-3.3 wps; speed 0.9-1.1 [HOUSE] |
| CAN-N4g | Tryout and playback | `animatic_tryout` | record present; re-run N2c/N3 | required |
| CAN-N4h | Where narration is cut | reaction/silence/lead windows | overlap | 0 |

## JSON schema fragment (additions)

```json
{
  "story.json": {
    "narrator": {"type":"object","required":["person","persona","authority","knowledge_scope","voice_id"],
      "properties":{"person":{"enum":["first","second","third_omniscient"]},"persona":{"type":"string"},
        "authority":{"type":"string"},"knowledge_scope":{"enum":["character","omniscient"]},
        "voice_id":{"type":"string"},"direction":{"type":"string"}}},
    "threats": {"type":"array","items":{"type":"object",
      "required":["id","planted_shot","planted_t","noticed_at","outcome"],
      "properties":{"id":{"type":"string"},"desc":{"type":"string"},"planted_shot":{"type":"string"},
        "planted_t":{"type":"number"},"noticed_shot":{"type":"string"},"noticed_at":{"type":"number"},
        "peak_t":{"type":"number"},"outcome":{"enum":["escaped","averted","survived_with_cost"]}}}},
    "knowledge_timeline": {"type":"array","items":{"type":"object",
      "required":["beat","mode","audience_knows","character_knows","who_can_act","audience_question","threat_planted_shot"],
      "properties":{"beat":{"type":"string"},"t0":{"type":"number"},"t1":{"type":"number"},
        "mode":{"enum":["shared","dramatic_irony","suppression","mystery","surprise","relief"]},
        "audience_knows":{"type":"array","items":{"type":"string"}},
        "character_knows":{"type":"array","items":{"type":"string"}},
        "withheld_from_audience":{"type":"array","items":{"type":"string"}},
        "who_can_act":{"type":"string","pattern":"^(character|nobody|other:.+)$"},
        "audience_question":{"type":"string"},
        "threat_planted_shot":{"type":["string","null"]}}}},
    "ticking_clock": {"type":"object","required":["kind","deadline","readings"],
      "properties":{"kind":{"enum":["diegetic_prop","environment","badge"]},"deadline":{"type":"string"},
        "readings":{"type":"array","items":{"type":"object","required":["t","value","severity"]}}}},
    "attempts[]": {"clock_before":{"type":"string"},"clock_after":{"type":"string"},"t0":{"type":"number"},"t1":{"type":"number"}},
    "script_columns": {"type":"array","items":{"type":"object",
      "required":["row_id","beat","t0","t1","picture","narration","sound"],
      "properties":{"row_id":{"type":"string"},"beat":{"type":"string"},"t0":{"type":"number"},"t1":{"type":"number"},
        "picture":{"type":"string","minLength":1},"narration":{"type":"string"},
        "sound":{"type":"string","minLength":1,"description":"AMB:/FX:/MUSIC: tokens, anchors @gap:<id> @lead:<line>"},
        "line_ids":{"type":"array","items":{"type":"string"}},"gap_id":{"type":["string","null"]}}}},
    "narration_gaps": {"type":"array","items":{"type":"object",
      "required":["id","after_line","start_s","len_s","purpose","filled_by"],
      "properties":{"id":{"type":"string"},"after_line":{"type":"string"},"start_s":{"type":"number"},
        "len_s":{"type":"number","minimum":0.45},
        "purpose":{"enum":["breath","key_sfx","reaction","music_swell"]},
        "filled_by":{"type":"string","description":"sound.json cue id, bed id, or room_tone"},
        "measured_len_s":{"type":"number","description":"written by voice/align after TTS"}}}},
    "narration[]": {
      "purpose":{"enum":["setup","context","authenticity","momentum","inner_state","clarify","bridge","resolution","step"]},
      "adds":{"type":"string","minLength":1},
      "sound_lead":{"type":["object","null"],"properties":{"cue":{"type":"string"},"lead_s":{"type":"number"}}},
      "reveal_order":{"type":"object","required":["key_word_idx","reveal_shot","reveal_frame","order"],
        "properties":{"key_word_idx":{"type":"integer"},"reveal_shot":{"type":"string"},
          "reveal_frame":{"type":"integer"},"order":{"enum":["before","after","on"]}}},
      "perception_order":{"type":"array","items":{"type":"string"}},
      "block":{"type":"integer","description":"numbered TTS block (Rabiger p.450)"}
    },
    "animatic_tryout": {"type":"object","properties":{"date":{"type":"string"},"report":{"type":"string"}}}
  },
  "shotplan.json shots[]": {
    "cut_word":{"type":["object","null"],"properties":{"line":{"type":"string"},"word_idx":{"type":"integer"}}},
    "reaction_windows":{"type":"array","items":{"type":"object","required":["from","to","kind"],
      "properties":{"from":{"type":"integer"},"to":{"type":"integer"},
        "kind":{"enum":["reserved_close_up","turn_then_change","breath","gasp","payoff_reaction"]}}}},
    "hero.gaze_away_from":{"type":"array","items":{"type":"string"},"description":"threat ids the character cannot see in this shot (CAN-S1a/b)"}
  }
}
```
