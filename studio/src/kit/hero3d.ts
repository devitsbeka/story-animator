import * as THREE from "three";

// ============================================================================
// HERO 3D: a code-built stylised adult, ~6 heads tall (1.80 m), Arcane/Pixar-adult proportions.
// Origin at the feet, +y up, facing +z. Bone hierarchy + analytic 2-bone IK for arms.
// Wardrobe: oversized washed-black hoodie (hood, strings, kangaroo pocket, chest print),
// structured cap, dark denim, white sneakers. Face: eyes with lids + gaze, FACS-style brows/mouth.
// ============================================================================

export type V3 = [number, number, number];
export type Gesture = "relaxed" | "open" | "fist" | "grip" | "point" | "shh" | "wave" | "flat";
export type HeroAU = { innerUp?: number; outerUp?: number; browDown?: number; lidUp?: number; lidTight?: number; smile?: number; frown?: number; jaw?: number; pucker?: number; squeeze?: number };
export const HERO_EXPR: Record<string, HeroAU> = {
  neutral: {},
  worried: { innerUp: 0.8, browDown: 0.2, frown: 0.3 },
  scared: { innerUp: 1, outerUp: 0.7, lidUp: 1, jaw: 0.45, frown: 0.25 },
  surprised: { innerUp: 0.8, outerUp: 1, lidUp: 1, jaw: 0.6 },
  shout: { browDown: 0.9, lidTight: 0.4, jaw: 1, smile: 0.1 },
  determined: { browDown: 0.75, lidTight: 0.4, frown: 0.15 },
  happy: { smile: 1, outerUp: 0.25, lidTight: 0.25 },
  grin: { smile: 1, jaw: 0.5, lidTight: 0.3 },
  hush: { innerUp: 0.4, pucker: 0.9, lidTight: 0.2 },
  sneeze: { squeeze: 1, browDown: 0.6, jaw: 0.55 },
};

export type ArmPose = { target?: V3; pole?: V3; shoulder?: V3; elbow?: number; wrist?: V3; gesture?: Gesture };
export type HeroPose3 = {
  hips?: V3; // rotation (rad) of the pelvis
  hipsY?: number; // pelvis height offset (crouch)
  spine?: V3; chest?: V3; neck?: V3; head?: V3;
  armL?: ArmPose; armR?: ArmPose; // targets in CHARACTER space (metres, origin at the feet)
  legL?: { hip?: V3; knee?: number }; legR?: { hip?: V3; knee?: number };
  expr?: keyof typeof HERO_EXPR | HeroAU;
  blink?: number; look?: [number, number]; breathe?: number;
};

const D = THREE.MathUtils.degToRad;

// tapered capsule along -y from the origin (a limb hanging from its joint)
const limb = (r1: number, r2: number, len: number, seg = 18) => {
  const pts: THREE.Vector2[] = [];
  for (let i = 0; i <= 6; i++) { const a = (i / 6) * Math.PI / 2; pts.push(new THREE.Vector2(Math.sin(a) * r1, Math.cos(a) * r1)); }
  for (let i = 0; i <= 6; i++) { const a = Math.PI / 2 + (i / 6) * Math.PI / 2; pts.push(new THREE.Vector2(Math.sin(a) * r2, -len + Math.cos(a) * r2)); }
  const g = new THREE.LatheGeometry(pts.reverse(), seg);
  return g;
};
// lathe body from a radius profile [y, r][] (bottom → top), squashed in z
const lathe = (prof: [number, number][], zScale: number, seg = 28) => {
  const g = new THREE.LatheGeometry(prof.map(([y, r]) => new THREE.Vector2(r, y)), seg);
  g.scale(1, 1, zScale);
  return g;
};
const mesh = (g: THREE.BufferGeometry, m: THREE.Material, p: V3 = [0, 0, 0], r: V3 = [0, 0, 0], s: V3 = [1, 1, 1]) => {
  const o = new THREE.Mesh(g, m); o.position.set(...p); o.rotation.set(...r); o.scale.set(...s); o.castShadow = true; return o;
};
const node = (p: V3 = [0, 0, 0], parent?: THREE.Object3D) => { const o = new THREE.Group(); o.position.set(...p); parent?.add(o); return o; };

