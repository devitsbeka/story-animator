import * as THREE from "three";
import { seaHeight } from "./ocean3d";

// ============================================================================
// YACHT 3D: a 14 m flybridge motor yacht, modelled entirely in code.
// Local frame (metres): +z = bow, +x = starboard, y = 0 at the design waterline.
// ============================================================================

const LOA = 14; // length overall
const Z0 = -LOA / 2, Z1 = LOA / 2;
const N_ST = 44, N_SEC = 14;

// hull lines as functions of t = 0 (transom) … 1 (stem)
const beamAt = (t: number) => {
  const b = 2.15; // half beam
  const bow = t > 0.62 ? Math.pow((t - 0.62) / 0.38, 1.7) : 0;
  const stern = t < 0.06 ? 0.94 + 0.06 * (t / 0.06) : 1;
  return b * stern * (1 - bow * 0.985);
};
const sheerAt = (t: number) => 1.35 + 0.55 * Math.pow(t, 2.2); // deck edge height above waterline
const keelAt = (t: number) => -0.95 + 0.25 * Math.pow(t, 3) + (t > 0.9 ? (t - 0.9) * 6.5 : 0); // rises to the stem
const deadrise = (t: number) => 0.32 + 0.45 * t; // V gets deeper toward the bow (fraction of half-beam)

// one cross-section (starboard half) from keel to sheer
const section = (t: number): THREE.Vector2[] => {
  const hb = beamAt(t), top = sheerAt(t), keel = keelAt(t);
  const chineY = keel + (top - keel) * 0.32;
  const pts: THREE.Vector2[] = [];
  for (let i = 0; i <= N_SEC; i++) {
    const u = i / N_SEC;
    let x: number, y: number;
    if (u < 0.45) { // bottom: keel → chine, V-shaped with slight convexity
      const s = u / 0.45;
      x = hb * 0.92 * s;
      y = keel + (chineY - keel) * (s * (1 - deadrise(t)) + deadrise(t) * s * s);
    } else { // topsides: chine → sheer, flaring out
      const s = (u - 0.45) / 0.55;
      x = hb * (0.92 + 0.08 * Math.sin(s * Math.PI * 0.5)) + 0.04 * Math.sin(s * Math.PI);
      y = chineY + (top - chineY) * s;
    }
    pts.push(new THREE.Vector2(x, y));
  }
  return pts;
};

const hullGeometry = () => {
  const pos: number[] = [], col: number[] = [], idx: number[] = [];
  const white = new THREE.Color(0.92, 0.93, 0.95), navy = new THREE.Color(0.04, 0.07, 0.16), red = new THREE.Color(0.42, 0.06, 0.05);
  const rows = N_SEC + 1;
  for (let side = -1; side <= 1; side += 2) {
    const base = pos.length / 3;
    for (let s = 0; s <= N_ST; s++) {
      const t = s / N_ST;
      const z = Z0 + t * LOA;
      section(t).forEach((p) => {
        pos.push(p.x * side, p.y, z);
        const c = p.y < 0.05 ? red : p.y < 0.38 && p.y > 0.12 ? navy : white;
        col.push(c.r, c.g, c.b);
      });
    }
    for (let s = 0; s < N_ST; s++) for (let i = 0; i < N_SEC; i++) {
      const a = base + s * rows + i, b = a + rows;
      if (side > 0) idx.push(a, b, a + 1, b, b + 1, a + 1); else idx.push(a, a + 1, b, b, a + 1, b + 1);
    }
  }
  // transom
  const tb = pos.length / 3;
  section(0).forEach((p) => { pos.push(p.x, p.y, Z0); col.push(0.9, 0.91, 0.93); pos.push(-p.x, p.y, Z0); col.push(0.9, 0.91, 0.93); });
  for (let i = 0; i < N_SEC; i++) { const a = tb + i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
};

const deckGeometry = () => {
  const shape = new THREE.Shape();
  const pts: [number, number][] = [];
  for (let s = 0; s <= N_ST; s++) { const t = s / N_ST; pts.push([beamAt(t) * 0.995, Z0 + t * LOA]); }
  shape.moveTo(-pts[0][0], pts[0][1]);
  pts.forEach(([x, z]) => shape.lineTo(x, z));
  for (let i = pts.length - 1; i >= 0; i--) shape.lineTo(-pts[i][0], pts[i][1]);
  const g = new THREE.ShapeGeometry(shape, 1);
  // lift to the sheer line (curved deck)
  const p = g.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getY(i);
    const t = (z - Z0) / LOA;
    p.setXYZ(i, x, sheerAt(Math.max(0, Math.min(1, t))) - 0.02 + 0.06 * (1 - Math.abs(x) / 2.2), z);
  }
  g.computeVertexNormals();
  return g;
};

