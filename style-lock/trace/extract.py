import cv2, numpy as np, os
os.makedirs('trace/layers', exist_ok=True)
img = cv2.imread('ref/reference.jpg'); H, W = img.shape[:2]
lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
ink = (lab[...,0] < 70).astype(np.uint8)
ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))
n, lbl, stats, _ = cv2.connectedComponentsWithStats(1-ink, connectivity=4)
def comp(x,y):
    c = lbl[y,x]; assert c != 0, (x,y); return (lbl==c).astype(np.uint8)
def near_free(x,y):
    for r in range(0,12):
        for dx in range(-r,r+1):
            for dy in range(-r,r+1):
                if lbl[y+dy,x+dx]!=0: return x+dx,y+dy
def C(x,y): return comp(*near_free(x,y))
def with_outline(m, w=9):
    d = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(w,w)))
    return ((m | (d & ink))>0).astype(np.uint8)

head = C(500,240); handL = C(375,440); handR = C(615,395)
redA = C(330,560)   # left arm + torso (merged)
armR = C(700,560); sliver = C(770,580)
# split left arm from torso with a cut line along the inner edge of the forearm
cut = np.zeros_like(redA)
cv2.line(cut, (425,470), (452,640), 1, 3)
n2, l2 = cv2.connectedComponents((redA & (1-cut)).astype(np.uint8), connectivity=4)
a = l2[560,330]; t = l2[560,520]
armL = (l2==a).astype(np.uint8); torso = (l2==t).astype(np.uint8) | sliver
torso = torso | (cut & redA)
# face features inside head: ink components fully inside the head's bbox
hx,hy,hw,hh = cv2.boundingRect(head)
headFill = cv2.morphologyEx(head, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(61,61)))
inner = ink & cv2.erode(headFill, np.ones((25,25),np.uint8))
nf, lf, sf, cf = cv2.connectedComponentsWithStats(inner)
feat = [(i, sf[i,:5], cf[i]) for i in range(1,nf) if sf[i,4] > 4]
for i,s,c in feat: print('feature', i, s, c.round())
parts = dict(head=headFill, handL=handL, handR=handR, armL=armL, armR=armR, torso=torso)
parts = {k: with_outline(v) for k,v in parts.items()}
# exclusive ownership so overlapping outlines aren't doubled: hands > arms > head > torso
order = ['handL','handR','armL','armR','head','torso']
taken = np.zeros((H,W),np.uint8)
for k in order:
    parts[k] = parts[k] & (1-taken); taken |= parts[k]
# gaps between parts (collar, neck, slivers next to cuffs) belong to the torso
closed = cv2.morphologyEx(taken, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(17,17)))
ff = closed.copy()*255; cv2.floodFill(ff, None, (0,0), 128)
closed = ((ff==255)|(closed>0)).astype(np.uint8)
gap = closed & (1-taken)
gap[:440,:] = 0  # never steal from above the chin
parts['torso'] |= gap; taken |= gap
# any remaining sweater-red pixels around the neckline belong to the torso too
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
red = (((hsv[...,0] < 12) | (hsv[...,0] > 170)) & (hsv[...,1] > 110) & (hsv[...,2] > 60)).astype(np.uint8)
box = np.zeros_like(red); box[440:530, 400:660] = 1
extra = cv2.dilate(red & box, np.ones((5,5),np.uint8)) & (1-taken)
parts['torso'] |= extra; taken |= extra
char = taken
np.save('trace/char.npy', char)
for k,m in parts.items():
    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA); rgba[...,3] = m*255
    x,y,w,h = cv2.boundingRect(m); print(k, (x,y,w,h))
    cv2.imwrite(f'trace/layers/{k}.png', rgba)
# face features as their own layer (for the rig); then clean them off the head layer
face = np.zeros((H,W),np.uint8)
for i,s,c in feat: face |= (lf==i).astype(np.uint8)
face = cv2.dilate(face, np.ones((3,3),np.uint8))
rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA); rgba[...,3] = face*255
cv2.imwrite('trace/layers/face.png', rgba)
headimg = cv2.inpaint(img, cv2.dilate(face,np.ones((5,5),np.uint8))*255, 7, cv2.INPAINT_TELEA)
rgba = cv2.cvtColor(headimg, cv2.COLOR_BGR2BGRA); rgba[...,3] = parts['head']*255
cv2.imwrite('trace/layers/head.png', rgba)
# background: remove the character, refill with a smooth push-pull fill (wall and desk separately)
def pushpull(im, known):
    im = im.astype(np.float32); k = known.astype(np.float32)
    levels = []
    a, w = im*k[...,None], k
    while min(w.shape) > 4:
        levels.append((a, w))
        a = cv2.pyrDown(a); w = cv2.pyrDown(w)
    est = a/np.maximum(w[...,None],1e-6)
    for a, w in reversed(levels):
        up = cv2.resize(est, (w.shape[1], w.shape[0]), interpolation=cv2.INTER_LINEAR)
        cur = a/np.maximum(w[...,None],1e-6)
        ww = np.clip(w*4,0,1)[...,None]
        est = cur*ww + up*(1-ww)
    return est
