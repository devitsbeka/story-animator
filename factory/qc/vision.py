"""Vision-review hook: contact sheet + rubric prompt for a vision model.

`contact_sheet()` samples frames (one per shot keyFrame from the mp4, or from plates) into a
labelled grid with the house safe rect drawn on each tile. `build_prompt()` assembles a rubric
whose items quote the rule text straight from factory/recipes/{PIXAR,ENGAGEMENT}_RECIPE.md,
so the rubric follows the recipes when they change. `review()` sends sheet + prompt to Claude
when ANTHROPIC_API_KEY is set and the `anthropic` SDK is installed; otherwise it returns a
"skipped" result and the prompt/sheet stay on disk for a human or a later run.
"""
from __future__ import annotations

import base64
import json
import os
import re

import numpy as np

from .common import CANVAS, FAIL, PASS, SAFE_RECT, rule, skip

MODEL = "claude-opus-5-5"

# (rule id, section, recipe file, regex that finds the rule's line, question for the reviewer)
RUBRIC = [
    ("H-3", "HOOK", "ENGAGEMENT_RECIPE.md", r"\*\*H-3 ", "Tile 1 is frame 0. Does it show the hero (face visible, eyes open, an emotion that is not neutral), the threat in the same frame, and clear subject/background contrast?"),
    ("H-2", "HOOK", "ENGAGEMENT_RECIPE.md", r"\*\*H-2 ", "Do the first tiles' visuals and on-screen text express one single idea?"),
    ("H1", "FRAMING", "PIXAR_RECIPE.md", r"\*\*H1 ", "In every tile where the hero appears, are the hero's eyes on the vertical centre line (yellow guides are NOT drawn; judge by eye, x = 0.5 +- 0.08)?"),
    ("H2", "FRAMING", "PIXAR_RECIPE.md", r"\*\*H2 ", "Is all key action and every face inside the cyan safe rectangle (out of the top 12% and bottom 20%)?"),
    ("L7", "FRAMING", "PIXAR_RECIPE.md", r"L7 Silhouette", "Does the hero read as a clear silhouette against the background in each tile (>= 1 stop contrast or a clear hue difference)?"),
    ("L2", "FRAMING", "PIXAR_RECIPE.md", r"L2 Key azimuth", "Is the lighting direction and colour consistent across the shots of the same scene (cinematic, consistent moonlight key)?"),
    ("C-3", "CAPTIONS", "ENGAGEMENT_RECIPE.md", r"\*\*C-3 Size", "Is every caption legible against its plate (heavy weight, stroke or shadow, high contrast)?"),
    ("C-1.visual", "CAPTIONS", "ENGAGEMENT_RECIPE.md", r"\*\*C-1 ", "Is every caption, badge and number card inside the cyan safe rectangle?"),
    ("STYLE", "FRAMING", None, None, "Does every tile look like one coherent Pixar-quality stylized 3D film (no broken geometry, missing textures, stand-in capsules, black or blown-out frames, z-fighting)?"),
    ("T-1", "HOOK", "ENGAGEMENT_RECIPE.md", r"\*\*T-1 ", "Which tile would make the best cover, and does it have a clear face, threat and contrast?"),
]


def recipe_line(recipes_dir, fname, pattern):
    if not fname:
        return "House style: Pixar-quality stylized 3D, hero always centred, continuous camera motion, cinematic consistent lighting."
    try:
        with open(os.path.join(recipes_dir, fname)) as fh:
            for line in fh:
                if re.search(pattern, line):
                    return line.strip().lstrip("-[] ").strip()
    except OSError:
        pass
    return "(rule text not found in recipe)"


def build_prompt(recipes_dir, labels):
    items = []
    for rid, sec, fname, pat, q in RUBRIC:
        items.append({"id": rid, "section": sec, "rule": recipe_line(recipes_dir, fname, pat), "question": q})
    lines = [
        "You are the stage-9 visual QC reviewer for a 9:16 (1080x1920) animated short made entirely in code (Blender + Remotion; no image or video generation models).",
        "The attached contact sheet holds one tile per shot, in edit order, labelled with the shot id and time. The cyan rectangle on each tile is the platform safe area (x 65..888, y 290..1248 on 1080x1920).",
        "Tiles: " + "; ".join(labels),
        "",
        "Judge each rubric item strictly against the quoted rule. Mark pass only if every relevant tile satisfies it; list the failing tile labels.",
        "",
    ]
    for it in items:
        lines.append(f"- [{it['id']}] Rule: {it['rule']}\n  Question: {it['question']}")
    lines += ["", "Reply with JSON only, matching: {\"items\": [{\"id\": str, \"pass\": bool, \"confidence\": number 0..1, \"failing_tiles\": [str], \"note\": str}], \"summary\": str}"]
    return "\n".join(lines), items


def _tile(img, label, tw, th):
    from PIL import Image, ImageDraw
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((tw, th))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = (SAFE_RECT[0] / CANVAS[0] * tw, SAFE_RECT[1] / CANVAS[1] * th, SAFE_RECT[2] / CANVAS[0] * tw, SAFE_RECT[3] / CANVAS[1] * th)
    d.rectangle([x0, y0, x1, y1], outline=(0, 220, 255), width=1)
    d.rectangle([0, 0, tw, 16], fill=(0, 0, 0))
    d.text((3, 2), label, fill=(255, 255, 255))
    return im


