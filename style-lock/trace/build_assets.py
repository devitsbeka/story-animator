"""Turn the extracted layer PNGs (trace/layers/*.png) into code-drawable JSON assets.

Every layer becomes:
  sil       outline path of the layer's silhouette (evenodd), filled with silColor underneath,
            so tracing pinholes never show what's behind;
  base      (optional) a coarse colour grid the renderer blurs: keeps soft light and gradients
            that colour-cluster tracing would flatten;
  paths     vtracer spline paths: the drawn detail (ink lines, shapes, texture).
Face features are pure ink shapes: silhouette only, filled with the ink colour.
"""
import cv2, numpy as np, json, re, sys, vtracer

INK = '#1a0a04'

def pushpull(im, known):
    im = im.astype(np.float32); k = known.astype(np.float32)
    levels = []; a, w = im * k[..., None], k
    while min(w.shape) > 4:
        levels.append((a, w)); a = cv2.pyrDown(a); w = cv2.pyrDown(w)
    est = a / np.maximum(w[..., None], 1e-6)
    for a, w in reversed(levels):
        up = cv2.resize(est, (w.shape[1], w.shape[0]), interpolation=cv2.INTER_LINEAR)
        cur = a / np.maximum(w[..., None], 1e-6); ww = np.clip(w * 4, 0, 1)[..., None]
        est = cur * ww + up * (1 - ww)
    return est

def sil_path(mask, eps=0.7):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cnts:
        if cv2.contourArea(c) < 4: continue
        c = cv2.approxPolyDP(c, eps, True)[:, 0, :]
        out.append('M' + ' L'.join(f'{x},{y}' for x, y in c) + 'Z')
    return ' '.join(out)

def trace(png, **over):
    kw = dict(colormode='color', hierarchical='stacked', mode='spline', filter_speckle=4, color_precision=6,
              layer_difference=12, corner_threshold=60, length_threshold=4.0, max_iterations=10, splice_threshold=45, path_precision=2)
    kw.update(over)
    vtracer.convert_image_to_svg_py(png, '/tmp/_t.svg', **kw)
    svg = open('/tmp/_t.svg').read(); paths = []
    for m in re.finditer(r'<path d="([^"]+)" fill="([^"]+)"(?: transform="translate\(([-\d.]+),([-\d.]+)\)")?', svg):
        d, fill, tx, ty = m.groups(); paths.append([d, fill, float(tx or 0), float(ty or 0)])
    return paths

def build(name, base_grid=0, thresh=10, ink_only=False):
    im = cv2.imread(f'trace/layers/{name}.png', cv2.IMREAD_UNCHANGED)
    if im.shape[2] == 3: im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    bgr, alpha = im[..., :3], im[..., 3]
    H, W = alpha.shape; mask = (alpha > 127).astype(np.uint8)
    # the underlay sits just inside the ink so it never haloes outside the outline
    out = dict(sil=sil_path(mask if ink_only else cv2.erode(mask, np.ones((5, 5), np.uint8))))
    if ink_only:
        out.update(silColor=INK, paths=[])
    else:
        # silhouette colour: median of the layer's lighter (non-ink) pixels
        px = bgr[mask > 0]; lum = px.mean(axis=1); body = px[lum > np.percentile(lum, 35)]
        out['silColor'] = '#%02x%02x%02x' % tuple(int(v) for v in np.median(body, axis=0)[::-1])
        src = f'trace/layers/{name}.png'
        if base_grid:
            G = base_grid
            # iterate: the base is fitted to "plain surface" pixels only, so objects never bleed
            # into it (that bleed shows up as halos around everything traced on top)
            plain = mask > 0
            for it in range(3):
                filled = pushpull(bgr, plain)
                small = cv2.resize(filled, (G, G), interpolation=cv2.INTER_AREA)
                # model the renderer exactly: hard grid cells, Gaussian blur with sigma = 0.75 cell
                base = cv2.GaussianBlur(cv2.resize(small, (W, H), interpolation=cv2.INTER_NEAREST), (0, 0), W / G * 0.75, borderType=cv2.BORDER_REPLICATE)
                diff = np.abs(bgr.astype(int) - base.astype(int)).max(axis=2)
                detail = (diff > thresh).astype(np.uint8)
                detail = cv2.morphologyEx(detail, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
                detail = cv2.dilate(detail, np.ones((3, 3), np.uint8)) & mask
                plain = (mask > 0) & ~cv2.dilate(detail, np.ones((9, 9), np.uint8)).astype(bool)
            r = im.copy(); r[..., 3] = detail * 255; src = f'trace/layers/{name}_detail.png'; cv2.imwrite(src, r)
            out['base'] = dict(G=G, W=W, H=H, cells=['#%02x%02x%02x' % tuple(int(v) for v in np.clip(small[y, x], 0, 255)[::-1]) for y in range(G) for x in range(G)])
        out['paths'] = trace(src)
    json.dump(out, open(f'src/assets/{name}.json', 'w'), separators=(',', ':'))
    print(f'{name:8s} paths={len(out["paths"]):5d} base={"yes" if "base" in out else "no ":3s} {len(json.dumps(out))//1024} KB')

if __name__ == '__main__':
    build('room', base_grid=128, thresh=12)
    build('desk')
    build('lamp', base_grid=96, thresh=16)
    build('ball')
    for k in ['head', 'handL', 'handR', 'armL', 'armR', 'torso']:
        build(k)
    for k in ['browL', 'browR', 'eyeL', 'eyeR', 'mouth']:
        build(k, ink_only=True)
