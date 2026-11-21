// Export code-built three.js props to binary glTF (GLB) headlessly in Node.
import "./nodePolyfills";
import * as THREE from "three";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { mergeGeometries, mergeVertices } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/**
 * Replace every InstancedMesh with one merged Mesh (vertex colours carry the per-instance colour).
 * Blender's glTF importer does not keep EXT_mesh_gpu_instancing per-instance colours, so baking is
 * the default; pass instanced=true to keep the (much smaller) instanced form.
 */
export const bakeInstances = (root: THREE.Object3D) => {
  const todo: THREE.InstancedMesh[] = [];
  root.traverse((o: any) => o.isInstancedMesh && todo.push(o));
  for (const im of todo) {
    // non-indexed polyhedra duplicate every vertex: drop uv (seams) and weld to an indexed mesh
    const base = im.geometry.clone();
    if (base.attributes.uv) base.deleteAttribute("uv");
    const merged = mergeVertices(base, 1e-4);
    const parts: THREE.BufferGeometry[] = [];
    const m = new THREE.Matrix4(), c = new THREE.Color(1, 1, 1);
    for (let i = 0; i < im.count; i++) {
      im.getMatrixAt(i, m);
      if (im.instanceColor) im.getColorAt(i, c);
      const g = merged.clone().applyMatrix4(m);
      const n = g.attributes.position.count, col = new Float32Array(n * 3);
      for (let k = 0; k < n; k++) { col[k * 3] = c.r; col[k * 3 + 1] = c.g; col[k * 3 + 2] = c.b; }
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
      parts.push(g);
    }
    const geo = mergeGeometries(parts, false)!;
    const mat = (im.material as THREE.MeshStandardMaterial).clone();
    mat.vertexColors = true; mat.name = (im.material as THREE.Material).name;
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = im.name; mesh.castShadow = im.castShadow;
    mesh.position.copy(im.position); mesh.quaternion.copy(im.quaternion); mesh.scale.copy(im.scale);
    im.parent!.add(mesh); im.parent!.remove(im);
  }
};

export const exportGLB = async (root: THREE.Object3D, opts: { instanced?: boolean } = {}): Promise<ArrayBuffer> => {
  if (!opts.instanced) bakeInstances(root);
  root.updateMatrixWorld(true);
  const scene = new THREE.Scene();
  scene.name = root.name;
  scene.add(root);
  // GLTFExporter warns once per mesh about normals / light decay; collapse to one line each
  const seen = new Map<string, number>(), warn = console.warn;
  console.warn = (...a: unknown[]) => { const k = String(a[0]); seen.set(k, (seen.get(k) ?? 0) + 1); };
  try {
    return await new Promise((res, rej) =>
      new GLTFExporter().parse(scene, (r) => res(r as ArrayBuffer), rej, { binary: true, onlyVisible: false, includeCustomExtensions: false }),
    );
  } finally {
    console.warn = warn;
    seen.forEach((n, k) => warn(`${k}${n > 1 ? ` (x${n})` : ""}`));
  }
};

/** Header-level stats of a GLB (parses the JSON chunk only). */
export const glbStats = (buf: ArrayBuffer) => {
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== 0x46546c67) throw new Error("not a GLB");
  const len = dv.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, len)));
  let tris = 0, verts = 0;
  for (const mesh of json.meshes ?? []) for (const p of mesh.primitives) {
    const pos = json.accessors[p.attributes.POSITION];
    verts += pos.count;
    tris += p.indices !== undefined ? json.accessors[p.indices].count / 3 : pos.count / 3;
  }
  return {
    bytes: buf.byteLength, nodes: (json.nodes ?? []).length, meshes: (json.meshes ?? []).length,
    materials: (json.materials ?? []).length, verts, tris: Math.round(tris),
    extensionsUsed: json.extensionsUsed ?? [], lights: json.extensions?.KHR_lights_punctual?.lights?.length ?? 0,
  };
};