def contact_sheet(frames, labels, out_png, cols=8, tw=135, th=240):
    """frames: list of float RGB arrays; writes a labelled grid PNG."""
    from PIL import Image
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (20, 20, 20))
    for i, (fr, lb) in enumerate(zip(frames, labels)):
        sheet.paste(_tile(fr, lb, tw, th), ((i % cols) * tw, (i // cols) * th))
    sheet.save(out_png)
    return out_png


def sample_from_video(path, ep, n=None):
    from . import video
    if ep and ep.shots and not n:
        pts = [(s["id"], s.get("keyFrame", (s["from"] + s["to"]) // 2) / ep.fps) for s in ep.shots]
        pts = [("f0", 0.0)] + pts
    else:
        dur = video.probe(path)["duration"]
        n = n or 12
        pts = [(f"t{i}", dur * i / n) for i in range(n)]
    frames, labels = [], []
    for name, t in pts:
        frames.append(video.frame_at(path, t))
        labels.append(f"{name} {t:.1f}s")
    return frames, labels


def sample_from_plates(plates_dir, n=24):
    from .plates import discover, load_plate
    found = discover(plates_dir)
    items = [(sid, f, p) for sid, g in sorted(found.items()) for f, p in sorted(g["frames"].items())]
    if len(items) > n:
        idx = np.linspace(0, len(items) - 1, n).round().astype(int)
        items = [items[i] for i in idx]
    return [load_plate(p) for _, _, p in items], [f"{sid} f{f}" for sid, f, _ in items]


def _schema():
    item = {"type": "object", "additionalProperties": False, "required": ["id", "pass", "confidence", "failing_tiles", "note"],
            "properties": {"id": {"type": "string"}, "pass": {"type": "boolean"}, "confidence": {"type": "number"},
                           "failing_tiles": {"type": "array", "items": {"type": "string"}}, "note": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["items", "summary"],
            "properties": {"items": {"type": "array", "items": item}, "summary": {"type": "string"}}}


def call_model(sheet_png, prompt, client=None, model=MODEL):
    """Send the contact sheet + rubric to Claude. Returns the parsed JSON dict."""
    if client is None:
        import anthropic  # optional dependency
        client = anthropic.Anthropic()
    with open(sheet_png, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode("utf-8")
    resp = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": _schema()}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": prompt},
        ]}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"vision review refused: {getattr(resp, 'stop_details', None)}")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"vision review returned no JSON (stop_reason={resp.stop_reason})")
    return json.loads(m.group(0))


def review(out_dir, recipes_dir, video_path=None, plates_dir=None, ep=None, client=None, run_model=None):
    """Write contact sheet + prompt; call the model if possible. -> (rules, info)."""
    os.makedirs(out_dir, exist_ok=True)
    if video_path:
        frames, labels = sample_from_video(video_path, ep)
    elif plates_dir:
        frames, labels = sample_from_plates(plates_dir)
    else:
        return [skip("VISION", "FRAMING", "no video or plates to sample")], {"status": "skipped"}
    sheet = contact_sheet(frames, labels, os.path.join(out_dir, "contact_sheet.png"))
    prompt, items = build_prompt(recipes_dir, labels)
    with open(os.path.join(out_dir, "vision_prompt.md"), "w") as fh:
        fh.write(prompt + "\n")
    info = {"contact_sheet": sheet, "prompt": os.path.join(out_dir, "vision_prompt.md"), "tiles": len(labels), "model": MODEL}
    if run_model is None:
        run_model = client is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not run_model:
        info["status"] = "skipped"
        info["reason"] = "ANTHROPIC_API_KEY not set"
        return [skip(f"{it['id']}.vision", it["section"], "vision model not run (ANTHROPIC_API_KEY not set); prompt + sheet written", source="vision")
                for it in items], info
    try:
        res = call_model(sheet, prompt, client=client)
    except ImportError:
        info.update(status="skipped", reason="anthropic SDK not installed (pip install anthropic)")
        return [skip(f"{it['id']}.vision", it["section"], info["reason"], source="vision") for it in items], info
    except Exception as e:  # noqa: BLE001 - network/API errors must not crash QC
        info.update(status="error", reason=str(e)[:500])
        return [skip(f"{it['id']}.vision", it["section"], f"vision call failed: {str(e)[:200]}", source="vision") for it in items], info
    with open(os.path.join(out_dir, "vision_review.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    info.update(status="ok", summary=res.get("summary"))
    sec = {it["id"]: it["section"] for it in items}
    rules = []
    for r in res.get("items", []):
        rid = str(r.get("id"))
        if rid not in sec:
            continue
        hard = rid in ("H-3",)  # vision verdict on H-3 is a HARD rule (ENGAGEMENT 8.2)
        rules.append(rule(f"{rid}.vision", sec[rid], PASS if r.get("pass") else FAIL, r.get("confidence"), "vision reviewer: pass",
                          {"failing_tiles": r.get("failing_tiles"), "note": r.get("note")}, hard=hard, source="vision"))
    return rules, info
