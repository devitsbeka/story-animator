"""Image metrics for golden-frame regression (numpy only).

ssim_map(a, b): Wang et al. 2004 SSIM on luma with an 11-tap Gaussian window (sigma 1.5), K1 0.01, K2 0.03, L 1.
compare(ref, cand, thresholds): SSIM (global mean + worst tile), mean colour / luminance deltas, edge-density delta
-> {"metrics", "pass", "reasons"}. diff_sheet(rows, out): reference | candidate | amplified |diff| per golden.
"""
from __future__ import annotations

import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float64)
DEFAULT_THRESHOLDS = {"ssim_min": 0.98, "tile_ssim_min": 0.94, "rgb_delta_max": 0.02, "luma_delta_max": 0.015,
                      "edge_delta_max": 0.15}


def load(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0


def save(a, path):
    from PIL import Image
    Image.fromarray(np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)).save(path)


def luma(a):
    a = np.asarray(a, dtype=np.float64)
    return a[..., :3] @ LUMA if a.ndim == 3 else a


def gaussian_kernel(size=11, sigma=1.5):
    x = np.arange(size) - (size - 1) / 2.0
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    return k / k.sum()


def _filt(x, k):
    """Separable 'valid' convolution with a 1-D kernel along both axes."""
    n = len(k)
    H, W = x.shape
    if H < n or W < n:
        raise ValueError(f"image {x.shape} smaller than the {n}-tap SSIM window")
    r = sum(k[i] * x[i:H - n + 1 + i, :] for i in range(n))
    return sum(k[i] * r[:, i:W - n + 1 + i] for i in range(n))


def ssim_map(a, b, k1=0.01, k2=0.03, L=1.0, size=11, sigma=1.5):
    x, y = luma(a), luma(b)
    if x.shape != y.shape:
        raise ValueError(f"shape mismatch {x.shape} vs {y.shape}")
    k = gaussian_kernel(size, sigma)
    c1, c2 = (k1 * L) ** 2, (k2 * L) ** 2
    mx, my = _filt(x, k), _filt(y, k)
    sxx = _filt(x * x, k) - mx * mx
    syy = _filt(y * y, k) - my * my
    sxy = _filt(x * y, k) - mx * my
    return ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))


def ssim(a, b, **kw):
    return float(ssim_map(a, b, **kw).mean())