const printTexture = (text: string) => {
  const c = document.createElement("canvas"); c.width = 512; c.height = 128;
  const x = c.getContext("2d")!;
  x.clearRect(0, 0, 512, 128);
  x.fillStyle = "#f1eee8"; x.font = "700 64px Helvetica, Arial, sans-serif"; x.textAlign = "center"; x.textBaseline = "middle";
  // the wordmark: tight, heavy, slightly condensed
  x.save(); x.scale(0.86, 1); x.fillText(text, 256 / 0.86, 66); x.restore();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
};

type Finger = { j: THREE.Group[] };
type HandRig = { root: THREE.Group; fingers: Finger[]; thumb: THREE.Group[] };

export type HeroRig = {
  group: THREE.Group;
  setPose: (p: HeroPose3) => void;
  height: number;
  joints: Record<string, THREE.Object3D>;
};

export const buildHero3D = (envMap: THREE.Texture | null): HeroRig => {
  // ---------- materials ----------
  const skin = new THREE.MeshPhysicalMaterial({ color: 0xe9b896, roughness: 0.55, sheen: 0.4, sheenColor: new THREE.Color(0xffc8a8), sheenRoughness: 0.6, envMap, envMapIntensity: 0.35 });
  const hoodie = new THREE.MeshPhysicalMaterial({ color: 0x1c1b20, roughness: 0.92, sheen: 1, sheenColor: new THREE.Color(0x4a4a58), sheenRoughness: 0.5, envMap, envMapIntensity: 0.25 });
  const rib = new THREE.MeshPhysicalMaterial({ color: 0x161519, roughness: 0.95, sheen: 0.8, sheenColor: new THREE.Color(0x3a3a46), envMap, envMapIntensity: 0.2 });
  const denim = new THREE.MeshPhysicalMaterial({ color: 0x1f2a3d, roughness: 0.85, sheen: 0.5, sheenColor: new THREE.Color(0x45608a), envMap, envMapIntensity: 0.25 });
  const shoe = new THREE.MeshPhysicalMaterial({ color: 0xeeeeea, roughness: 0.6, clearcoat: 0.3, envMap, envMapIntensity: 0.5 });
  const sole = new THREE.MeshStandardMaterial({ color: 0xd8d4cc, roughness: 0.7 });
  const cap = new THREE.MeshPhysicalMaterial({ color: 0x141317, roughness: 0.8, sheen: 0.8, sheenColor: new THREE.Color(0x3c3c48), envMap, envMapIntensity: 0.25 });
  const white = new THREE.MeshPhysicalMaterial({ color: 0xf4f1ec, roughness: 0.25, clearcoat: 0.5, envMap, envMapIntensity: 0.6 });
  const iris = new THREE.MeshPhysicalMaterial({ color: 0x3a2516, roughness: 0.2, clearcoat: 1, envMap, envMapIntensity: 1 });
  const pupil = new THREE.MeshStandardMaterial({ color: 0x050505, roughness: 0.1 });
  const brow = new THREE.MeshStandardMaterial({ color: 0x2a1a12, roughness: 0.9 });
  const lip = new THREE.MeshStandardMaterial({ color: 0xa8584a, roughness: 0.55 });
  const mouthIn = new THREE.MeshStandardMaterial({ color: 0x3a0f0c, roughness: 0.8 });
  const teeth = new THREE.MeshStandardMaterial({ color: 0xf2eee6, roughness: 0.4 });
  const cord = new THREE.MeshStandardMaterial({ color: 0xe8e4dc, roughness: 0.7 });
  const metal = new THREE.MeshStandardMaterial({ color: 0xc9ccd2, roughness: 0.2, metalness: 1, envMap });

  const group = new THREE.Group();
  const joints: Record<string, THREE.Object3D> = {};

  // ---------- skeleton ----------
  const hips = node([0, 0.96, 0], group); joints.hips = hips;
  const spine = node([0, 0.08, 0], hips); joints.spine = spine;
  const chest = node([0, 0.2, 0], spine); joints.chest = chest;
  const neck = node([0, 0.24, 0.0], chest); joints.neck = neck;
  const head = node([0, 0.09, 0.01], neck); joints.head = head;

  // ---------- torso: oversized hoodie ----------
  hips.add(mesh(lathe([[-0.1, 0.0], [-0.09, 0.15], [-0.02, 0.17], [0.08, 0.175]], 0.72), denim, [0, 0, 0]));
  chest.add(mesh(lathe([[-0.34, 0.0], [-0.33, 0.205], [-0.26, 0.215], [-0.05, 0.22], [0.12, 0.235], [0.2, 0.225], [0.25, 0.17], [0.285, 0.07], [0.29, 0.0]], 0.66), hoodie));
  chest.add(mesh(lathe([[-0.36, 0.0], [-0.36, 0.2], [-0.315, 0.208], [-0.31, 0.0]], 0.68), rib)); // waistband
  // kangaroo pocket
  const pocket = mesh(new THREE.BoxGeometry(0.26, 0.13, 0.03), hoodie, [0, -0.22, 0.148], [D(-6), 0, 0]); chest.add(pocket);
  // print
  const print = new THREE.Mesh(new THREE.PlaneGeometry(0.22, 0.055), new THREE.MeshStandardMaterial({ map: printTexture("PALENCIAGA"), transparent: true, roughness: 0.8 }));
  print.position.set(0, 0.06, 0.154); print.rotation.x = D(-4); chest.add(print);
  // hood bunched behind the neck + front opening
  chest.add(mesh(new THREE.TorusGeometry(0.11, 0.055, 12, 24, Math.PI * 1.4), hoodie, [0, 0.26, -0.04], [D(-78), 0, D(-126)]));
  chest.add(mesh(new THREE.SphereGeometry(0.12, 20, 14), hoodie, [0, 0.3, -0.1], [0, 0, 0], [1, 0.7, 0.75]));
  // drawstrings with metal aglets
  [-0.045, 0.045].forEach((x) => {
    const curve = new THREE.CatmullRomCurve3([new THREE.Vector3(x, 0.235, 0.12), new THREE.Vector3(x * 1.2, 0.15, 0.158), new THREE.Vector3(x * 1.1, 0.06, 0.16)]);
    chest.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 16, 0.005, 6), cord));
    chest.add(mesh(new THREE.CylinderGeometry(0.0055, 0.0055, 0.022, 8), metal, [x * 1.1, 0.045, 0.16]));
  });
  // neck
  neck.add(mesh(limb(0.05, 0.055, 0.1), skin, [0, 0.1, 0]));

  // ---------- head (≈0.28 m tall incl. jaw; 1/6.4 of height) ----------
  // one sculpted head: sphere → narrower, longer lower face with a soft chin and cheekbones
  const hg = new THREE.SphereGeometry(0.1, 56, 44);
  const hp_ = hg.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < hp_.count; i++) {
    let x = hp_.getX(i), y = hp_.getY(i), z = hp_.getZ(i);
    const low = Math.max(0, -y / 0.1); // 0 at the equator → 1 at the chin
    x *= 0.95 * (1 - 0.22 * low * low);
    z *= 0.92 * (1 - 0.06 * low) + (z > 0 ? 0.08 * low * (1 - low) : 0);
    y = y * 1.08 - 0.03 * low * low;
    const cheek = Math.exp(-Math.pow((y + 0.012) / 0.02, 2)) * Math.max(0, z) * 0.12;
    x += Math.sign(x) * cheek;
    hp_.setXYZ(i, x, y, z);
  }
  hg.computeVertexNormals();
  const skull = mesh(hg, skin, [0, 0.1, 0]); head.add(skull);
  head.scale.setScalar(1.1); // stylised: slightly large head for appeal
  const jawM = new THREE.Group(); head.add(jawM); // jaw motion is carried by the lips/mouth
  head.add(mesh(new THREE.SphereGeometry(0.014, 14, 10), skin, [0, 0.088, 0.092], [0, 0, 0], [0.85, 1.2, 1.05])); // nose
  [-1, 1].forEach((s) => head.add(mesh(new THREE.SphereGeometry(0.022, 14, 10), skin, [s * 0.093, 0.095, -0.005], [0, 0, 0], [0.45, 1, 0.75]))); // ears
  // eyes: ball + iris + pupil + catchlight, lids as partial spheres
  const eyes: { ball: THREE.Group; up: THREE.Mesh; low: THREE.Mesh }[] = [];
  [-1, 1].forEach((s) => {
    const socket = node([s * 0.036, 0.117, 0.079], head);
    const ball = node([0, 0, 0], socket);
    ball.add(mesh(new THREE.SphereGeometry(0.0195, 24, 18), white));
    ball.add(mesh(new THREE.SphereGeometry(0.0118, 18, 14), iris, [0, 0, 0.0158], [0, 0, 0], [1, 1, 0.32]));
    ball.add(mesh(new THREE.SphereGeometry(0.0062, 12, 10), pupil, [0, 0, 0.0186], [0, 0, 0], [1, 1, 0.3]));
    ball.add(mesh(new THREE.SphereGeometry(0.0022, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffffff }), [-0.0045, 0.0045, 0.0203]));
    const lidG = new THREE.SphereGeometry(0.0212, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2);
    const up = mesh(lidG, skin); socket.add(up);
    const low = mesh(lidG, skin, [0, 0, 0], [Math.PI, 0, 0]); socket.add(low);
    eyes.push({ ball, up, low });
  });
  // brows and mouth are rebuilt from curves each pose
  const browMeshes: THREE.Mesh[] = [new THREE.Mesh(new THREE.BufferGeometry(), brow), new THREE.Mesh(new THREE.BufferGeometry(), brow)];
  browMeshes.forEach((b) => head.add(b));
  const upperLip = new THREE.Mesh(new THREE.BufferGeometry(), lip), lowerLip = new THREE.Mesh(new THREE.BufferGeometry(), lip);
  head.add(upperLip, lowerLip);
  const mouthHole = mesh(new THREE.SphereGeometry(1, 20, 12), mouthIn); head.add(mouthHole);
  const teethM = mesh(new THREE.BoxGeometry(0.03, 0.007, 0.01), teeth); head.add(teethM);

  // ---------- cap: structured crown + curved bill ----------
  const capG = node([0, 0.158, -0.006], head);
  capG.add(mesh(new THREE.SphereGeometry(0.104, 40, 20, 0, Math.PI * 2, 0, Math.PI * 0.5), cap, [0, 0.0, 0], [D(-6), 0, 0], [0.98, 0.78, 0.98]));
  capG.add(mesh(new THREE.CylinderGeometry(0.102, 0.1, 0.022, 40, 1, true), cap, [0, -0.01, 0.0], [D(-6), 0, 0], [0.98, 1, 0.98]));
  const billShape = new THREE.Shape();
  for (let i = 0; i <= 24; i++) { const a = Math.PI * (0.08 + 0.84 * (i / 24)); const r = 0.105; const x = Math.cos(a) * r, y = Math.sin(a) * r; if (i === 0) billShape.moveTo(x, y); else billShape.lineTo(x, y); }
  for (let i = 24; i >= 0; i--) { const a = Math.PI * (0.08 + 0.84 * (i / 24)); const r = 0.105 + 0.09 * Math.sin(Math.PI * (i / 24)); billShape.lineTo(Math.cos(a) * r, Math.sin(a) * r); }
  const billG = new THREE.ExtrudeGeometry(billShape, { depth: 0.006, bevelEnabled: true, bevelThickness: 0.002, bevelSize: 0.002, bevelSegments: 2 });
  billG.rotateX(D(90)); billG.rotateY(D(180)); // lie flat, point forward (+z)
  const bill = mesh(billG, cap, [0, -0.018, 0.004], [D(8), 0, 0]); capG.add(bill);
  capG.add(mesh(new THREE.SphereGeometry(0.008, 10, 8), cap, [0, 0.081, -0.008]));
  const emb = new THREE.Mesh(new THREE.PlaneGeometry(0.05, 0.02), new THREE.MeshStandardMaterial({ map: printTexture("≈"), transparent: true }));
  void emb;

  // ---------- arms ----------
  const UP = 0.3, FORE = 0.27;
  const arm = (side: -1 | 1) => {
    const sh = node([side * 0.215, 0.205, -0.01], chest);
    sh.add(mesh(new THREE.SphereGeometry(0.075, 18, 14), hoodie, [0, -0.01, 0], [0, 0, 0], [1, 1, 0.95])); // dropped shoulder
    sh.add(mesh(limb(0.07, 0.062, UP), hoodie));
    const el = node([0, -UP, 0], sh);
    el.add(mesh(limb(0.062, 0.05, FORE - 0.05), hoodie));
    el.add(mesh(limb(0.047, 0.045, 0.05), rib, [0, -(FORE - 0.06), 0])); // ribbed cuff
    const wr = node([0, -FORE, 0], el);
    const hand = buildHand(side, skin);
    wr.add(hand.root);
    return { sh, el, wr, hand };
  };
  const armL = arm(-1), armR = arm(1);
  joints.shoulderL = armL.sh; joints.shoulderR = armR.sh; joints.wristL = armL.wr; joints.wristR = armR.wr;

  // ---------- legs ----------
  const leg = (side: -1 | 1) => {
    const hp = node([side * 0.095, -0.04, 0], hips);
    hp.add(mesh(limb(0.095, 0.07, 0.45), denim));
    const kn = node([0, -0.45, 0], hp);
    kn.add(mesh(limb(0.07, 0.058, 0.42), denim));
    const an = node([0, -0.43, 0], kn);
    const shoeG = new THREE.CapsuleGeometry(0.048, 0.17, 6, 14); shoeG.rotateX(D(90));
    an.add(mesh(shoeG, shoe, [0, -0.025, 0.05], [0, 0, 0], [1, 0.75, 1]));
    an.add(mesh(new THREE.BoxGeometry(0.1, 0.02, 0.28), sole, [0, -0.06, 0.05]));
    return { hp, kn, an };
  };
  const legL = leg(-1), legR = leg(1);

  // ---------- face rebuild helpers ----------
  const tubeOn = (m: THREE.Mesh, pts: V3[], r: number) => {
    m.geometry.dispose();
    m.geometry = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(...p))), 16, r, 6, false);
  };

  // ---------- 2-bone IK in character space ----------
  const solveArm = (a: typeof armL, side: -1 | 1, p: ArmPose) => {
    a.sh.rotation.set(0, 0, 0); a.el.rotation.set(0, 0, 0); a.wr.rotation.set(0, 0, 0);
    if (!p.target) {
      a.sh.rotation.set(...(p.shoulder ?? [0.05, 0, side * 0.12]));
      a.el.rotation.x = -(p.elbow ?? 0.25);
      a.wr.rotation.set(...(p.wrist ?? [0, 0, 0]));
      return;
    }
    group.updateMatrixWorld(true);
    const toWorld = (v: V3) => new THREE.Vector3(...v).applyMatrix4(group.matrixWorld);
    const S = new THREE.Vector3().setFromMatrixPosition(a.sh.matrixWorld);
    const T = toWorld(p.target);
    const pole = toWorld(p.pole ?? [side * 0.6, 0.6, -0.4]);
    const dir = T.clone().sub(S); const dist = Math.min(dir.length(), UP + FORE - 1e-3); dir.normalize();
    const cosA = (UP * UP + dist * dist - FORE * FORE) / (2 * UP * dist);
    const along = dir.clone().multiplyScalar(UP * cosA);
    const pv = pole.clone().sub(S); pv.sub(dir.clone().multiplyScalar(pv.dot(dir))).normalize();
    const E = S.clone().add(along).add(pv.multiplyScalar(UP * Math.sqrt(Math.max(0, 1 - cosA * cosA))));
    const T2 = S.clone().add(dir.clone().multiplyScalar(dist));
    // aim bone (-y axis) from joint to child in its parent's space
    const aim = (bone: THREE.Object3D, from: THREE.Vector3, to: THREE.Vector3) => {
      const parentQ = new THREE.Quaternion(); bone.parent!.getWorldQuaternion(parentQ);
      const d = to.clone().sub(from).normalize().applyQuaternion(parentQ.invert());
      bone.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), d);
      bone.updateMatrixWorld(true);
    };
    aim(a.sh, S, E);
    aim(a.el, E, T2);
    if (p.wrist) a.wr.rotation.set(...p.wrist);
  };

  let lastKey = "";
  const setPose = (p: HeroPose3) => {
    const br = p.breathe ?? 0;
    hips.position.y = 0.96 + (p.hipsY ?? 0);
    hips.rotation.set(...(p.hips ?? [0, 0, 0]));
    spine.rotation.set(...(p.spine ?? [0, 0, 0]));
    chest.rotation.set(...(p.chest ?? [0, 0, 0]));
    chest.scale.set(1 + br * 0.012, 1 + br * 0.008, 1 + br * 0.015);
    neck.rotation.set(...(p.neck ?? [0, 0, 0]));
    head.rotation.set(...(p.head ?? [0, 0, 0]));
    legL.hp.rotation.set(...(p.legL?.hip ?? [0, 0, 0.03])); legL.kn.rotation.x = p.legL?.knee ?? 0.02; legL.an.rotation.x = -(legL.hp.rotation.x + legL.kn.rotation.x);
    legR.hp.rotation.set(...(p.legR?.hip ?? [0, 0, -0.03])); legR.kn.rotation.x = p.legR?.knee ?? 0.02; legR.an.rotation.x = -(legR.hp.rotation.x + legR.kn.rotation.x);
    solveArm(armL, -1, p.armL ?? {});
    solveArm(armR, 1, p.armR ?? {});
    setGesture(armL.hand, p.armL?.gesture ?? "relaxed");
    setGesture(armR.hand, p.armR?.gesture ?? "relaxed");
    // ---- face ----
    const au: HeroAU = typeof p.expr === "string" ? HERO_EXPR[p.expr] ?? {} : p.expr ?? {};
    const v = (k: keyof HeroAU) => au[k] ?? 0;
    const lk = p.look ?? [0, 0];
    const blink = Math.max(p.blink ?? 0, v("squeeze"));
    const open = Math.max(0, 1 - blink - v("lidTight") * 0.35);
    eyes.forEach((e) => {
      e.ball.rotation.set(-lk[1] * 0.35, lk[0] * 0.45, 0);
      // upper lid: rotate down from "open" (above the iris) to closed
      e.up.rotation.x = D(-70 - 30 * v("lidUp")) + D(110) * (1 - open);
      e.low.rotation.x = Math.PI + D(62) - D(14) * v("smile") - D(20) * v("squeeze");
    });
    const key = JSON.stringify([au, Math.round(blink * 20)]);
    if (key !== lastKey) {
      lastKey = key;
      [-1, 1].forEach((s, i) => {
        const inn: V3 = [s * 0.014, 0.146 + 0.016 * v("innerUp") - 0.012 * v("browDown"), 0.093];
        const mid: V3 = [s * 0.037, 0.153 + 0.009 * v("innerUp") + 0.012 * v("outerUp") - 0.008 * v("browDown"), 0.092];
        const out: V3 = [s * 0.06, 0.146 + 0.016 * v("outerUp") - 0.003 * v("browDown") - 0.004 * v("innerUp"), 0.079];
        tubeOn(browMeshes[i], [inn, mid, out], 0.0042);
      });
      const jaw = v("jaw"), sm = v("smile") - v("frown"), pk = v("pucker");
      const cw = 0.024 + 0.008 * v("smile") - 0.01 * pk + 0.002 * jaw;
      const cy = 0.047 + 0.008 * sm;
      const o = 0.004 + jaw * 0.026;
      tubeOn(upperLip, [[-cw, cy, 0.083], [-cw * 0.4, 0.051 + 0.002 * sm, 0.094], [0, 0.0505, 0.096], [cw * 0.4, 0.051 + 0.002 * sm, 0.094], [cw, cy, 0.083]], 0.0034);
      tubeOn(lowerLip, [[-cw, cy, 0.083], [-cw * 0.4, 0.049 - o * 0.9, 0.092], [0, 0.0485 - o, 0.094], [cw * 0.4, 0.049 - o * 0.9, 0.092], [cw, cy, 0.083]], 0.0039);
      mouthHole.position.set(0, 0.05 - o * 0.5, 0.085); mouthHole.scale.set(cw * 0.85, Math.max(0.001, o * 0.55), 0.008);
      teethM.visible = jaw > 0.25; teethM.position.set(0, 0.047, 0.088); teethM.scale.set(cw / 0.03 * 0.9, 1, 1);
      jawM.position.y = 0.035 - jaw * 0.012;
    }
  };
  setPose({});
  return { group, setPose, height: 1.8, joints };
};

