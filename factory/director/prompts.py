"""System prompts per stage. The long, stable part (role + recipe sections + vocabulary) is one cached
system block; the per-episode inputs go in the user turn, after the cache breakpoint."""
import json

from .recipes import stage_recipe_text
from .staging import ISLANDS, MARKS, vocabulary

COMMON = """You work in an automated, code-driven animation factory (factory/ARCHITECTURE.md). Episodes are directed as data
and rendered by Blender from code; no image or video generation models are used. Hero always centred, continuous camera
motion, cinematic consistent lighting; the look, lenses, light, captions, music and narration pace follow the STYLE section.

Your answer is one JSON document that must validate against the provided schema AND the automatable checklists of the
recipes below. A validator runs on your output; if it fails you get the list of failed rule ids and must return the full
corrected document. HARD items must be fixed. A HEUR item you deliberately keep must be logged in `overrides` as
{"rule": "<id>", "reason": "<why this serves the story>"}; use overrides sparingly and honestly."""

DEVELOP = """ROLE: Director, stage 1 DEVELOP. Turn the idea into story.json.

FORMAT short (60-120 s, 9:16): one story spine; HOOK -> CONTEXT -> ESCALATION_1 -> MIDPOINT -> ESCALATION_2 -> PAYOFF -> STING
(beats[] exactly in that order); narration about 2.8-3.1 words/s; 3-5 numbered survival steps ("Step one: ...").
FORMAT docuseries (15-25 min): cold open <= 90 s, a title beat, 5-8 chapters each with its own spine (hook, escalation,
payoff), a re-hook every 2-3 min, climax, resolution, tease of the next episode; narration about 2.4-2.7 words/s in a
documentary register. Every chapter carries one `short_candidate` (a self-contained 45-90 s beat with setup, turn, payoff
and its own hook line), staged so it can be re-cut vertically. Narration lines outside the cold open name their chapter.

Narration lines: ids L01, L02...; t0/t1 are seconds in the narration audio as you intend them to be delivered (plan the
timing at the w/s target, with short pauses between lines); every line has a delivery tag (excited, serious, whispers...).
Facts: only real, checkable facts with a source URL you are confident resolves; list in facts[].numbers every number as it
is spoken in the narration (e.g. "sixteen", "1981"). Never invent survival advice. Treat real peoples and places with
respect: no caricature, threats implied rather than shown when people are involved."""

BREAKDOWN = """ROLE: Breakdown agent, stage 2. Turn story.json into breakdown.json.

Every narration line maps to at least one scene (the picture the viewer sees while it plays); scenes follow narration
order. A line that straddles two pictures may appear in both scenes. List every element on screen (locations/sets, world,
character, props, vehicles, FX, HDRI and textures, overlays composited later, systems such as the acting rig) with what it
must DO on screen and library search terms; search_terms[0] is the primary noun the librarian matches (e.g. "radio", not
"handheld"). Mark story_specific for one-off things no stock asset can stand in for (a named historical ship) and
solves_climax for anything that resolves the climax (it must be planted before 40% of runtime)."""

DIRECT = """ROLE: Director + Cinematographer + Gaffer + Animator, stage 4 DIRECT. Turn story + breakdown + manifest into
shotplan.json. factory/director/compile.py turns your plan into episode.json for cloud/blender/render_episode.py.

CUT: shots are contiguous absolute film frames at 30 fps from 0; a narration word at audio time t plays at frame
audio_offset_frames + round(30 t). Cut on narration beats; each shot lists the narration lines playing over it and its
breakdown scene. Every shot has continuous camera motion and the hero centred; inserts centre the object.

CAMERA RIGS
- orbit: around a hero mark in yacht-local metres. az [start, end] degrees around the hero (0 = in front of his face,
  +90 = his left), dist [start, end] metres, height [start, end] metres above the target, fov [start, end] vertical
  degrees, target chest|face|hands|feet|sit or a height in metres, optional aim offset [x, y, z].
- path: straight eased move between two camera points and two look points. Points are {"frame": yacht|world|shore|island,
  "v": [...]}: yacht = yacht-local metres (space must be yacht); world = world metres; shore = [u, y, p] metres from the
  island's nearest shore point (u toward the island, p to the left); island = [dx, y, dz] from the island centre.
- ease: move | arrive | exit | linear | crash. handheld (default 0.15) / drift (default 0.08); shakes [{at, px, tau}].
YACHT STATES: afloat_lit, afloat_dark, aground, aground_hit (needs hit_frame), tide_lift (hit_frame = level-off frame),
leaving (offset [along_u, along_p] metres), absent; optional lights keys [[frame, 0..1], ...].
ISLAND: near | far | null. FIRES: [[frame, [6 intensities 0..1]], ...] (keys hold outside, step = 2 keys).
HERO: {mark, stance, stance_changes [[frame, stance]], poses [{pose, from, to, in, out, ease}], verbs [{verb, at, dur, amount}],
breath, seed, emotion}. Every hero shot shows an action motivated by the line (thought -> action).
PROPS: {prop, attach yacht|handR|handL, light keys, show keys, strobe frame}; defaults place yacht props and hand grips.
Only props whose manifest render_key is prop:<name> exist in the renderer."""