def tile_ssim(smap, tiles=(4, 4)):
    """Worst mean SSIM over a grid of tiles (a local regression - a broken hand - hides in the global mean)."""
    H, W = smap.shape
    ty, tx = tiles
    vals = [smap[i * H // ty:(i + 1) * H // ty, j * W // tx:(j + 1) * W // tx].mean() for i in range(ty) for j in range(tx)]
    return float(min(vals))


def edge_density(a, thresh=0.1):
    y = luma(a)
    gx = np.zeros_like(y)
    gy = np.zeros_like(y)
    # Sobel
    gx[1:-1, 1:-1] = (y[:-2, 2:] + 2 * y[1:-1, 2:] + y[2:, 2:]) - (y[:-2, :-2] + 2 * y[1:-1, :-2] + y[2:, :-2])
    gy[1:-1, 1:-1] = (y[2:, :-2] + 2 * y[2:, 1:-1] + y[2:, 2:]) - (y[:-2, :-2] + 2 * y[:-2, 1:-1] + y[:-2, 2:])
    mag = np.hypot(gx, gy) / 4.0
    return float((mag > thresh).mean())


def stats(a):
    a = np.asarray(a, dtype=np.float64)
    return {"mean_rgb": [round(float(v), 5) for v in a[..., :3].reshape(-1, 3).mean(0)], "mean_luma": round(float(luma(a).mean()), 5),
            "edge_density": round(edge_density(a), 5), "size": [int(a.shape[1]), int(a.shape[0])]}


def compare(ref, cand, thresholds=None):
    th = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    sa, sb = stats(ref), stats(cand)
    if sa["size"] != sb["size"]:
        return {"metrics": {"ref": sa, "cand": sb}, "pass": False, "reasons": [f"size changed {sa['size']} -> {sb['size']}"], "thresholds": th}
    sm = ssim_map(ref, cand)
    m = {"ssim": round(float(sm.mean()), 5), "tile_ssim": round(tile_ssim(sm), 5),
         "rgb_delta": round(max(abs(x - y) for x, y in zip(sa["mean_rgb"], sb["mean_rgb"])), 5),
         "luma_delta": round(abs(sa["mean_luma"] - sb["mean_luma"]), 5),
         "edge_delta": round(abs(sb["edge_density"] - sa["edge_density"]) / max(sa["edge_density"], 1e-3), 5),
         "identical": bool(np.array_equal(np.asarray(ref), np.asarray(cand))), "ref": sa, "cand": sb}
    reasons = []
    if m["ssim"] < th["ssim_min"]:
        reasons.append(f"SSIM {m['ssim']} < {th['ssim_min']}")
    if m["tile_ssim"] < th["tile_ssim_min"]:
        reasons.append(f"worst-tile SSIM {m['tile_ssim']} < {th['tile_ssim_min']}")
    if m["rgb_delta"] > th["rgb_delta_max"]:
        reasons.append(f"mean colour delta {m['rgb_delta']} > {th['rgb_delta_max']}")
    if m["luma_delta"] > th["luma_delta_max"]:
        reasons.append(f"mean luminance delta {m['luma_delta']} > {th['luma_delta_max']}")
    if m["edge_delta"] > th["edge_delta_max"]:
        reasons.append(f"edge density changed {100 * m['edge_delta']:.1f}% > {100 * th['edge_delta_max']:.0f}%")
    return {"metrics": m, "pass": not reasons, "reasons": reasons, "thresholds": th}


def tile_strip(images, pad=4, bg=0.08):
    """Horizontal strip of equally sized images (a golden with several views)."""
    h = max(i.shape[0] for i in images)
    w = sum(i.shape[1] for i in images) + pad * (len(images) - 1)
    out = np.full((h, w, 3), bg)
    x = 0
    for i in images:
        out[:i.shape[0], x:x + i.shape[1]] = i[..., :3]
        x += i.shape[1] + pad
    return out


def diff_sheet(rows, out_png, max_w=1800):
    """rows: [(label, ref, cand, status)] -> one PNG: ref | cand | |diff| x4 (hot = changed), a header per row."""
    from PIL import Image, ImageDraw
    tiles = []
    for label, a, b, status in rows:
        if a is None or b is None or a.shape != b.shape:
            x = a if a is not None else b
            a = a if a is not None else np.zeros_like(x)
            b = b if b is not None and b.shape == a.shape else np.zeros_like(a)
        d = np.clip(np.abs(a - b).max(-1, keepdims=True) * 4.0, 0, 1)
        heat = np.concatenate([d, d * 0.35, 1.0 - d], -1) * (d > 0.004) + 0.05 * (d <= 0.004)
        row = tile_strip([a, b, heat], pad=6)
        sc = min(1.0, max_w / row.shape[1])
        im = Image.fromarray(np.clip(row * 255, 0, 255).astype(np.uint8))
        if sc < 1.0:
            im = im.resize((int(im.width * sc), int(im.height * sc)))
        canvas = Image.new("RGB", (im.width, im.height + 22), (20, 20, 24))
        canvas.paste(im, (0, 22))
        col = {"pass": (120, 220, 120), "fail": (255, 90, 90)}.get(status, (230, 200, 90))
        ImageDraw.Draw(canvas).text((6, 5), f"{label}   [{status.upper()}]   reference | candidate | |diff| x4", fill=col)
        tiles.append(canvas)
    W = max(t.width for t in tiles)
    H = sum(t.height for t in tiles) + 4 * len(tiles)
    sheet = Image.new("RGB", (W, H), (10, 10, 12))
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height + 4
    sheet.save(out_png)
    return out_png