// ---------- hands ----------
const CURLS: Record<Gesture, [number, number, number, number, number]> = {
  // [thumb, index, middle, ring, pinky] curl 0..1
  relaxed: [0.25, 0.25, 0.32, 0.38, 0.45],
  open: [0, 0, 0, 0, 0],
  wave: [0, 0, 0.02, 0.04, 0.06],
  flat: [0.15, 0, 0, 0, 0],
  fist: [0.85, 1, 1, 1, 1],
  grip: [0.6, 0.75, 0.8, 0.85, 0.9],
  point: [0.75, 0, 1, 1, 1],
  shh: [0.75, 0, 1, 1, 1],
};
const SPREAD: Record<Gesture, number> = { relaxed: 0.3, open: 1, wave: 1.2, flat: 0.1, fist: 0, grip: 0.2, point: 0.2, shh: 0, };

const buildHand = (side: -1 | 1, skin: THREE.Material): HandRig => {
  const root = new THREE.Group();
  // palm hangs along -y; palm faces -x*side (toward the body when the arm hangs)
  const palm = new THREE.Mesh(new THREE.CapsuleGeometry(0.028, 0.045, 6, 12), skin);
  palm.scale.set(1.25, 1, 0.55); palm.position.set(0, -0.045, 0); palm.castShadow = true; root.add(palm);
  const fingers: Finger[] = [];
  const LEN = [0.088, 0.096, 0.09, 0.072];
  [-0.018, -0.006, 0.006, 0.018].forEach((x, i) => {
    const j: THREE.Group[] = [];
    let parent: THREE.Object3D = root;
    let y = -0.083;
    [0.45, 0.32, 0.23].forEach((f, k) => {
      const g = new THREE.Group(); g.position.set(k === 0 ? x * 1.15 : 0, k === 0 ? y : -LEN[i] * [0.45, 0.32, 0.23][k - 1], 0); parent.add(g);
      const seg = new THREE.Mesh(new THREE.CapsuleGeometry(0.0078 - k * 0.0006, LEN[i] * f - 0.008, 4, 8), skin);
      seg.position.y = -(LEN[i] * f) / 2; seg.castShadow = true; g.add(seg);
      j.push(g); parent = g; y = 0;
    });
    fingers.push({ j });
  });
  const thumb: THREE.Group[] = [];
  const tb = new THREE.Group(); tb.position.set(0.026, -0.02, 0.012); root.add(tb);
  const t1 = new THREE.Mesh(new THREE.CapsuleGeometry(0.0095, 0.03, 4, 8), skin); t1.position.y = -0.022; tb.add(t1);
  const tj = new THREE.Group(); tj.position.y = -0.045; tb.add(tj);
  const t2 = new THREE.Mesh(new THREE.CapsuleGeometry(0.0085, 0.022, 4, 8), skin); t2.position.y = -0.016; tj.add(t2);
  thumb.push(tb, tj);
  root.scale.set(side, 1, 1); // mirror for the left hand
  return { root, fingers, thumb };
};
const setGesture = (h: HandRig, g: Gesture) => {
  const c = CURLS[g], sp = SPREAD[g];
  h.fingers.forEach((f, i) => {
    const curl = c[i + 1];
    f.j[0].rotation.set(D(80) * curl, 0, D((i - 1.5) * 5 * sp));
    f.j[1].rotation.x = D(100) * curl;
    f.j[2].rotation.x = D(65) * curl;
  });
  h.thumb[0].rotation.set(D(20 + 40 * c[0]), D(-30 * c[0]), D(-35 + 25 * c[0]));
  h.thumb[1].rotation.x = D(50) * c[0];
};
