import cv2, numpy as np, sys
img = cv2.imread('ref/reference.jpg')
lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
L = lab[...,0]
ink = (L < 70).astype(np.uint8)
ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3,3),np.uint8))
free = (1-ink)
n, lbl, stats, cent = cv2.connectedComponentsWithStats(free, connectivity=4)
seeds = {
 'head':(500,240),'handL':(360,420),'handR':(615,395),
 'armL':(330,560),'armR':(700,560),'torso':(520,560),'chair':(820,480),
}
out = img.copy()
for k,(x,y) in seeds.items():
    c = lbl[y,x]; a = stats[c,cv2.CC_STAT_AREA]
    print(k, c, a, stats[c,:4])
    m = (lbl==c)
    col = np.random.RandomState(abs(hash(k))%999).randint(60,255,3)
    out[m] = (out[m]*0.4 + col*0.6).astype(np.uint8)
cv2.imwrite('out/seg.png', out)
np.save('trace/lbl.npy', lbl); np.save('trace/ink.npy', ink)
