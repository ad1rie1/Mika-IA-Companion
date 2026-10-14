/**
 * Les battants sur la VRAIE pièce (public/models/room.glb) : la croisée de la
 * fenêtre, les deux portes de l'armoire et la porte se retrouvent parmi les
 * morceaux joints, avec leur charnière où l'export Unity la met. Lu en Node
 * (fs) — exclu du typage de l'application, comme les autres tests « smoke ».
 *
 * Le GLB est lu à la main (JSON + tampon binaire) : le chargeur glTF de
 * three.js veut un navigateur pour les textures. Chaque nœud devient ce que
 * GLTFLoader en ferait : un Mesh pour une primitive, un Group de Mesh sinon.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { components } from "../meshParts";
import { buildHinges, extractPart } from "../RoomHinges";
import { DESK_PROPS, HINGES, ROOM_OBJECTS, takesProp } from "../roomBindings";

const GLB = path.resolve(__dirname, "../../../public/models/room.glb");

interface Gltf {
  nodes: { name?: string; mesh?: number }[];
  meshes: { primitives: { attributes: { POSITION: number }; indices?: number; material?: number }[] }[];
  materials: { name?: string }[];
  accessors: { bufferView: number; byteOffset?: number; count: number; componentType: number; type: string }[];
  bufferViews: { byteOffset?: number; byteStride?: number }[];
}

function readGlb(): { json: Gltf; bin: Buffer } {
  const b = fs.readFileSync(GLB);
  const jsonLength = b.readUInt32LE(12);
  const json = JSON.parse(b.subarray(20, 20 + jsonLength).toString("utf-8")) as Gltf;
  const binStart = 20 + jsonLength + 8;
  return { json, bin: b.subarray(binStart) };
}

function accessor(g: Gltf, bin: Buffer, i: number): Float32Array | Uint32Array {
  const a = g.accessors[i];
  const view = g.bufferViews[a.bufferView];
  const width = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }[a.type] ?? 1;
  const offset = (view.byteOffset ?? 0) + (a.byteOffset ?? 0);
  const size = a.componentType === 5126 || a.componentType === 5125 ? 4 : a.componentType === 5123 ? 2 : 1;
  const stride = view.byteStride ?? size * width;
  const out = a.componentType === 5126 ? new Float32Array(a.count * width) : new Uint32Array(a.count * width);
  for (let k = 0; k < a.count; k++) {
    for (let c = 0; c < width; c++) {
      const at = offset + k * stride + c * size;
      out[k * width + c] =
        a.componentType === 5126 ? bin.readFloatLE(at) : a.componentType === 5125 ? bin.readUInt32LE(at)
          : a.componentType === 5123 ? bin.readUInt16LE(at) : bin.readUInt8(at);
    }
  }
  return out;
}

function room(): THREE.Group {
  const { json, bin } = readGlb();
  const root = new THREE.Group();
  root.name = "RoomModel";
  for (const node of json.nodes) {
    if (node.mesh === undefined || !node.name) continue;
    const meshes = json.meshes[node.mesh].primitives.map((p) => {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(accessor(json, bin, p.attributes.POSITION), 3));
      if (p.indices !== undefined) geometry.setIndex(new THREE.BufferAttribute(accessor(json, bin, p.indices), 1));
      const material = new THREE.MeshStandardMaterial();
      material.name = json.materials[p.material ?? 0]?.name ?? "";
      return new THREE.Mesh(geometry, material);
    });
    if (meshes.length === 1) {
      meshes[0].name = node.name;
      root.add(meshes[0]);
    } else {
      const group = new THREE.Group();
      group.name = node.name;
      for (const m of meshes) group.add(m);
      root.add(group);
    }
  }
  return root;
}

function triangles(obj: THREE.Object3D): number {
  let n = 0;
  obj.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (mesh.isMesh) n += (mesh.geometry.index?.count ?? 0) / 3;
  });
  return n;
}

const present = fs.existsSync(GLB);

describe.skipIf(!present)("les battants de la vraie pièce", () => {
  it("chaque objet du monde que la pièce dessine a ses nœuds", () => {
    const r = room();
    for (const [id, nodes] of Object.entries(ROOM_OBJECTS)) {
      expect(r.getObjectByName(nodes[0]), id).toBeDefined();
    }
  });

  it("les boîtes jointes se retrouvent une à une", () => {
    const sash = room().getObjectByName("Window_Frame") as THREE.Mesh;
    const parts = components(sash.geometry.getAttribute("position").array, sash.geometry.index!.array);
    // le cadre (ses quatre montants se touchent), l'appui, l'allège, l'encadrement, et les deux meneaux
    expect(parts.length).toBe(6);
  });

  it("chaque battant est trouvé, sa charnière à sa place, sans perdre un triangle", () => {
    const r = room();
    const before = triangles(r);
    const hinges = buildHinges(r);
    expect(hinges.map((h) => h.spec.name)).toEqual(HINGES.map((s) => s.name));
    expect(triangles(r)).toBe(before);

    const at = (name: string) => hinges.find((h) => h.spec.name === name)!;
    const leafTriangles = (name: string) => triangles(at(name).pivot);
    // la porte : son panneau (et ses deux moulures) et sa poignée ; l'interrupteur reste au mur
    expect(at("Door_Leaf").pivot.position.x).toBeCloseTo(2.23, 2);
    expect(at("Door_Leaf").pivot.position.z).toBeCloseTo(3.56, 2);
    expect(leafTriangles("Door_Leaf")).toBe(3 * 108 + 240 + 108 + 40);
    // la croisée tourne sur son bord côté z min, vers la pièce
    expect(at("Window_Sash").pivot.position.x).toBeCloseTo(-4.07, 2);
    expect(at("Window_Sash").pivot.position.z).toBeCloseTo(-1.845, 2);
    expect(leafTriangles("Window_Sash")).toBe(2 * 108);
    // chaque porte d'armoire : le battant, son panneau, sa poignée et ses deux pattes
    for (const name of ["Wardrobe_DoorR", "Wardrobe_DoorL"]) expect(leafTriangles(name)).toBe(108 * 3 + 2 * 44);
    expect(at("Wardrobe_DoorR").pivot.position.z).toBeCloseTo(-4.47, 2);
    expect(at("Wardrobe_DoorL").pivot.position.z).toBeCloseTo(-3.29, 2);
  });

  it("ouverts, les battants s'ouvrent vers la pièce", () => {
    const r = room();
    const hinges = buildHinges(r);
    const freeEdge = (name: string) => {
      const h = hinges.find((x) => x.spec.name === name)!;
      h.apply("open", true);
      r.updateMatrixWorld(true);
      return new THREE.Box3().setFromObject(h.pivot).getCenter(new THREE.Vector3());
    };
    // la porte vient dans la chambre (z < 3,5), la croisée et les portes d'armoire aussi (x plus grand)
    expect(freeEdge("Door_Leaf").z).toBeLessThan(3.4);
    expect(freeEdge("Window_Sash").x).toBeGreaterThan(-3.9);
    expect(freeEdge("Wardrobe_DoorR").x).toBeGreaterThan(-3.2);
    expect(freeEdge("Wardrobe_DoorL").x).toBeGreaterThan(-3.2);
  });

  it("un autre état que « open » ou « closed » ne bouge rien", () => {
    const hinge = buildHinges(room())[0];
    hinge.apply("open", true);
    hinge.apply("ajar", true);
    expect(hinge.pivot.rotation.y).toBeCloseTo(hinge.openAngle, 6);
    hinge.apply("closed", false);
    hinge.update(0.6);
    expect(Math.abs(hinge.pivot.rotation.y)).toBeLessThan(Math.abs(hinge.openAngle));
    hinge.update(1);
    expect(hinge.pivot.rotation.y).toBeCloseTo(0, 6);
  });

  it("la tasse, le stylo et la souris se sortent des accessoires du bureau, là où les gestes les attendent", () => {
    const r = room();
    const before = triangles(r);
    const got = Object.fromEntries(
      DESK_PROPS.map((spec) => [spec.name, extractPart(r, spec.name, [spec.node], (p) => takesProp(spec, p))])
    );
    expect(triangles(r)).toBe(before);
    expect(triangles(got.mug!.group)).toBe(448 + 140 + 96);
    expect(triangles(got.pen!.group)).toBe(40);
    expect(triangles(got.mouse!.group)).toBe(288);
    for (const spec of DESK_PROPS) {
      const g = got[spec.name]!.group;
      expect(Math.hypot(g.position.x - spec.at.x, g.position.z - spec.at.z), spec.name).toBeLessThan(0.03);
      expect(g.position.y, spec.name).toBeGreaterThan(0.74); // sur le plateau
    }
  });

  it("le plan de l'atelier et la table du web disent les mêmes places", () => {
    const plan = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, "../../../../Unity/ArtSource/atelier/desk_plan.json"), "utf-8")
    ) as { objects: Record<string, { room: [number, number] }> };
    for (const spec of DESK_PROPS) {
      const [x, z] = plan.objects[spec.name].room;
      expect([spec.at.x, spec.at.z], spec.name).toEqual([x, z]);
    }
  });
});