# >>> canon: the film-craft canon (factory/canon/*.md) injected BEFORE drafting; the validator enforces these ids
# (factory/canon/checks.py story_rules / plan_rules) with the thresholds in factory/canon/thresholds.yaml.
CANON_DEVELOP = """FILM-CRAFT CANON (mandatory; the validator checks every id below). Plan these with the story, not after it.
Times are narration-audio seconds like narration[].t0/t1; shot ids are the ids stage 4 will use (plan them now: S01, S02..).
- CAN-S1 Hitchcock's bomb: every danger is in threats[] {id, desc, planted_shot, planted_t, noticed_shot, noticed_at, peak_t,
  outcome escaped|averted|survived_with_cost}. The audience sees it >= 2.0 s (short; 4.0 s docuseries) before the character
  notices (noticed_at - planted_t), with >= 1.0 s of it on screen in that window while the hero is not looking. A feared
  threat ends in a relief record >= 1.5 s after its peak; it never kills the innocent. Surprise is rare (<= 1 per 90 s,
  never the climax).
- CAN-S2 knowledge_timeline[]: one record per beat (more records inside long beats) {beat, t0, t1, mode shared|dramatic_irony|
  suppression|mystery|surprise|relief, audience_knows[], character_knows[] (threat ids), withheld_from_audience[], who_can_act
  character|nobody|other:<id>, audience_question, threat_planted_shot, decision?}. dramatic_irony <=> audience_knows strictly
  contains character_knows on threat ids; shared <=> equal on threat ids. When character_knows gains a threat or who_can_act
  changes, audience_question changes in that same record and asks what happens next ("Will he look back?" -> "Can he turn
  in time?"). The question or mode changes at least every 12 s (short); at most 2 new audience_knows items per record; a
  short has >= 1 dramatic_irony record and >= 2 modes. Every beats[].id has a record. Inside threats' planted..noticed
  window every record has the threat in audience_knows and not in character_knows.
- CAN-S3 ticking_clock {what, kind diegetic_prop|environment|badge, deadline, readings[{t, value, severity}]}: first reading
  <= 20 % of runtime, severity strictly rising, re-shown every <= 20 s. attempts[] after the threat is planted carry t0, t1
  (>= 1.5 s apart) and clock_before != clock_after (ordinary actions cost visible time).
- CAN-N1 script_columns[] {row_id, beat, t0, t1, picture, narration, sound, line_ids, gap_id}: PICTURE first, narration only
  adds. Keep rows terse: picture <= 15 words, narration = the line ids it carries (e.g. "L03 L04", not the text) or "" for
  a sound-only row, sound = short tokens. Every narration line is in exactly one row whose t0..t1 contains it; rows stay inside their beat; every row's
  sound names an AMB: bed plus FX:/MUSIC: tokens; every beat has >= 1 sound-only row (narration "", line_ids []) of >= 0.6 s.
- CAN-N2 narration_gaps[] {id, after_line, start_s, len_s, purpose breath|key_sfx|reaction|music_swell, filled_by, desc}:
  breath >= 0.45 s, key_sfx >= 0.6 s, reaction >= 1.0 s, music_swell >= 0.8 s. start_s = the after_line's t1 and the next
  line starts at or after start_s + len_s (plan the line times around the gaps; the voice engine records them as silence).
  Every beat that has narration contains a gap >= 0.6 s; every dramatic_irony/shared beat has a reaction or key_sfx gap.
  filled_by: "FX:<sound>" for a key sound (the sound designer places it inside the gap), "room_tone", or "music".
  Planned line spans cover <= 85 % of duration_s and voiced speech <= 80 %: thin the narration to pay for the gaps.
  sound_lead {cue: "FX:<sound>", lead_s 0.4-2.5} on a line puts a featured sound before its words.
- CAN-N3 every line has reveal_order {key_word_idx (0-based index into the line's whitespace words), reveal_shot,
  reveal_frame (film frame = round(30 x audio seconds) + the stage-4 audio offset, normally 0), order before|on|after}:
  before = the word primes, the picture pays it off 0.2-1.5 s later (reveal_frame AFTER the word); after = the picture
  reveals first and the word names its meaning 0.25-2.0 s later (reveal_frame BEFORE the word: word time - reveal time in
  0.25..2.0; default for a threat: seen before named); on = within 2 frames. Words never play over the
  reserved close-up, a turn-then-change settle, or a reaction gap.
- CAN-N4 narrator {person first|second|third_omniscient, persona, authority (why we trust them), knowledge_scope character|
  omniscient, voice_id, direction}. Every line has purpose (setup|context|authenticity|momentum|inner_state|clarify|bridge|
  resolution|step) and adds (what picture and sound do not say). Never describe what the picture shows (Rabiger's red
  raincoat) or restate a key sound ("Nothing." after a dead click). Value judgements (mistake, wrong, right, good, bad,
  saved, smart, best, worst...) only at or after the evidence on screen: such a line has evidence {shot, frame} and the
  word plays after that frame. No passive voice; sentences <= 14 words; 2.2-3.3 words/s.
- Stage 4 reserves ONE hero close-up per sequence for a decision: give it a knowledge_timeline record where
  character_knows or who_can_act changes (or decision: true), and no narration over it (a reaction gap)."""