hole = cv2.dilate(char, np.ones((9,9),np.uint8))
DESK_Y = 622  # desk top edge behind the character
rows = np.arange(H)[:,None].repeat(W,1)
bg = img.astype(np.float32).copy()
for region in [(rows < DESK_Y), (rows >= DESK_Y)]:
    known = (1-hole).astype(bool) & region
    fill = pushpull(img, known)
    sel = hole.astype(bool) & region
    bg[sel] = fill[sel]
bg = np.clip(bg,0,255).astype(np.uint8)
# complete the chair back hidden behind the right arm: mirror its visible right edge
FILL, RIM, INKC = (34,45,83), (105,141,205), (0,7,25)  # BGR, sampled from the visible chair
pts = np.array([[704,384],[770,377],[770,640],[690,640],[686,425]], np.int32)
cv2.fillPoly(bg, [pts], FILL)
edge = np.array([[694,640],[690,428],[697,398],[712,388],[770,382]], np.int32)
cv2.polylines(bg, [edge + [7,6]], False, RIM, 12, cv2.LINE_AA)
cv2.polylines(bg, [edge], False, INKC, 6, cv2.LINE_AA)
# keep what was visible in the reference exactly as it was
vis_mask = (1-hole).astype(bool)
bg[vis_mask] = img[vis_mask]
cv2.imwrite('trace/layers/bg.png', bg)
np.save('trace/hole.npy', hole)
vis = img.copy(); vis[char>0] = (vis[char>0]*0.3).astype(np.uint8)
cv2.imwrite('out/char_mask.png', np.hstack([vis, bg]))

# ---- depth layers: room (far), desk + desk props (near), lamp (near) ----
desk_poly = np.array([[0,336],[150,336],[238,392],[246,598],[300,612],[780,612],[796,578],[884,582],[902,504],[1024,504],[1024,1024],[0,1024]], np.int32)
lamp_poly = np.array([[0,150],[60,120],[96,40],[150,40],[275,165],[262,212],[200,252],[130,250],[110,200],[0,262]], np.int32)
def poly_mask(p):
    m = np.zeros((H,W),np.uint8); cv2.fillPoly(m,[p],1); return m
desk_m = poly_mask(desk_poly); lamp_m = poly_mask(lamp_poly)
# within the desk polygon keep only real objects: pixels that differ from the wall behind them
# (estimated by filling the polygon from the wall around it), plus everything below the desk edge
wall_est = pushpull(bg, ~(cv2.dilate(desk_m, np.ones((15,15),np.uint8)).astype(bool)) & ~hole.astype(bool))
obj = (np.abs(bg.astype(np.float32) - wall_est).max(axis=2) > 22).astype(np.uint8)
obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(11,11)))
ffo = obj.copy()*255; cv2.floodFill(ffo, None, (0,0), 128); obj = ((ffo==255)|(obj>0)).astype(np.uint8)
obj[612:,:] = 1
desk_m = desk_m & obj
# the lamp: a tight polygon traced along its ink outline (shade, knob, joint, arm)
LAMP = np.array([[103,52],[110,41],[123,42],[135,54],[140,63],[160,59],[175,67],[215,97],[258,139],[279,162],[273,176],
                 [255,196],[220,221],[180,241],[145,252],[125,251],[117,238],[107,210],[100,167],[80,167],[0,226],[0,184],
                 [71,139],[79,127],[96,126],[96,100],[102,84],[102,60]], np.int32)
lamp_m = poly_mask(LAMP)
# snap mask borders to ink lines where possible: grow into adjacent ink by a few px
grow = lambda m: (m | (cv2.dilate(m, np.ones((7,7),np.uint8)) & ink)).astype(np.uint8)
desk_m = grow(desk_m) & (1-char); lamp_m = grow(lamp_m)
def save_rgba(name, im, m):
    r = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA); r[...,3] = m*255; cv2.imwrite(f'trace/layers/{name}.png', r)
