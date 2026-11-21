"""Checks the caption pages / STEP spans for Sentinel against ENGAGEMENT_RECIPE section 5.

  python3 factory/finish/test_captions.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from captions import build_pages, build_steps, is_number  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))


def main():
    ep = json.load(open(os.path.join(REPO, "episodes/sentinel/episode_v2.json")))
    words = json.load(open(os.path.join(REPO, ep["audio"]["wordsJson"])))
    fps, off = ep["fps"], ep["audio"]["offsetFrames"]
    pages = build_pages(words, fps, off, ep["captions"])
    steps = build_steps(words, ep["shots"], fps, off, ep["captions"])

    # every word appears exactly once, in order (caption text == transcript)
    flat = [w["t"] for p in pages for w in p["words"]]
    assert len(flat) == len([w for w in words if w["w"].strip()]), "word count mismatch"
    assert all(1 <= len(p["words"]) <= 3 for p in pages), "C-2: 1-3 words per page"
    durs = [(p["to"] - p["from"]) / fps for p in pages]
    assert min(durs) >= 0.25 - 1e-9 and max(durs) <= 1.2 + 1e-9, f"C-2: page duration {min(durs)}..{max(durs)}"
    assert all(a["to"] <= b["from"] for a, b in zip(pages, pages[1:])), "pages overlap"
    # C-5: page starts exactly on its first word's onset frame; words never shown before onset
    for p in pages:
        assert p["from"] == p["words"][0]["from"]
    share = sum(p["emph"] is not None for p in pages) / len(pages)
    assert share <= 0.35 + 1e-9, f"C-4: emphasis share {share:.2f}"
    for p in pages:
        nums = [i for i, w in enumerate(p["words"]) if is_number(w["t"])]
        if nums:
            assert p["emph"] is not None, f"C-4: number not emphasised: {p}"
    assert [s["n"] for s in steps] == [1, 2, 3, 4], steps
    assert all(s["to"] > s["from"] for s in steps)
    assert steps[-1]["to"] == 2076, steps[-1]  # step 4 ends where E30 (the tide) starts
    print(f"OK: {len(pages)} pages, mean {len(flat) / len(pages):.2f} words/page, "
          f"duration {min(durs):.2f}-{max(durs):.2f} s, emphasis {share:.0%}, steps {[(s['from'], s['to']) for s in steps]}")


if __name__ == "__main__":
    main()