CANON_BREAKDOWN = """FILM-CRAFT CANON for the breakdown: each scene's `picture` says concretely what is EVIDENT on screen; the
validator compares narration against it (CAN-N4c: a line that only describes its picture is cut). Picture the threats[]
planted shots (the hero not looking), the reserved close-up beat, and the look-dev elements (boat + one practical lamp +
water, CAN-T1); name the one practical light that carries the night. Keep scenes to <= 2 narration lines."""

CANON_DIRECT = """FILM-CRAFT CANON (mandatory; the validator checks every id below on your shotplan AND the compiled episode).
- sequences[] {id, beats, shots [ids in order; together they cover every shot exactly once], tension mounting|plateau|
  release, action bool, reserved_close_up {beat, shot, reason} | null, discovery_map[], action_order {...} | null}.
- story.json planned shot references (threats[].planted_shot/noticed_shot, narration[].reveal_order, evidence) must point
  at real shots of your cut: keep those shot ids, or re-point them in story_links {reveal_order: {L01: {key_word_idx,
  reveal_shot, reveal_frame, order}}, evidence: {L08: {shot, frame}}, threats: {T1: {planted_shot, noticed_shot}}}.
  reveal_frame lies inside its shot; the planted shot lists gaze_away_from [threat id].
- CAN-C1 every location's first shots include a WS/EWS (>= 36 frames) whose establishes lists [hero, vessel,
  threat-or-zone]; put establishes ONLY on WS/EWS shots >= 36 frames; re-establish after <= 6 tighter shots.
- CAN-C2 ONE hero-face CU/ECU per sequence = reserved_close_up.shot, on the beat where what he knows or can do changes (or
  a decision: the knowledge_timeline record covering the CU's time must change character_knows / who_can_act or carry
  decision: true). All other hero shots are MCU or wider (inserts / POV exempt) or carry extra_cu_reason. The reserved CU
  lasts >= 45 frames and <= 180, carries turn_then_change, and no narration word plays over it (story gap there).
- CAN-E1 a sequence with action: true has action_order {obstacle_audience, obstacle_character, impact, cost_revealed} as
  shot ids in strictly increasing order: obstacle_audience starts >= 60 frames before obstacle_character and lists
  gaze_away_from; obstacle_character is followed by a POV/insert (or a shot whose establishes has "threat") and then a hero
  reaction shot; cost_revealed is its own held shot >= 75 frames with a discovery_map entry. Action shots >= 18 frames
  (inserts excepted); consecutive action shots differ in size class (or orbit az by >= 30 deg); a WS/EWS within 6 shots
  after the impact. tension mounting: last-third average shot length <= 0.8 x the first third. time_cut follows a cutaway.
- CAN-H1 every impact shot (action_order.impact, or camera.motivation "impact") has impact_handheld {impact_frame inside the
  shot, escape_frames 2-6, lag_frames 3-8, recover_frames <= 15, amplitude_deg 4-8}: the subject jolts out of frame and the
  camera catches up late (the compiler adds the layer; validators exempt the window). Never on the reserved CU.
  camera.handheld <= 0.12 on every shot (POV <= 0.18): shake is caused by events, never decorative. Set it explicitly.
- CAN-P1 turn then change (Animation Mentor): turn_then_change [{turn {from, to, deg}, settle_frames >= 6, change {from, to},
  emotion_from, emotion_to, mode post_turn}] with change.from = turn.to + settle_frames (the compiler schedules the emotion
  key + a thought blink). NO pose onset/release, stance change or emotion change in the first or last 10 frames of a shot:
  hero.poses[].from >= shot.from + 10 (or < shot.from when it continues from the previous shot), poses[].to >= shot.to
  (held through the cut) or <= shot.to - 10, stance_changes inside [from + 10, to - 10]. A move that must continue across
  the cut sets match_action: true on the shot. Every pose and verb has why (the beat or stimulus that causes it).
- CAN-L1 every sequence has discovery_map [{detail, shot, frame (>= 10 frames into the shot), light_reveal {source moon|key|
  rim|lightning|fire|practical:<name>, kind reflection|rim|practical_pool|lightning|silhouette|glint}, subordinate[]}]:
  light shows the viewer where to look; no hero pose/verb onset and no cut in [frame - 6, frame + 15].
- CAN-T1 lookdev_test {view, elements ["boat", "one_practical", "water"] (no actors/FX), practical, lighting_preset,
  water_material, hull_material}: tested and approved before FX/weather/acting renders.
- CAN-N3 cut_word {line, word_idx} on shots whose cut lands on an operative word (cut frame within -3..+1 frames of that
  word's start); reaction_windows [{from, to, kind}] on breaths/gasps/payoff reactions (no words there).
  If voiced_words.json is given, the narration is already recorded: cut, time reveals and place reaction windows against
  those measured times (film frame = audio_offset_frames + round(30 x s)), not the planned t0/t1."""