save_rgba('desk', bg, desk_m)
save_rgba('lamp', bg, lamp_m)
# room: refill what the desk and lamp cover with the smooth wall/shelf fill
room_hole = cv2.dilate(desk_m | lamp_m, np.ones((5,5),np.uint8))
room = bg.astype(np.float32).copy()
fill = pushpull(bg, ~room_hole.astype(bool))
room[room_hole>0] = fill[room_hole>0]
room = np.clip(room,0,255).astype(np.uint8)
cv2.imwrite('trace/layers/room.png', room)
cv2.imwrite('out/layers_check.png', np.hstack([room, cv2.cvtColor(cv2.imread('trace/layers/desk.png',cv2.IMREAD_UNCHANGED)[...,3],cv2.COLOR_GRAY2BGR)]))

# ---- physics prop: the crumpled paper ball on the desk, lifted out of the desk layer ----
ball = C(268, 790) if lbl[790,268] else None
bx0,by0,bx1,by1 = 214,756,332,850
ballbox = np.zeros((H,W),np.uint8); ballbox[by0:by1,bx0:bx1] = 1
# ball = non-wood pixels in the box (paper is light & low-saturation) plus its outline
# the ball is whatever its outer ink contour encloses
lab_bg = cv2.cvtColor(bg, cv2.COLOR_BGR2LAB)
bink = ((lab_bg[...,0] < 95).astype(np.uint8)) & ballbox
bink = cv2.morphologyEx(bink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)))
cnts,_ = cv2.findContours(bink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
paper = np.zeros((H,W),np.uint8); cv2.drawContours(paper, [c for c in cnts if cv2.pointPolygonTest(c, (272.0, 800.0), False) >= 0][:1] or [max(cnts, key=cv2.contourArea)], -1, 1, -1)
ball_m = with_outline(paper, 5) & ballbox
ball_img = bg.copy()
bh_ = cv2.cvtColor(ball_img, cv2.COLOR_BGR2HSV)
woody = (bh_[...,1] > 140) & (bh_[...,2] > 150) & (ball_m > 0)   # desk wood seen between folds
paper_col = np.median(ball_img[(paper > 0) & ~woody], axis=0)
ball_img[woody] = (0.35*ball_img[woody] + 0.65*paper_col).astype(np.uint8)
save_rgba('ball', ball_img, ball_m)
bx,by,bw,bh = cv2.boundingRect(ball_m)
# refill the desk underneath from surrounding desk pixels (with its shadow removed)
desk_rgba = cv2.imread('trace/layers/desk.png', cv2.IMREAD_UNCHANGED)
under = cv2.dilate(ball_m, np.ones((9,9),np.uint8))
# also lift its painted cast shadow (down-left of the ball); the engine draws a live one
shadow_zone = np.zeros_like(ball_m); cv2.ellipse(shadow_zone, (int(cv2.boundingRect(ball_m)[0]+40), int(cv2.boundingRect(ball_m)[1]+cv2.boundingRect(ball_m)[3]-8)), (62,18), 0, 0, 360, 1, -1)
under = (under | shadow_zone).astype(np.uint8)
dfill = pushpull(bg, ~(under.astype(bool)) & (desk_m>0))
d2 = bg.copy(); d2[under>0] = np.clip(dfill[under>0],0,255).astype(np.uint8)
save_rgba('desk', d2, desk_m)

# ---- rig data: pivots, underlays, colours ----
import json
cnts,_ = cv2.findContours(parts['head'], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
(ex,ey),(ew,eh),ea = cv2.fitEllipse(max(cnts,key=cv2.contourArea))
red_sweater = np.concatenate([np.argwhere(m>0) for m in [parts['torso'],parts['armL'],parts['armR']]])[:,::-1]
hull = cv2.convexHull(red_sweater.astype(np.int32))[:,0,:]
col = lambda x,y: '#%02x%02x%02x' % tuple(int(v) for v in img[y,x][::-1])
rig = dict(
  headEllipse=[round(ex,1),round(ey,1),round(ew/2,1),round(eh/2,1),round(ea,1)],
  headColor=col(500,200), redColor=col(520,560), inkColor='#1a0a04',
  torsoHull=hull.tolist(),
  ball=dict(cx=bx+bw/2, cy=by+bh/2, r=max(bw,bh)/2),
  pivots=dict(torso=[520,650], head=[515,468], armL=[330,625], handL=[386,470], armR=[715,632], handR=[628,470]),
)
json.dump(rig, open('src/assets/rig.json','w'), indent=1)
print('rig', rig['headEllipse'], rig['ball'])
