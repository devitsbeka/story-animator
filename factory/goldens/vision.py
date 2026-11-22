"""Vision-review hook for changed goldens: "is B better, the same or worse than A on <rubric>?"

Runs only when ANTHROPIC_API_KEY is available (the environment, or sourced from ~/.factory_secrets.env) and the
`anthropic` SDK is installed; otherwise returns verdict "unavailable". The verdict is advisory for humans and is
recorded with the compare result: `approve` refuses a golden judged "worse" unless the operator passes
--accept-worse with a note, and `compare --auto-approve-better` only ever approves "better" (never "worse").
"""
from __future__ import annotations

import base64
import io
import json
import os
import re

MODEL = os.environ.get("GOLDENS_VISION_MODEL", "claude-opus-5-5")
SECRETS = os.path.expanduser("~/.factory_secrets.env")
VERDICTS = ("better", "same", "worse")


def ensure_key(path=None):
    """Load ANTHROPIC_API_KEY from a KEY=VALUE secrets file into the environment (only that key) if unset."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    path = path or SECRETS
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if line.startswith("ANTHROPIC_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip("'\"")
                    if v:
                        os.environ["ANTHROPIC_API_KEY"] = v
                        return True
    except OSError:
        pass
    return False


def pair_png(ref_png, cand_png):
    from PIL import Image, ImageDraw
    a, b = Image.open(ref_png).convert("RGB"), Image.open(cand_png).convert("RGB")
    W, H = a.width + b.width + 12, max(a.height, b.height) + 26
    im = Image.new("RGB", (W, H), (16, 16, 18))
    im.paste(a, (0, 26))
    im.paste(b, (a.width + 12, 26))
    d = ImageDraw.Draw(im)
    d.text((6, 6), "A (approved reference)", fill=(230, 230, 230))
    d.text((a.width + 18, 6), "B (candidate)", fill=(230, 230, 230))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def prompt(rubric, metrics=None):
    return ("You review golden-frame regression renders of a code-built animation pipeline (Blender, no generative "
            "image models). The image shows A (the approved reference) on the left and B (the candidate after a code "
            f"change) on the right. Judge ONLY on this rubric: {rubric}.\n"
            + (f"Measured differences: {json.dumps(metrics)}\n" if metrics else "")
            + "Is B better, the same, or worse than A? Be strict: any new artifact (broken geometry, black/brown frame, "
              "missing texture, splayed fingers, uncanny face, lost detail) makes B worse. Answer as JSON.")


def _schema():
    return {"type": "object", "additionalProperties": False, "required": ["verdict", "confidence", "reason"],
            "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}, "confidence": {"type": "number"},
                           "reason": {"type": "string"}}}


def judge(ref_png, cand_png, rubric, metrics=None, client=None, model=MODEL):
    if client is None:
        if not ensure_key():
            return {"verdict": "unavailable", "reason": "ANTHROPIC_API_KEY not set (env or ~/.factory_secrets.env)"}
        try:
            import anthropic
        except ImportError:
            return {"verdict": "unavailable", "reason": "anthropic SDK not installed"}
        client = anthropic.Anthropic()
    data = base64.standard_b64encode(pair_png(ref_png, cand_png)).decode()
    try:
        resp = client.messages.create(
            model=model, max_tokens=4000,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema()}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                {"type": "text", "text": prompt(rubric, metrics)}]}])
    except Exception as e:  # noqa: BLE001 - the hook is advisory; the metric gate still decides
        return {"verdict": "unavailable", "reason": f"vision call failed: {type(e).__name__}: {str(e)[:200]}"}
    if getattr(resp, "stop_reason", None) == "refusal":
        return {"verdict": "unavailable", "reason": "model declined"}
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    mm = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(mm.group(0)) if mm else {}
    except ValueError:
        out = {}
    v = str(out.get("verdict", "")).lower()
    if v not in VERDICTS:
        return {"verdict": "unavailable", "reason": f"unparseable answer: {text[:200]}"}
    return {"verdict": v, "confidence": out.get("confidence"), "reason": out.get("reason", ""), "model": model}


# ------------------------------------------------------------------ single-frame rubric (stress scenarios)
RUBRIC = {
    "HANDS-1": "Hands read naturally: relaxed curl or a clear grip/gesture, fingers never flat-splayed, wrists not broken, a held object sits in the palm.",
    "FACE-2": "The facial expression reads instantly as the intended emotion ({emotion}) and is appealing (clear brows, lid tension, mouth corners).",
    "FACE-3": "The eyes are alive and believable: upper lids cover the top of the iris (unless fear/shock), eyes converge on a target, no dead stare.",
    "FRAME-1": "Framing is cinematic for a {size} shot: the face is not cropped, eyes in the upper part of a close-up, no camera inside geometry.",
}


def _rubric_schema(ids):
    item = {"type": "object", "additionalProperties": False, "required": ["id", "pass", "note"],
            "properties": {"id": {"type": "string", "enum": list(ids)}, "pass": {"type": "boolean"}, "note": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {"type": "array", "items": item}}}


def rubric(png, context, ids=tuple(RUBRIC), client=None, model=MODEL):
    """-> {id: {"status": pass|fail|unavailable, "note"}} for one rendered frame (HANDS-1, FACE-2, FACE-3, FRAME-1)."""
    if client is None:
        if not ensure_key():
            return {i: {"status": "unavailable", "note": "no ANTHROPIC_API_KEY"} for i in ids}
        try:
            import anthropic
        except ImportError:
            return {i: {"status": "unavailable", "note": "anthropic SDK not installed"} for i in ids}
        client = anthropic.Anthropic()
    with open(png, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode()
    items = "\n".join(f"- {i}: {RUBRIC[i].format(**context)}" for i in ids)
    text_prompt = ("Strict visual QC of one frame from a code-built 3D animation (Blender, stylised character). "
                   f"Scenario: {json.dumps(context)}. For each rubric item answer pass true/false with a short note.\n{items}")
    try:
        resp = client.messages.create(model=model, max_tokens=3000,
                                      output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _rubric_schema(ids)}},
                                      messages=[{"role": "user", "content": [
                                          {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                                          {"type": "text", "text": text_prompt}]}])
        txt = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        got = {x["id"]: x for x in json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["items"]}
    except Exception as e:  # noqa: BLE001 - advisory
        return {i: {"status": "unavailable", "note": f"{type(e).__name__}: {str(e)[:120]}"} for i in ids}
    return {i: ({"status": "pass" if got[i]["pass"] else "fail", "note": got[i].get("note", "")} if i in got
                else {"status": "unavailable", "note": "not answered"}) for i in ids}
