import * as THREE from "three";
import GEO from "../data/sentinel_geo.json";

// ============================================================================
// ISLAND 3D: North Sentinel from its real OpenStreetMap coastline (km → m), built in code:
// low terrain lifted inside the coast, a pale beach band, dense instanced jungle canopy with
// a few tall emergent trees, a foam reef ring offshore, and firelight points (people never shown).
// Scale can be reduced for shots that need the island closer than it really is.
// ============================================================================

const hash = (n: number) => { const s = Math.sin(n * 127.1) * 43758.5453; return s - Math.floor(s); };

export type IslandRig = { group: THREE.Group; fires: THREE.PointLight[]; fireMeshes: THREE.Mesh[]; setFires: (on: number[], t: number) => void };

export const buildIsland = (envMap: THREE.Texture | null, opts: { scale?: number; seed?: number } = {}): IslandRig => {
  const S = (opts.scale ?? 1) * 1000; // km → m
  const coast = (GEO.coast as number[][]).map(([x, y]) => new THREE.Vector2(x * S, y * S)); // y = +south → world +z
  const group = new THREE.Group();
  // terrain: the coast polygon as a shape, extruded thin, then domed by distance to the edge
  const shape = new THREE.Shape(coast.map((p) => new THREE.Vector2(p.x, -p.y)));
  const terrainG = new THREE.ShapeGeometry(shape, 1);
  terrainG.rotateX(-Math.PI / 2);
  const tp = terrainG.attributes.position as THREE.BufferAttribute;
  // subdivide by re-triangulating with interior points is expensive; dome via a smooth bump instead
  for (let i = 0; i < tp.count; i++) tp.setY(i, 2.5);
  terrainG.computeVertexNormals();
  const sand = new THREE.MeshStandardMaterial({ color: 0x8c8470, roughness: 0.95, envMap, envMapIntensity: 0.2 });
  const ground = new THREE.MeshStandardMaterial({ color: 0x1b2a1d, roughness: 1 });
  group.add(new THREE.Mesh(terrainG, sand));
  // inner ground slightly smaller (beach band shows as the outer ring)
  const inner = coast.map((p) => p.clone().multiplyScalar(0.985));
  const innerG = new THREE.ShapeGeometry(new THREE.Shape(inner.map((p) => new THREE.Vector2(p.x, -p.y))), 1);
  innerG.rotateX(-Math.PI / 2); innerG.translate(0, 3.2, 0);
  group.add(new THREE.Mesh(innerG, ground));
  // jungle canopy: instanced blobs scattered inside the coast (rejection sampling)
  const box = new THREE.Box2().setFromPoints(inner);
  const inside = (x: number, z: number) => {
    let c = false;
    for (let i = 0, j = inner.length - 1; i < inner.length; j = i++) {
      const a = inner[i], b = inner[j];
      if ((a.y > z) !== (b.y > z) && x < ((b.x - a.x) * (z - a.y)) / (b.y - a.y) + a.x) c = !c;
    }
    return c;
  };
  const N = 2600;
  const canopyG = new THREE.IcosahedronGeometry(1, 2);
  const canopy = new THREE.InstancedMesh(canopyG, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.95, flatShading: false }), N);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), col = new THREE.Color();
  let k = 0, tries = 0;
  while (k < N && tries < N * 20) {
    tries++;
    const x = box.min.x + hash(tries * 1.3 + 0.1) * (box.max.x - box.min.x);
    const z = box.min.y + hash(tries * 2.7 + 0.5) * (box.max.y - box.min.y);
    if (!inside(x, z)) continue;
    const edge = Math.min(1, Math.hypot(x, z) / (S * 3.5));
    const r = (14 + hash(k * 3.1) * 16) * (opts.scale ?? 1) ** 0.3;
    const y = 3 + (1 - edge) * 22 + r * 0.6 + hash(k * 5.3) * 8;
    q.setFromEuler(new THREE.Euler(hash(k) * 0.4, hash(k * 1.7) * 6.28, 0));
    m.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(r, r * (0.7 + hash(k * 9.1) * 0.4), r));
    canopy.setMatrixAt(k, m);
    col.setHSL(0.3 + hash(k * 2.2) * 0.06, 0.35 + hash(k * 4.4) * 0.2, 0.09 + hash(k * 6.6) * 0.06);
    canopy.setColorAt(k, col);
    k++;
  }
  canopy.count = k;
  canopy.castShadow = true;
  group.add(canopy);
  // emergent palms along the beach (silhouettes against the sky)
  const trunkG = new THREE.CylinderGeometry(0.25, 0.4, 1, 6); trunkG.translate(0, 0.5, 0);
  const frondG = new THREE.ConeGeometry(1, 0.35, 7, 1, true); frondG.translate(0, -0.1, 0);
  const palmMat = new THREE.MeshStandardMaterial({ color: 0x15201a, roughness: 1, side: THREE.DoubleSide });
  for (let i = 0; i < 140; i++) {
    const p = inner[Math.floor(hash(i * 7.7) * inner.length)];
    const pos = new THREE.Vector3(p.x * 0.99, 3, p.y * 0.99);
    const h = 14 + hash(i * 3.3) * 10;
    const trunk = new THREE.Mesh(trunkG, palmMat); trunk.scale.set(1, h, 1); trunk.position.copy(pos);
    trunk.rotation.set((hash(i) - 0.5) * 0.35, 0, (hash(i * 2) - 0.5) * 0.35); group.add(trunk);
    const fr = new THREE.Mesh(frondG, palmMat); fr.scale.set(7, 7, 7); fr.position.copy(pos).add(new THREE.Vector3(0, h, 0)); group.add(fr);
  }
  // reef: a foam ring ~700 m offshore (real fringing reef), as a thin bright ribbon
  const reefPts = (GEO.coast as number[][]).map(([x, y]) => { const d = Math.hypot(x, y) || 1; return new THREE.Vector3(x * (1 + 0.7 / d) * S, 0.25, y * (1 + 0.7 / d) * S); });
  const reef = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(reefPts, true), 600, 6, 4, true), new THREE.MeshStandardMaterial({ color: 0xcfd8f0, emissive: new THREE.Color(0x6b7aa8), emissiveIntensity: 0.15, roughness: 0.8 }));
  reef.scale.y = 0.08; group.add(reef);
  // fires: warm point lights + small flame sprites in the tree line (no figures, ever)
  const fires: THREE.PointLight[] = [], fireMeshes: THREE.Mesh[] = [];
  const flameMat = new THREE.MeshBasicMaterial({ color: 0xffa040 });
  for (let i = 0; i < 6; i++) {
    const p = inner[Math.floor((0.08 + i * 0.045) * inner.length) % inner.length];
    const pos = new THREE.Vector3(p.x * 0.975, 4, p.y * 0.975);
    const l = new THREE.PointLight(0xff8a30, 0, 120, 1.6); l.position.copy(pos).add(new THREE.Vector3(0, 3, 0)); group.add(l); fires.push(l);
    const fm = new THREE.Mesh(new THREE.ConeGeometry(1.2, 3.5, 8), flameMat.clone()); fm.position.copy(pos).add(new THREE.Vector3(0, 1.8, 0)); fm.visible = false; group.add(fm); fireMeshes.push(fm);
  }
  return {
    group, fires, fireMeshes,
    setFires(on, t) {
      fires.forEach((l, i) => {
        const v = on[i] ?? 0;
        const fl = 0.85 + 0.15 * Math.sin(t * 9 + i * 2) * Math.sin(t * 3.7 + i);
        l.intensity = v * 900 * fl;
        fireMeshes[i].visible = v > 0.02;
        fireMeshes[i].scale.set(1, 0.6 + 0.4 * fl, 1).multiplyScalar(Math.max(0.01, v));
        ((fireMeshes[i].material as THREE.MeshBasicMaterial).color).setRGB(1.6 * fl, 0.75 * fl, 0.25);
      });
    },
  };
};
