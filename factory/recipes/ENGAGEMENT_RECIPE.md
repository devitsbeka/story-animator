# ENGAGEMENT RECIPE

Machine-applicable rules for 9:16 explainer-survival shorts (60–120 s) for YouTube Shorts, TikTok and Reels. The voice is energetic MrBeast-style narration and the visuals are Pixar-grade 3D, as in Zack D. Films "what would you do if..." shorts.

Read by: Stage 1 Develop (`story.json`), Stage 4 Direct (`episode.json`), Stage 5 Voice+Sound (`sound.json`) and Stage 9 QC (`qc/report.json`). See `factory/ARCHITECTURE.md`.

## How to read this file

- Every rule has an ID (`H-`, `R-`, `N-`, `P-`, `C-`, `S-`, `T-`, `M-`) and is tagged as one of:
  - **[SRC]**: backed by the cited source.
  - **[HOUSE]**: a house default derived from sources or genre convention. It is a tunable parameter, not a fact. Retune it from our own analytics (section 8).
- The checklists use these field names:
  - `t`: seconds from frame 0.
  - `shots[]`: the shots in `episode.json`.
  - `words[]`: word timings from Stage 5.
  - `cues[]`: the cues in `sound.json`.
- The numbers assume 30 fps (1 s = 30 frames).
- Source caveat: the MrBeast guide is a leaked 2022 onboarding memo written for long-form video. We map its *principles* to shorts; we do not copy its timestamps.
  - [alexanderjarvis.com copy](https://www.alexanderjarvis.com/memo-how-to-succeed-in-mrbeast-production/)
  - [Simon Willison notes](https://simonwillison.net/2024/Sep/15/how-to-succeed-in-mrbeast-production/)
  - [Tubefilter summary](https://www.tubefilter.com/2024/09/17/mrbeast-internal-production-guide-leaked-key-points/)

### Core evidence used throughout

- **Viewed vs swiped away (VVSA)** is an official YouTube Shorts metric: "the percentage of times viewers viewed your Shorts versus swiped away" ([YouTube Help](https://support.google.com/youtube/answer/12220281); [reach](https://support.google.com/youtube/answer/9314355?hl=en)).
- **Paddy Galloway's study** covered 3.3B views and 5,400 Shorts across 33 channels ([thread](https://threadreaderapp.com/thread/1646898356419981315.html)):
  - Shorts under 60% VVSA "rarely performed well".
  - The best Shorts sat at 70–90% VVSA.
  - Longer Shorts performed better on average.
  - Shorts with AVD above 50 s averaged 4.1M views.
  - The first second must be "really punchy".
- **YouTube view counting:** since 2025-03-31 a Shorts view counts every start or replay, with no minimum watch time. "Engaged views" (the old metric) still drive YPP and payouts ([TechCrunch](https://techcrunch.com/2025/03/26/youtube-is-changing-how-youtube-shorts-views-are-counted); [Tubefilter](https://www.tubefilter.com/2025/03/26/youtube-shorts-views-counting-stats/)). Consequence: loops and replays inflate views, so we optimise *engaged* views and APV, not raw views.
- **MrBeast guide:**
  - "The first minute ... is the most important minute"; most loss happens there.
  - AVD and AVP are the success metrics.
  - "No dull moments".
  - "As you get deeper in the video the stakes get higher".
  - "Video endings must always be abrupt".
  - Never signal the end.
  - Title and thumbnail set expectations, and the opening must confirm them.
- **TikTok official guidance** ([Creative best practices](https://ads.tiktok.com/help/article/creative-best-practices?lang=en)):
  - Introduce the proposition in the first 3 s.
  - Prioritise the hook in the first 6 s.
  - On-screen text at about 5–10 words/s.
  - Use sound, music and transitions to hold engagement.
  - Stay inside the UI safe zone.
  - TikTok "is best when sound is on" ([Creative Codes](https://ads.tiktok.com/business/library/Creative_Codes_ENG.pdf)).
- **Curiosity gap:** curiosity is deprivation caused by a *perceived gap in knowledge* (Loewenstein 1994, *Psych. Bulletin* 116(1):75–98, [PDF](https://www.cmu.edu/dietrich/sds/docs/loewenstein/PsychofCuriosity.pdf)).
  - Veritasium's "Clickbait is Unreasonably Effective" ([summary](https://recapio.com/digest/clickbait-is-unreasonably-effective-by-veritasium)) argues that a gap is legitimate only if the video *fills it*; broken promises cause backlash ([Boing Boing](https://boingboing.net/2025/12/09/clickbait-isnt-the-problem-broken-promises-are.html)).
- **Kallaway's three-hook alignment:** the visual, spoken and text hooks must all point at *one* idea. Mismatches split attention, and the visual hook is the strongest of the three ([summary](https://recapio.com/digest/how-to-create-a-killer-hook-impossible-to-skip-by-kallaway); [transcript](https://sozai.app/transcript/create-killer-hook-impossible-skip/)).

---

## 1. HOOK (0.0–3.0 s)

**Goal:** stop the swipe. VVSA is decided here.
- Galloway: under 60% VVSA almost never works.
- Meta data, widely repeated but not verified against the original: about 65% of people who watch 3 s reach 10 s ([B&T](https://www.bandt.com.au/five-reasons-facebook-wants-adopt-video-first-strategy/)).
- Nielsen for Facebook: 47% of an ad's value is delivered in the first 3 s ([IAB/Facebook IQ](https://iabeurope.eu/wp-content/uploads/facebookiq_video_one_sheeter_uk.pdf)).

### 1.1 Allowed hook formats (pick exactly one per episode, recorded in `story.json.hook.format`)

| Code | Format | Template | Survival example |
|---|---|---|---|
| `IMR` | In medias res: open at peak danger, then rewind | "[Danger already happening]. You have [N] [units]." | Water pouring into the cabin at night. "Your boat is sinking, and you have 90 seconds." |
| `STK` | Stakes statement, second person, with a number | "If you [situation], you have [number] [units] before [consequence]." | "If you fall through ice, you have 10 minutes before your arms stop working." |
| `QST` | Direct question plus a forced choice | "Would you [A] or [B]?" | "Shark circling. Do you swim or freeze?" |
| `SHK` | Visual shock or impossible image, no setup | [Impossible or extreme image] + "This is what happens when..." | A wave towering over a tiny yacht |
| `MYT` | Wrong instinct: "Most people do X. It kills them." | "Everyone's first instinct is [X]. That's exactly what gets you killed." | "Most people swim toward shore in a rip current. That's the mistake." |

- **H-1 [SRC]** The proposition (what the video is about, plus the stakes) must be stated or shown by t ≤ 3.0 s (TikTok official).
  - [HOUSE] The first spoken word starts at t ≤ 0.3 s.
  - There is no logo, title card, fade-in or "hey guys". The MrBeast guide's rule to cut the hype and *show* it applies.
- **H-2 [SRC]** Visual, spoken and on-screen text hooks express the *same* single idea (Kallaway: single subject, single question).
- **H-3 [HOUSE]** The first frame (frame 0) must contain all of the following, so the auto-generated cover reads:
  - the hero (face visible, eyes open, an emotion other than neutral, preferably fear or shock);
  - the threat in the same frame;
  - motion already in progress (no static establishing shot);
  - a luminance contrast of at least 4.5:1 between the subject and the background.
- **H-4 [SRC]** The opening must deliver what the title promises (MrBeast: a mismatch with the thumbnail or title makes viewers "feel lied to"; Veritasium on broken promises).
- **H-5 [HOUSE]** Hook text overlay:
  - 2–6 words, all caps or title case;
  - contains a number or a threat noun;
  - on screen from frame 0 to at least 2.0 s;
  - placed in the upper-middle safe band (section 5).
- **H-6 [HOUSE]** The hook opens a curiosity gap that is not closed before 50% of runtime: the *Core Question* (CQ), e.g. "how do you survive this?" (Loewenstein's gap).
- **H-7 [HOUSE]** The hook narration is at most 2 sentences and at most 18 words, staccato: the first sentence is 8 words or fewer (Kallaway: staccato sentences).
- **H-8 [HOUSE]** Something visibly moves or changes within the first 0.5 s (camera push, object motion or FX). Zack D.-style "the camera is almost always moving" ([Recapio](https://recapio.com/digest/i-copied-a-youtube-channel-with-ai-3d-animation-tools-by-dan-kieft)).
- **H-9 [HOUSE]** An impact SFX or music hit lands on frame 0–6. The music bed is already playing at frame 0, with no fade-in.

**Checklist: Hook** (validated on `story.json` + `episode.json` + `words[]`)
- [ ] `story.json.hook.format ∈ {IMR,STK,QST,SHK,MYT}`
- [ ] `words[0].start ≤ 0.30`
- [ ] Hook narration word count ≤ 18; first sentence ≤ 8 words
- [ ] Hook narration contains `you|your` AND (a digit or number word OR a threat lexicon word)
- [ ] `hook.text_overlay` has 2–6 words, `start == 0`, `end ≥ 2.0`
- [ ] Embedding similarity between hook text, hook narration and the shot-0 description ≥ 0.6 (one idea)
- [ ] Vision QC on frame 0: face detected AND threat object detected AND subject/background contrast ≥ 4.5
- [ ] Optical-flow magnitude over frames 0–15 > threshold (no static open)
- [ ] `cues[]` contains an `impact|hit` with `frame ≤ 6`; music `start_frame == 0`
- [ ] The CQ is defined, and its answer beat's `t ≥ 0.5 × duration`
- [ ] Banned openers absent: "hey", "welcome", "in this video", "today we", "let me tell you"

---

## 2. RETENTION STRUCTURE

### 2.1 Beat map (normalised to duration D; stored in `story.json.beats[]`)

| Beat | Window | Job | Source |
|---|---|---|---|
| HOOK | 0–3 s | Stakes, CQ, frame-0 shock | §1 |
| CONTEXT | 3 s → 0.15D | Set the rules fast: where you are, what you have, the clock. Show, don't explain. | MrBeast "show it" |
| ESCALATION 1 | 0.15D → 0.40D | First attempt or instinct, then complication ("but") | South Park rule |
| RE-HOOK / MIDPOINT | ~0.45D | The biggest "wow" visual plus a new, harder question | MrBeast 3- and 6-minute re-engagements, scaled to shorts |
| ESCALATION 2 | 0.45D → 0.80D | Higher stakes, the clock shrinks, steps | MrBeast "stakes get higher" |
| PAYOFF | 0.80D → 0.95D | Answer the CQ with the most surprising fact | Loewenstein: close the gap |
| STING / LOOP | last 1–3 s | Abrupt end, and the last line feeds back into the first frame | MrBeast "abrupt endings" |

- **R-1 [HOUSE]** Open loops:
  - At least 1 primary loop (the CQ), opened in the hook and closed in the payoff.
  - At least 2 secondary loops, e.g. "but there's one thing that matters more, and we'll get to it", each closed within 25 s of opening.
  - At every point after 3 s, at least one loop is open, until the final 3 s.
- **R-2 [HOUSE]** Re-hooks every 8–12 s. A re-hook is a narration line containing a contrast or tension token ("but", "except", "then", "suddenly", "the problem is", "here's the catch", "worse") together with a visual escalation (new threat, scale change or time-skip card).
  - For 60 s that is at least 5 re-hooks; for 120 s at least 10.
  - The midpoint re-hook (about 0.45D) must be the *largest* visual event before the payoff. This is the MrBeast wow-factor principle: "only we can show this".
- **R-3 [SRC]** But/therefore causality: consecutive beats link with BUT or THEREFORE, never "and then" (Parker and Stone, [Cheat Sheet](https://www.cheatsheet.com/entertainment/south-park-trey-parker-and-matt-stone-1-rule.html/); [No Film School](https://nofilmschool.com/2015/04/tony-zhou-storytelling-video-essay-f-fake-therefore-but-and-then)). Each `beats[i].link ∈ {BUT, THEREFORE}`.
- **R-4 [SRC]** Escalation curve: the stakes score (0–10, assigned by the director per beat) is non-decreasing from CONTEXT to PAYOFF, with at most one dip of no more than 2 points (a breath before the climb). MrBeast: "stakes get higher"; stair-step fireworks example.
- **R-5 [SRC]** Never signal the end: no "in conclusion", "finally", "that's it", "thanks for watching" or "so remember" before the last 1.5 s (MrBeast: "Don't ever signal the end").
- **R-6 [HOUSE]** Payoff timing: CQ answered at t ∈ [0.80D, 0.95D]. Everything after the answer is at most 4 s (MrBeast: abrupt endings).
- **R-7 [HOUSE]** Loop-back for rewatch. This matters because replays count as views on Shorts, per the 2025 view change above. Choose one per episode:
  - (a) the last sentence is grammatically completed by the first sentence, e.g. "...and that's why you never—" → "Your boat is sinking";
  - (b) the final frame matches frame 0 in composition (SSIM ≥ 0.5) for a seamless loop;
  - (c) the last line poses a reversed or harder question the hook re-answers.
- **R-8 [HOUSE]** Time compression:
  - Survival time is shown with on-screen clock or day cards ("HOUR 3", "00:42 LEFT") at least every 20 s.
  - This is MrBeast's "crazy progression": compressing days early builds investment.
- **R-9 [SRC]** No dull moments ("No dull moments in videos"): no window of 3 s or more with neither narration, a new visual event, nor an SFX/music accent (except a deliberate suspense hold, P-4).

**Checklist: Retention**
- [ ] `beats[]` covers HOOK→STING in order, with windows within ±10% of the table
- [ ] Every `beats[i>0].link ∈ {BUT, THEREFORE}`; the transcript has no "and then" between beats
- [ ] Re-hook timestamps: count ≥ ⌊D/12⌋; max gap ≤ 12 s; first re-hook ≤ 12 s
- [ ] Midpoint event at 0.40–0.55D has the highest `visual_scale` score before the payoff
- [ ] Stakes scores non-decreasing (≤ 1 dip of ≤ 2)
- [ ] Open-loop timeline: at least 1 loop open for all t ∈ [3, D−3]; every loop closed by D
- [ ] CQ answer at 0.80–0.95D; tail after the answer ≤ 4 s
- [ ] End-signal lexicon absent before D−1.5 s
- [ ] Loop-back method declared and verified (text-join test OR SSIM(frame_last, frame_0) ≥ 0.5)
- [ ] Dead-air scan: no 3 s window with zero events, unless tagged `suspense_hold`
- [ ] Clock or day card at least every 20 s when `story.time_pressure == true`

---

## 3. NARRATION / SCRIPT

- **N-1 Speed [SRC+HOUSE]**
  - Explainer baseline is 150–160 wpm; high-energy promo is 165–180 wpm; above 180 wpm causes fatigue ([Breadnbeyond](https://breadnbeyond.com/how-many-words-does-a-60-seconds-explainer-video-needs/); [Typecast](https://typecast.ai/learn/?p=15068)).
  - House target: **2.8–3.1 words/s (170–185 wpm) average**. The hook may peak at 3.3 w/s.
  - The payoff slows to 2.3–2.6 w/s so the key fact lands.
  - Word budget: 60 s ≈ 160–180 words; 90 s ≈ 240–270; 120 s ≈ 320–360. That is 90–95% of the runtime voiced; the rest goes to holds and SFX moments.
- **N-2 Sentences [HOUSE]** Average sentence length 6–10 words; maximum 16. At least 30% of sentences are 5 words or fewer (staccato). Flesch-Kincaid grade ≤ 6 ("Me like simple. The simpler the better." MrBeast).
- **N-3 Second person [HOUSE]** "you/your" appears at least once every 2 sentences, i.e. ≥ 1 per 15 words. The viewer is the protagonist; the 3D hero is "you". Do not narrate in the third person ("he") except for a one-line flashback.
- **N-4 Specificity and numbers [HOUSE]**
  - At least one concrete number (time, distance, temperature, percentage, count) every 10 s of narration.
  - Every number is in `story.json.facts[]` with a source URL, so there is no invented survival advice.
  - Prefer exact over round numbers ("47 seconds", not "under a minute").
- **N-5 Tension lexicon [HOUSE]** At least 1 tension word per 20 words, from a list such as: but, suddenly, except, only, last, never, deadly, mistake, wrong, seconds, before, until, worse, catch, problem, almost.
  - Cap: at most 3 superlatives per 60 s, so the voice does not become shouty.
- **N-6 Step lists [HOUSE]**
  - The survival method is delivered as **3–5 numbered steps** ("Step one: ...").
  - Each step: ≤ 14 words of instruction, then a "because" or consequence clause, then a visual demonstration.
  - Each step gets an on-screen step badge (section 5).
  - The last step is the counter-intuitive one.
- **N-7 Surprise placement [HOUSE]**
  - Rank facts by surprise (a director's 1–10 score).
  - The #1 fact goes in the PAYOFF (0.80–0.95D).
  - The #2 fact goes at the midpoint re-hook.
  - The #3 fact may be teased in the hook *without* revealing the answer.
  - The best fact is never spent in the first 50% (Loewenstein: closing the gap ends the curiosity).
- **N-8 Explicit loop phrases [HOUSE]** Use 1–2 per video: "Stay with me, because step three is the one that saves you." Each must be paid off (R-1).
- **N-9 Performance tags [HOUSE]** Every line carries an ElevenLabs-style delivery tag (`[urgent]`, `[whisper]`, `[beat]`, `[excited]`).
  - Energy is high by default.
  - At least 1 `[whisper]` or low-energy line before the payoff, for contrast.
- **N-10 Banned [HOUSE]** No filler ("basically", "actually", "so yeah"), no hedging ("kind of", "maybe"), and no calls to action ("like and subscribe") in the body.

**Checklist: Narration** (on `story.json.narration` + `words[]`)
- [ ] words/s overall ∈ [2.8, 3.1]; hook ≤ 3.3; payoff segment ∈ [2.3, 2.6]
- [ ] Total words within the budget for D (±10%)
- [ ] Mean sentence length ∈ [6, 10]; max ≤ 16; share of ≤ 5-word sentences ≥ 0.30; FK grade ≤ 6
- [ ] `you|your` density ≥ 1/15 words
- [ ] Number density ≥ 1 per 10 s; every number maps to `facts[].source_url` (HTTP 200)
- [ ] Tension-word density ≥ 1/20 words; superlatives ≤ 3 per 60 s
- [ ] Steps: 3–5 with "Step one..." ordinal pattern; each ≤ 14 words before the consequence clause
- [ ] Top surprise fact `t ∈ [0.80D, 0.95D]`; #2 at 0.40–0.55D; none of the top 3 answered before 0.5D
- [ ] Every "stay with me" or "we'll get to it" promise has a matching payoff beat
- [ ] At least 1 low-energy tag before the payoff; banned-phrase list absent

---

## 4. PACING (editing)

Context:
- Hollywood average shot length has fallen to about 2.5–4 s (Cutting et al., [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3485803); [Cornell](https://news.cornell.edu/node/271563)).
- The MrBeast guide asks for "lots of quick scene changes" in the most exciting stretch.
- In the Zack D. style something is always moving.
- Short-form runs faster than film. Shot counts below are [HOUSE] values consistent with the ~33 shots per episode in `ARCHITECTURE.md`.

- **P-1 Average shot length (ASL) by section [HOUSE]**

| Section | ASL | Range | Notes |
|---|---|---|---|
| HOOK (0–3 s) | 1.0–1.5 s | 0.6–2.0 | 2–3 shots |
| CONTEXT | 2.0–2.5 s | 1.2–3.5 | Establish geography once |
| ESCALATION 1 | 1.8–2.2 s | 1.0–3.0 | |
| MIDPOINT wow | 2.5–4.0 s | ≤ 5.0 | Let the spectacle breathe; camera moves inside the shot |
| ESCALATION 2 / steps | 1.5–2.0 s | 0.8–3.0 | One shot per step clause |
| PAYOFF | 2.5–3.5 s | ≤ 4.5 | Hold on the key image |
| STING | 1.0–2.0 s | | Abrupt |

- Overall ASL target is 1.8–2.6 s: 60 s ≈ 25–33 shots; 120 s ≈ 46–60 shots.
- **P-2 Pattern interrupt cadence [HOUSE]**
  - A *visual change* happens at least every 1.5–3.0 s. Counted as visual changes: a cut, a camera-move start, a scale or punch-in (≥ 115% zoom), a new on-screen graphic, a VFX event, or a lighting change.
  - A *major* interrupt happens every 6–10 s: a location or angle reversal, a time-skip card, a freeze-frame with label, X-ray or cutaway, or a split comparison.
- **P-3 Cut on narration [HOUSE]**
  - Cuts land on word boundaries: within ±2 frames of a `words[].start`, preferably on stressed words or numbers.
  - Each new step or number triggers a cut or punch-in within 3 frames.
- **P-4 Suspense holds [HOUSE]**
  - 1–2 per video, each 1.0–2.0 s: no cut, a slow push-in, narration pause or whisper, music drop to bed or silence. Placed immediately *before* the midpoint reveal and the payoff reveal.
  - A hold is exempt from P-2, but its camera must move (≥ 2% frame scale change per second).
- **P-5 Beat drop / silence [HOUSE]** Exactly 1 hard silence (music and ambience under −40 dBFS) of 0.3–0.8 s right before the payoff reveal, followed by an impact SFX on the reveal frame.
- **P-6 No repetition [HOUSE]** The same camera preset and framing is not used twice in a row. At most 25% of shots reuse any one preset.
- **P-7 Motion in every shot [SRC-ish]** Every shot has camera or subject motion; no locked-off static frames longer than 0.8 s (Zack D. style, [Recapio](https://recapio.com/digest/animating-a-zack-d-films-style-youtube-short-complete-process-by-osasart)).

**Checklist: Pacing** (on `episode.json.shots[]` + rendered cut list)
- [ ] ASL per section within the table range; overall ASL ∈ [1.8, 2.6]
- [ ] Shot count within the bounds for D
- [ ] Visual-change events: max gap ≤ 3.0 s outside tagged holds
- [ ] Major interrupts: max gap ≤ 10 s
- [ ] ≥ 80% of cuts within ±2 frames of a word start
- [ ] 1–2 `suspense_hold` shots, each 1.0–2.0 s, directly preceding the midpoint or payoff reveal; camera scale change ≥ 2%/s
- [ ] Exactly one silence gap of 0.3–0.8 s before the payoff, with an impact cue on the reveal frame
- [ ] No consecutive identical camera presets; max preset share ≤ 25%
- [ ] Per-shot optical flow > threshold (no static > 0.8 s)

---

## 5. CAPTIONS / KINETIC TYPE

### 5.1 Safe zones on 1080×1920

There is no official organic-feed spec. Values are third-party measurements and ad specs, so we use the *union* (most conservative):
- **TikTok:** bottom 422–480 px, right 140–173 px, left 65 px, top about 240 px ([Kapwing](https://www.kapwing.com/video-editor/tiktok/safe-zone); [RightBlogger](https://rightblogger.com/blog/tiktok-safe-zone-template); [Remotion overlay](https://www.remotion.dev/elements/overlays/social-safe-zones/)). TikTok's ads guidance says the zone grows with caption length.
- **YouTube Shorts:** a commonly cited set is top 288, bottom 672, left 48, right 192 ([Merginit](https://merginit.com/tools/safe-zone-checker/youtube-shorts); Google's [universal safe zones PDF](https://services.google.com/fh/files/misc/universalsafezones-youtube.pdf) gives no pixels).
- **Instagram Reels (Meta ads spec):** top 14% (269 px), bottom 35% (672 px), sides 6% (65 px) ([Lilach Bullock](https://www.lilachbullock.com/instagram-reels-safe-zone/); [Hopper](https://www.hopperhq.com/blog/instagram-reel-size/)).

**House safe rectangle (all three platforms):**

```
Canvas            1080 x 1920
UNSAFE top        y < 290        (status bar, search, tabs)
UNSAFE bottom     y > 1248       (1920 - 672: username, caption, music, Shorts title)
UNSAFE right      x > 888        (1080 - 192: like/comment/share stack)
UNSAFE left       x < 65
SAFE RECT         x 65..888, y 290..1248   (823 x 958 px)
CAPTION BAND      y 1000..1240   (lower-middle, inside safe rect, baseline ≈ 1180)
HOOK/TITLE BAND   y 300..520     (upper-middle)
FACE/ACTION BAND  y 420..1100    (keep hero eyes ≈ y 600–800, rule of thirds)
```

- **C-1 [HOUSE]** Every caption, badge, number card and the hero's face must sit inside the SAFE RECT. Background plates may bleed full frame.
- **C-2 Words per caption [SRC+HOUSE]**
  - TikTok recommends 5–10 words/s for text overlays. Our captions track narration at about 3 w/s.
  - Show **1–3 words per caption page** (2 preferred); never more than 4 words or 1 line (2 lines only for step badges).
  - Page duration 0.25–1.2 s.
- **C-3 Size [HOUSE]**
  - Caption cap-height 70–95 px (font size about 90–120 px at 1080 width) in a heavy rounded or grotesk font (weight ≥ 800).
  - White fill with an 8–12 px black stroke, plus a drop shadow at 40–60% opacity.
  - Line width ≤ 800 px.
  - Contrast ≥ 7:1 against the local plate (measured).
- **C-4 Emphasis [HOUSE]**
  - The active word gets a highlight colour: style-locked accent, default yellow #FFD400, with danger red #FF3B30 for threat words and green #34C759 for the solution.
  - Plus a scale pop to 110–120% over 3–4 frames.
  - Numbers always get emphasis. Emphasis covers at most 1 word per page and at most 35% of pages.
- **C-5 Sync [HOUSE]** A caption appears within ±2 frames (±67 ms) of `words[].start` and never ahead of the audio by more than 2 frames.
- **C-6 Hook text [HOUSE]** A persistent hook title (H-5) sits in the HOOK/TITLE BAND for 0–2.0 s minimum (up to 3 s), at 80–110 px, and must not overlap the caption band.
- **C-7 Step badges and clocks [HOUSE]** "STEP 1"-style badges and countdown clocks go in the upper band (y 300–520), left-aligned at x ≥ 65, and persist for the duration of the step.
- **C-8 Burned-in captions [SRC]** Captions are burned in; do not rely on platform auto-captions. Captions give context and help sound-off viewers (TikTok best practices). Also upload an SRT for accessibility and search.

**Checklist: Captions** (on Remotion caption track + rendered frames)
- [ ] All text bounding boxes ⊂ SAFE RECT (65..888, 290..1248) on every frame (sampled every 5 frames)
- [ ] Hero face bbox ⊂ SAFE RECT in ≥ 90% of frames
- [ ] Words per page ≤ 4 (mean ≤ 3); single line except badges
- [ ] Page duration ∈ [0.25, 1.2] s
- [ ] Cap-height ∈ [70, 95] px; stroke ≥ 8 px; measured contrast ≥ 7:1
- [ ] Emphasised pages ≤ 35%; all numeric tokens emphasised
- [ ] |caption.start − word.start| ≤ 2 frames for ≥ 95% of words
- [ ] Hook title visible over [0, ≥ 2.0 s] and not overlapping captions
- [ ] Caption text equals the transcript (WER ≤ 2% vs the ASR of the final mix)

---

## 6. SOUND

- **S-1 Loudness [SRC]**
  - Master to **−14 LUFS integrated (±1), true peak ≤ −1.0 dBTP**.
  - YouTube, including Shorts, normalises to about −14 LUFS ([Fora Soft](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026); [OpenClip](https://openclip.app/learn/audio-normalization); [Frame.io](https://workflow.frame.io/guide/loudness-for-youtube)).
  - TikTok and Instagram publish no target; their adaptive loudness sits at about −14 internally. Some vendors advise −10 to −12.
  - **[HOUSE]:** a single −14 master for all platforms, plus an optional −12 LUFS TikTok/Reels variant as an A/B test.
  - Short-term loudness (3 s) stays within −17…−10 LUFS, except during P-5 silence.
- **S-2 Voice priority and ducking [SRC+HOUSE]**
  - Voice is the anchor: dialogue at about −16 to −14 LUFS-S, peaking at −6 to −3 dBFS pre-limiter.
  - Music under voice sits **18–22 dB below** the voice (Storyblocks: −18 to −22; Premiere auto-duck starting point −18 dB ([Storyblocks](https://www.storyblocks.com/resources/tutorials/how-to-balance-audio-premiere-pro); [Adobe](https://helpx.adobe.com/premiere-pro/how-to/automatic-audio-ducking.html))). Some guides allow a smaller 3–9 dB offset, but energetic narration over dense music needs the larger gap.
  - Ambience beds sit 24–30 dB below the voice.
  - Duck attack 50–100 ms, release 250–400 ms.
  - Music rises to −6…−10 dB relative to voice level during narration gaps of 0.8 s or longer.
- **S-3 Music energy map [HOUSE]** Store `cues[].energy` on a 1–5 scale:

| Section | Energy | Music behaviour |
|---|---|---|
| HOOK | 4–5 | Starts at frame 0 on a downbeat or hit; no intro |
| CONTEXT | 3 | Pulse or percussion bed, tempo 100–130 BPM |
| ESCALATION 1 | 3→4 | Add layers every 8–12 s, in step with the re-hooks |
| Pre-midpoint hold | 2 | Filter-sweep or strip to bed |
| MIDPOINT | 5 | Drop or hit on the reveal frame |
| ESCALATION 2 | 4 | Driving; step changes on step badges |
| Pre-payoff | 0 | P-5 hard silence 0.3–0.8 s |
| PAYOFF | 4–5 | Impact + resolve |
| STING | 3→cut | Hard stop on the last word or a sting; **no fade-out** (MrBeast abrupt ending; supports loop) |

  - Music changes section or layer at least every 15 s.
  - Cuts align to the beat grid within ±2 frames for at least 50% of cuts.
- **S-4 SFX density [HOUSE]**
  - **Whoosh or swish** on ≥ 60% of cuts and on every camera whip or punch-in; length 6–15 frames, peaking on the cut frame.
  - **Riser** of 1.0–3.0 s before every reveal (midpoint, payoff, each step demonstration), ending exactly on the reveal frame.
  - **Impact or boom** on the hook frame, the midpoint reveal, the payoff reveal and each step badge.
  - **UI ticks or pops** on every caption emphasis and number card, at low level (−20 dB relative to voice).
  - **Diegetic Foley** for every on-screen action (water, wind, creaks), because the 3D world must sound physical.
  - Overall rate 25–45 spot SFX per minute. Never more than 3 transient SFX within any 0.5 s window, to avoid mush.
- **S-5 Sound-on design [SRC]** The video must work with sound on (TikTok Creative Codes) *and* be legible muted (burned-in captions, C-8).
- **S-6 Ambience [HOUSE]** A continuous world bed (ocean, wind, night) with no gaps under 1 s, except P-5.

**Checklist: Sound** (on `sound.json` + final mix analysis via `ffmpeg ebur128` / pyloudnorm)
- [ ] Integrated loudness ∈ [−15, −13] LUFS; true peak ≤ −1.0 dBTP
- [ ] Short-term loudness ∈ [−17, −10] outside the declared silence
- [ ] Measured voice-to-music level difference during speech ∈ [18, 22] dB (stem analysis); ambience ≥ 24 dB below
- [ ] Music cue at frame 0; no fade-in > 3 frames; final cue ends with a hard stop (no fade > 6 frames)
- [ ] Energy sequence matches the map; layer or section change max gap ≤ 15 s
- [ ] Whoosh on ≥ 60% of cuts; riser ending ±1 frame on each tagged reveal; impact on hook, midpoint, payoff and steps
- [ ] SFX per minute ∈ [25, 45]; no 0.5 s window with > 3 transients
- [ ] Exactly one silence of 0.3–0.8 s (< −40 dBFS) before the payoff
- [ ] No ambience gaps > 1 s outside the silence
- [ ] ASR intelligibility: WER of narration in the full mix ≤ 5% (voice not masked)

---

## 7. THUMBNAIL / TITLE / FIRST FRAME

On Shorts the feed autoplays, so frame 0 *is* the thumbnail for most viewers. A chosen cover only appears on the channel grid, in search and on the Shorts shelf. Titles still set expectations (MrBeast: title and thumbnail set expectations; "I Survived" beats "I Spent" for intrigue).

- **T-1 [HOUSE]** First frame = cover candidate (H-3). Also export the best of 5 candidate frames (scored by face-emotion intensity, threat visibility, contrast and saliency centre inside the SAFE RECT) as the custom cover for YouTube and TikTok.
- **T-2 [HOUSE]** Cover text: 3 words or fewer, ≥ 110 px, inside the upper band. It must not repeat the title verbatim; it complements it.
- **T-3 [HOUSE] Title:**
  - ≤ 60 characters, with the front-loaded hook in the first 40.
  - Second person or a scenario: "What if your boat sinks at night?"
  - Contains a number or threat noun.
  - At most 2 emoji (TikTok/IG captions); 0–3 hashtags (#shorts is optional).
- **T-4 [SRC]** Honest gap: the title's promise must be answered in the video (Veritasium Type 1 vs Type 2; MrBeast "feel lied to"). The QC LLM verifies that the title question is answered in the PAYOFF.
- **T-5 [HOUSE]** The title, cover text and hook line form a set: the same single idea (Kallaway alignment) without three identical strings.

**Checklist: Title / cover**
- [ ] Title length ≤ 60 chars; hook keywords within the first 40; contains a number or threat noun
- [ ] Cover text ≤ 3 words, inside the upper band, ≥ 110 px
- [ ] Frame 0 passes H-3 vision checks; custom cover saliency centroid inside the SAFE RECT
- [ ] LLM judge: "Does the payoff answer the title's question?" = yes
- [ ] Title ≠ hook text ≠ cover text (string distance > 0.3), but embedding similarity ≥ 0.6

---

## 8. METRICS AND SELF-QC

### 8.1 Benchmarks (post-publish targets)

| Metric | Floor | Target | Stretch | Source |
|---|---|---|---|---|
| Viewed vs swiped away (YT) | 60% | 70% | 80–90% | Galloway thread (above) |
| APV / average % viewed (60–120 s Short) | 50% | 70% | ≥ 90% (loops push > 100% on some dashboards) | vidIQ reports ~73.6% avg on its own Shorts ([vidIQ](https://vidiq.com/blog/post/increase-audience-retention-youtube/)); quso.ai median ≈ 45%, top 10% ≈ 91% ([quso](https://quso.ai/research/video-retention-benchmarks)) |
| AVD | 30 s | 45 s | > 50 s | Galloway: AVD > 50 s averaged 4.1M views |
| 3 s hold (TikTok "watched ≥ 3 s" / curve at 3 s) | 65% | 75% | 85% | [HOUSE], Meta 3 s→10 s (65%) relay |
| Retention at 50% of runtime | 45% | 60% | 75% | [HOUSE] |
| Rewatch / loop rate (views ÷ engaged views − 1) | 5% | 15% | 30% | [HOUSE], enabled by the 2025 view-count change |
| Engagement (likes ÷ views) | 2% | 4% | 7% | [HOUSE] |

Caveats:
- YouTube publishes no official Shorts benchmarks; compare against our own trailing median per length bucket ([Bytecap](https://www.bytecap.io/research/youtube-shorts-retention-benchmarks); [1of10](https://1of10.com/blog/youtube-shorts-analytics/)).
- Long-form retention (about 23.7% average; 55% lost in the first 60 s, per the Retention Rabbit 2025 report via [Stripo](https://research.stripo.email/youtube-benchmarks)) is *not* comparable to Shorts.

### 8.2 Pre-publish predicted-retention model (Stage 9, automatable)

Compute `engagement_score ∈ [0,100]` from the draft. Each sub-score is the pass rate of its section's checklist, weighted by where swipes happen:

```
score = 30*Hook + 20*Retention + 15*Narration + 15*Pacing + 10*Captions + 10*Sound
gate:   Hook == 100% (all hard rules)  AND  score >= 85   → PUBLISH
        score 70–85                                        → AUTO-FIX loop (max 2 iterations)
        score < 70 OR any HARD fail                        → back to Stage 1/4
HARD rules: H-1, H-3, H-4, R-5, N-4 (fact sourcing), C-1, S-1
```

### 8.3 Automated checks the factory runs (tools)

1. **Transcript metrics**: from `words[]` (ElevenLabs timings) or WhisperX on the final mix. Covers w/s, sentence stats, lexicon densities, number density, banned phrases, the "and then" scan and loop-promise matching. Done with Python regex plus an LLM-judge for the CQ, BUT/THEREFORE links and the surprise rank.
2. **Cut detection**: PySceneDetect (`ContentDetector`, threshold 27) on the final mp4 gives the ASL per section, max gaps and cut-to-word alignment.
3. **Motion**: OpenCV Farneback optical-flow magnitude per frame, which flags static stretches over 0.8 s and the static open.
4. **Vision**: frame 0, the cover candidates and 1 frame per shot go to a VLM plus a face detector (MediaPipe). It checks face, emotion, threat object, contrast ratio, eyeline and face bbox inside the SAFE RECT.
5. **Safe-area OCR**: PaddleOCR or Tesseract on every 5th frame, asserting all text bboxes are inside the SAFE RECT. Overlay a platform UI PNG (Remotion `social-safe-zones`) for a human-visible contact sheet.
6. **Caption sync**: compare Remotion caption JSON against `words[]` (±2 frames), and WER of OCR text vs the transcript.
7. **Audio**: `ffmpeg -af ebur128=peak=true` for integrated, short-term and true-peak values. pyloudnorm on stems for the voice-to-music difference. An onset detector (librosa) for SFX density and transient clustering. Silence detection (`silencedetect=n=-40dB:d=0.3`) for P-5.
8. **Loop test**: SSIM(frame_last, frame_0), plus an LLM text-join check of last line → first line.
9. **Retention simulator** (optional and tunable): a per-second swipe-hazard model, `hazard(t) = base(t) × Π penalties`. Penalties apply for dead air, a missing re-hook in the trailing 12 s, a static frame, or an unclosed loop count of 0. It is fitted on our own published Shorts' retention curves (YouTube Analytics API `audienceWatchRatio`, plus TikTok analytics export). It outputs a predicted curve; reject if predicted APV < 65% or the 3 s hold < 70%.
10. **Feedback loop**: after 72 h, pull VVSA, APV, AVD and the retention curve per published episode. Map retention drops of more than 3 percentage points within 2 s to the shot or beat at that timestamp, and log them to `qc/postmortem.json`. Every 20 episodes, refit the [HOUSE] parameters (ASL, re-hook interval, w/s, energy map) by regression against APV. Store the fitted values in `styles/<style>.json` so the recipe numbers remain data.

**Checklist: Metrics and QC**
- [ ] `qc/report.json` contains a per-section pass rate, `engagement_score` and a list of HARD failures
- [ ] Gate logic applied (publish, auto-fix or return), with iteration count ≤ 2
- [ ] Predicted APV ≥ 65% and predicted 3 s hold ≥ 70% (once the simulator is fitted)
- [ ] Post-publish job scheduled at +72 h to pull VVSA, APV, AVD, engaged views and the retention curve
- [ ] Drops > 3 pp mapped to shot IDs and written to `qc/postmortem.json`
- [ ] Parameter refit every 20 episodes; changes diffed and versioned in `styles/<style>.json`

---

## Appendix A: Reference template for a 75 s episode (House defaults)

```
t(s)   beat          narration (w/s)  shots  sound                        text
0.0    HOOK  IMR     3.2              3      impact f0, music E5          "90 SECONDS TO LIVE" (300-520 band)
3.0    CONTEXT       2.9              5      bed E3, whoosh/cut           clock "01:30" badge
11     ESC1 (BUT)    3.0              6      layer+, riser→rehook @20     captions 2 w/page
24     re-hook       3.0              2      impact                       —
33     MIDPOINT wow  2.7 (#2 fact)    2      hold 1.5 s → drop E5         "STEP 1"
36     ESC2 steps    3.0              10     step impacts, whooshes       STEP 2..4 badges
60     hold+silence  —                1      0.5 s silence                —
61     PAYOFF        2.4 (#1 fact)    3      impact, resolve E4           emphasis green
71     STING/LOOP    3.0              2      hard stop on last word       last line → first line
75     END (≈34 shots, ASL 2.2 s, ~215 words, 8 re-hooks)
```

## Appendix B: Lexicons (seed lists; extend in `styles/<style>.json`)

- **threat:** drown, sink, freeze, shark, fire, storm, wave, cliff, venom, hypothermia, dehydration, avalanche, rip, lightning, dark
- **tension:** but, suddenly, except, only, last, never, mistake, wrong, seconds, before, until, worse, catch, problem, almost, instead
- **end-signal (banned before D−1.5 s):** in conclusion, finally, that's it, to sum up, thanks for watching, so remember, in summary
- **banned openers:** hey, hi guys, welcome, in this video, today we, let me tell you, have you ever wondered (allowed only as `QST` with a forced choice)