CANON = {"develop": CANON_DEVELOP, "breakdown": CANON_BREAKDOWN, "direct": CANON_DIRECT}
# <<< canon


def vocab_text():
    v = vocabulary()
    marks = "\n".join(f"  {k}: local {m['local']}, rotY {round(m['rotY'], 4)} - {m['desc']}" for k, m in MARKS.items())
    return (f"RENDERER VOCABULARY (from cloud/blender/acting.py and props.py)\nMARKS:\n{marks}\n"
            f"STANCES: {', '.join(v['stances'])}\nPOSES: {', '.join(v['poses'])}\nVERBS: {', '.join(v['verbs'])}\n"
            f"PROPS: {', '.join(v['props'])}\nISLAND PRESETS: {json.dumps(ISLANDS)}\n" + kits_text())


def kits_text():
    """World kits (factory/worlds): sets beyond the yacht/island world. A shot plays on one with "set": "<kit>"
    (or world.set), yacht.state absent, island null; hero/orbit marks are then the kit's marks."""
    from factory.worlds import kits, layout
    lines = ["WORLD KITS (shot.set or world.set = kit id; yacht absent, island null; marks below are set-local metres,"
             " rotY 0 faces +z; path points may use frame 'set'):"]
    for kid in kits.kit_ids():
        kit = kits.load(kid)
        if kit.get("legacy"):
            continue
        mk = layout.marks(kit)
        lines.append(f"  {kid} ({kit['sky']['time_of_day']}, lighting {kit['lighting']['preset']}): {kit['name']}")
        lines += [f"    {n}: local {m['local']}, rotY {round(m['rotY'], 4)}, {m['kind']} - {m['desc']}" for n, m in mk.items()]
        lines.append("    camera zones: " + "; ".join(f"{z['id']} {z['region']['shape']} y {z['y']}" for z in kit["camera_zones"]))
    return "\n".join(lines)


ROLE = {"develop": DEVELOP, "breakdown": BREAKDOWN, "direct": DIRECT}


def style_text(style=None):
    """STYLE section (factory/styles): the house look as data, injected into every stage's system block."""
    from factory.styles import DEFAULT_BY_FORMAT, style_prompt_text
    return "STYLE (factory/styles; the house look as data)\n" + style_prompt_text(style or DEFAULT_BY_FORMAT["short"])


def system_blocks(stage, style=None):
    parts = [COMMON, ROLE[stage], CANON[stage], style_text(style)]  # style system hook; canon before drafting
    if stage == "direct":
        parts.append(vocab_text())
    rec = stage_recipe_text(stage)
    if rec:
        parts.append("RECIPES (verbatim; the checklists are what the validator enforces):\n\n" + rec)
    return [{"type": "text", "text": "\n\n".join(parts), "cache_control": {"type": "ephemeral"}}]


def user_message(stage, idea, fmt, inputs):
    body = [f"IDEA: {idea}", f"FORMAT: {fmt}"]
    for name, doc in inputs.items():
        body.append(f"<{name}>\n{json.dumps(doc, ensure_ascii=False)}\n</{name}>")
    body.append({"develop": "Write story.json.", "breakdown": "Write breakdown.json.", "direct": "Write shotplan.json."}[stage])
    return {"role": "user", "content": "\n\n".join(body)}
