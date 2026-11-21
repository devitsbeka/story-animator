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


def vocab_text():
    v = vocabulary()
    marks = "\n".join(f"  {k}: local {m['local']}, rotY {round(m['rotY'], 4)} - {m['desc']}" for k, m in MARKS.items())
    return (f"RENDERER VOCABULARY (from cloud/blender/acting.py and props.py)\nMARKS:\n{marks}\n"
            f"STANCES: {', '.join(v['stances'])}\nPOSES: {', '.join(v['poses'])}\nVERBS: {', '.join(v['verbs'])}\n"
            f"PROPS: {', '.join(v['props'])}\nISLAND PRESETS: {json.dumps(ISLANDS)}")


ROLE = {"develop": DEVELOP, "breakdown": BREAKDOWN, "direct": DIRECT}


def style_text(style=None):
    """STYLE section (factory/styles): the house look as data, injected into every stage's system block."""
    from factory.styles import DEFAULT_BY_FORMAT, style_prompt_text
    return "STYLE (factory/styles; the house look as data)\n" + style_prompt_text(style or DEFAULT_BY_FORMAT["short"])


def system_blocks(stage, style=None):
    parts = [COMMON, ROLE[stage], style_text(style)]  # style system hook
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