// side profile extruded across the beam, bevelled: cabins, flybridge, arch
const profileBlock = (profile: [number, number][], width: number, bevel = 0.12) => {
  const s = new THREE.Shape();
  s.moveTo(profile[0][0], profile[0][1]);
  profile.slice(1).forEach(([z, y]) => s.lineTo(z, y));
  s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: width, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 5, curveSegments: 8 });
  g.translate(0, 0, -width / 2);
  g.rotateY(-Math.PI / 2); // profile (z,y) → yacht (z along length)
  g.computeVertexNormals();
  return g;
};

export type YachtRig = {
  group: THREE.Group;
  setLights: (on: number) => void;
  hatch: THREE.Object3D;
  anchors: Record<string, THREE.Vector3>; // useful local points (cockpit, helm, hatch, exhaust …)
};

export const buildYacht = (envMap: THREE.Texture | null): YachtRig => {
  const group = new THREE.Group();
  const gel = new THREE.MeshPhysicalMaterial({ side: THREE.DoubleSide, vertexColors: true, roughness: 0.28, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.08, envMap, envMapIntensity: 1.2 });
  const gelW = new THREE.MeshPhysicalMaterial({ color: 0xeceef2, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.1, envMap, envMapIntensity: 1.1 });
  const teak = new THREE.MeshStandardMaterial({ side: THREE.DoubleSide, color: 0x8a5a32, roughness: 0.75, envMap, envMapIntensity: 0.3 });
  const glass = new THREE.MeshPhysicalMaterial({ color: 0x060a12, roughness: 0.04, metalness: 0.4, clearcoat: 1, envMap, envMapIntensity: 2.2, emissive: new THREE.Color(1, 0.68, 0.34), emissiveIntensity: 0 });
  const steel = new THREE.MeshStandardMaterial({ color: 0xc8ccd2, roughness: 0.18, metalness: 1, envMap, envMapIntensity: 1.4 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x1c2027, roughness: 0.5, envMap, envMapIntensity: 0.4 });

  const hull = new THREE.Mesh(hullGeometry(), gel); group.add(hull);
  const deck = new THREE.Mesh(deckGeometry(), teak); group.add(deck);
  // swim platform
  const plat = new THREE.Mesh(new THREE.BoxGeometry(4.0, 0.12, 0.9), teak); plat.position.set(0, 0.45, Z0 - 0.42); group.add(plat);
  // main cabin (side profile in z,y): raked windshield at the front
  const cabinProfile: [number, number][] = [[-3.2, 1.45], [2.4, 1.6], [3.6, 2.15], [1.6, 2.95], [-3.0, 2.95]];
  const cabin = new THREE.Mesh(profileBlock(cabinProfile, 3.3), gelW); group.add(cabin);
  // windows: a continuous dark band + windshield
  const winProfile: [number, number][] = [[-2.7, 2.25], [1.5, 2.3], [2.55, 2.0], [3.0, 2.12], [1.65, 2.72], [-2.6, 2.72]];
  const win = new THREE.Mesh(profileBlock(winProfile, 3.44, 0.02), glass); group.add(win);
  [-1.7, -0.6, 0.5, 1.55].forEach((z) => [-1, 1].forEach((sd) => {
    const mul = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.62, 0.12), gelW); mul.position.set(sd * 1.73, 2.5, z); group.add(mul);
  }));
  // flybridge + hardtop
  const fly = new THREE.Mesh(profileBlock([[-2.6, 2.95], [1.0, 2.95], [0.6, 3.5], [-2.4, 3.5]], 2.9, 0.05), gelW); group.add(fly);
  const flyWin = new THREE.Mesh(profileBlock([[0.55, 3.05], [0.95, 3.05], [0.6, 3.42], [0.3, 3.42]], 2.95, 0.01), glass); group.add(flyWin);
  const top = new THREE.Mesh(profileBlock([[-3.4, 4.35], [0.6, 4.35], [0.9, 4.48], [-3.2, 4.5]], 3.1, 0.04), gelW); group.add(top);
  // hardtop posts
  [[-1.4, -3.0], [1.4, -3.0], [-1.35, 0.3], [1.35, 0.3]].forEach(([x, z]) => {
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.9, 10), steel); p.position.set(x, 3.9, z); group.add(p);
  });
  // radar arch + dome + mast light
  const arch = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.08, 10, 24, Math.PI), gelW); arch.position.set(0, 4.5, -1.6); arch.rotation.y = Math.PI / 2; group.add(arch);
  const radar = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.18, 24), gelW); radar.position.set(0, 5.6, -1.6); group.add(radar);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.8, 8), steel); mast.position.set(0, 5.9, -1.9); group.add(mast);
  // rails along the bow + stanchions
  const railPts: THREE.Vector3[] = [];
  for (let s = 0; s <= 30; s++) { const t = 0.35 + (s / 30) * 0.64; railPts.push(new THREE.Vector3(beamAt(t) * 0.93, sheerAt(t) + 0.62, Z0 + t * LOA)); }
  for (let s = 30; s >= 0; s--) { const t = 0.35 + (s / 30) * 0.64; railPts.push(new THREE.Vector3(-beamAt(t) * 0.93, sheerAt(t) + 0.62, Z0 + t * LOA)); }
  group.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(railPts), 120, 0.025, 8), steel));
  for (let s = 0; s <= 6; s++) {
    const t = 0.38 + (s / 6) * 0.55;
    [-1, 1].forEach((sd) => { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.62, 8), steel); p.position.set(sd * beamAt(t) * 0.93, sheerAt(t) + 0.31, Z0 + t * LOA); group.add(p); });
  }
  // cockpit details: helm seat block, transom door frame
  const seat = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.45, 0.7), dark); seat.position.set(0, 1.6, -5.2); group.add(seat);
  // foredeck hatch (opens on a hinge)
  const hatchPivot = new THREE.Group(); hatchPivot.position.set(0, sheerAt(0.78) + 0.05, Z0 + 0.78 * LOA - 0.35); group.add(hatchPivot);
  const hatchLid = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.06, 0.7), gelW); hatchLid.position.set(0, 0, 0.35); hatchPivot.add(hatchLid);
  // fenders
  [-2.2, 0.8].forEach((z) => [-1, 1].forEach((sd) => { const f = new THREE.Mesh(new THREE.CapsuleGeometry(0.13, 0.45, 6, 12), new THREE.MeshStandardMaterial({ color: 0x1e3a8a, roughness: 0.4, envMap })); f.position.set(sd * (beamAt((z - Z0) / LOA) + 0.1), 0.95, z); group.add(f); }));
  // nav lights
  const navMat = (c: number) => new THREE.MeshStandardMaterial({ color: c, emissive: new THREE.Color(c), emissiveIntensity: 4 });
  const port = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8), navMat(0xff2a1a)); port.position.set(-1.62, 2.3, 2.6); group.add(port);
  const stbd = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8), navMat(0x18ff5a)); stbd.position.set(1.62, 2.3, 2.6); group.add(stbd);
  const mastL = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 8), navMat(0xffffff)); mastL.position.set(0, 6.32, -1.9); group.add(mastL);
  const stern = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), navMat(0xffffff)); stern.position.set(0, 1.5, Z0 - 0.02); group.add(stern);
  const cabinLight = new THREE.PointLight(0xffb866, 0, 9, 2); cabinLight.position.set(0, 2.4, -0.5); group.add(cabinLight);
  const navs = [port, stbd, mastL, stern];
  return {
    group,
    hatch: hatchPivot,
    anchors: {
      cockpit: new THREE.Vector3(0, 1.55, -5.6),
      hatch: new THREE.Vector3(0, sheerAt(0.78), Z0 + 0.78 * LOA),
      exhaust: new THREE.Vector3(1.4, 0.55, Z0 - 0.05),
      bow: new THREE.Vector3(0, sheerAt(1), Z1),
      stern: new THREE.Vector3(0, 1.4, Z0),
    },
    setLights(on: number) {
      glass.emissiveIntensity = 0.32 * on;
      cabinLight.intensity = 6 * on;
      navs.forEach((m) => ((m.material as THREE.MeshStandardMaterial).emissiveIntensity = 4 * on));
    },
  };
};

// Buoyancy as a pure function of time: wave height sampled at hull points and low-passed by
// averaging over the recent past (a heavy hull can't follow every ripple).
export type YachtPose = { y: number; pitch: number; roll: number };
export const yachtPose = (time: number, x: number, z: number, heading: number, seaState: number): YachtPose => {
  const fx = Math.sin(heading), fz = Math.cos(heading);
  const sx = fz, sz = -fx;
  const H = (t: number, f: number, s: number) => seaHeight(t, x + fx * f + sx * s, z + fz * f + sz * s, seaState);
  let y = 0, pitch = 0, roll = 0, wsum = 0;
  for (let k = 0; k < 6; k++) {
    const t = time - k * 0.12, w = Math.exp(-k * 0.45);
    const bow = H(t, 5, 0), stn = H(t, -5, 0), prt = H(t, 0, -2), stb = H(t, 0, 2), mid = H(t, 0, 0);
    y += w * (mid * 2 + bow + stn + prt + stb) / 6;
    pitch += w * Math.atan2(bow - stn, 10) * 0.85;
    roll += w * Math.atan2(prt - stb, 4) * 0.5;
    wsum += w;
  }
  return { y: y / wsum - 0.05, pitch: pitch / wsum, roll: roll / wsum };
};
