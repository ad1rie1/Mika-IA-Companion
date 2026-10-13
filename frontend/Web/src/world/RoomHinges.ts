import * as THREE from "three";
import { center, components, corner, openingSign, union, volume, type Box, type Component } from "./meshParts";
import { HINGE_CLOSED, HINGE_OPEN, HINGES, type HingeSpec } from "./roomBindings";

/**
 * Un battant de la pièce sur sa charnière (porte, croisée de fenêtre, porte
 * d'armoire), qui suit l'état de son objet : « open » l'ouvre, « closed » le
 * ferme, tout autre état le laisse où il est. L'ouverture se joue en douceur
 * (smoothstep, comme `StateHinge` côté Unity) ; un instantané la pose d'un coup.
 */
export class Hinge {
  private angle = 0;
  private from = 0;
  private to = 0;
  private t = 1;

  constructor(
    readonly spec: HingeSpec,
    /** Le pivot (sur la charnière) qui porte les morceaux du battant. */
    readonly pivot: THREE.Object3D,
    /** L'angle ouvert, signé (radians autour de +Y). */
    readonly openAngle: number
  ) {}

  get object(): string {
    return this.spec.object;
  }

  apply(state: string | null | undefined, instant: boolean): void {
    const target = state === HINGE_OPEN ? this.openAngle : state === HINGE_CLOSED ? 0 : null;
    if (target === null) return;
    if (instant || this.spec.durationS <= 0) {
      this.angle = this.from = this.to = target;
      this.t = 1;
      this.pivot.rotation.y = target;
      return;
    }
    if (target === this.to && this.t < 1) return;
    this.from = this.angle;
    this.to = target;
    this.t = this.from === this.to ? 1 : 0;
  }

  update(dt: number): void {
    if (this.t >= 1) return;
    this.t = Math.min(1, this.t + dt / this.spec.durationS);
    const k = this.t * this.t * (3 - 2 * this.t);
    this.angle = this.from + (this.to - this.from) * k;
    this.pivot.rotation.y = this.angle;
  }
}

interface Source {
  mesh: THREE.Mesh;
  node: string;
  /** Du maillage à la racine de la pièce. */
  toRoot: THREE.Matrix4;
  parts: Component[];
}

/**
 * Sort les battants des maillages joints de la pièce : leurs triangles
 * quittent le maillage du meuble pour un maillage à eux, posé sous un pivot
 * placé sur la charnière. Les deux maillages partagent les mêmes tampons de
 * sommets (positions, normales, UV de l'occlusion) et les mêmes matériaux :
 * rien ne change à l'œil tant que le battant est fermé. Un battant
 * introuvable (une autre pièce, la pièce procédurale) est passé.
 */
export function buildHinges(root: THREE.Object3D, specs: readonly HingeSpec[] = HINGES): Hinge[] {
  root.updateMatrixWorld(true);
  const rootInverse = root.matrixWorld.clone().invert();
  const hinges: Hinge[] = [];
  for (const spec of specs) {
    const sources = sourcesOf(root, rootInverse, spec);
    const carcass = sources.filter((s) => s.node === spec.nodes[0]).flatMap((s) => s.parts);
    if (carcass.length === 0) continue;
    const body = carcass.reduce((a, b) => (volume(b.box) > volume(a.box) ? b : a)).box;
    const taken = new Map<Source, Component[]>();
    for (const s of sources) {
      const material = materialName(s.mesh);
      const parts = s.parts.filter((p) => spec.takes({ node: s.node, material, box: p.box }, body));
      if (parts.length > 0) taken.set(s, parts);
    }
    const leaf = [...taken.values()].flat();
    const box = union(leaf.map((p) => p.box));
    if (!box) {
      console.warn(`[monde] battant « ${spec.name} » introuvable dans la pièce`);
      continue;
    }
    // La charnière est au coin du plus gros morceau (le panneau, pas la poignée
    // qui dépasse) — comme l'export Unity la prend sur `Door_Slab`.
    const slab = leaf.reduce((a, b) => (volume(b.box) > volume(a.box) ? b : a)).box;
    hinges.push(mount(root, spec, slab, box, taken));
  }
  return hinges;
}

function sourcesOf(root: THREE.Object3D, rootInverse: THREE.Matrix4, spec: HingeSpec): Source[] {
  const out: Source[] = [];
  for (const name of spec.nodes) {
    const node = root.getObjectByName(name);
    if (!node) continue;
    node.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const toRoot = rootInverse.clone().multiply(mesh.matrixWorld);
      const positions = transformed(mesh.geometry, toRoot);
      const index = mesh.geometry.index?.array ?? null;
      out.push({ mesh, node: name, toRoot, parts: components(positions, index) });
    });
  }
  return out;
}

function transformed(geometry: THREE.BufferGeometry, m: THREE.Matrix4): Float32Array {
  const attr = geometry.getAttribute("position");
  const out = new Float32Array(attr.count * 3);
  const v = new THREE.Vector3();
  for (let i = 0; i < attr.count; i++) {
    v.fromBufferAttribute(attr, i).applyMatrix4(m);
    out[3 * i] = v.x;
    out[3 * i + 1] = v.y;
    out[3 * i + 2] = v.z;
  }
  return out;
}

function materialName(mesh: THREE.Mesh): string {
  const m = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
  return m?.name ?? "";
}

function mount(
  root: THREE.Object3D,
  spec: HingeSpec,
  slab: Box,
  box: Box,
  taken: Map<Source, Component[]>
): Hinge {
  const p = corner(slab, spec.pivot);
  const c = center(box);
  const sign = openingSign({ x: c[0] - p[0], z: c[2] - p[2] }, spec.opensToward);
  const pivot = new THREE.Group();
  pivot.name = `Hinge_${spec.name}`;
  pivot.position.set(p[0], p[1], p[2]);
  root.add(pivot);
  const offset = new THREE.Matrix4().makeTranslation(-p[0], -p[1], -p[2]);
  for (const [source, parts] of taken) {
    const leaf = split(source.mesh, new Set(parts.flatMap((part) => part.triangles)));
    offset.clone().multiply(source.toRoot).decompose(leaf.position, leaf.quaternion, leaf.scale);
    leaf.name = `${spec.name}_${source.node}`;
    pivot.add(leaf);
  }
  return new Hinge(spec, pivot, (sign * spec.angleDeg * Math.PI) / 180);
}

/**
 * Les triangles `take` quittent `mesh` pour un nouveau maillage (rendu) ;
 * `mesh` garde les autres. Les attributs sont partagés, pas copiés — et
 * l'ancienne géométrie n'est pas libérée : la libérer rendrait aussi les
 * tampons qu'elle partage.
 */
function split(mesh: THREE.Mesh, take: ReadonlySet<number>): THREE.Mesh {
  const geometry = mesh.geometry;
  const count = geometry.index ? geometry.index.count : geometry.getAttribute("position").count;
  const at = (k: number) => (geometry.index ? geometry.index.getX(k) : k);
  const kept: number[] = [];
  const moved: number[] = [];
  for (let t = 0; t < count / 3; t++) {
    const into = take.has(t) ? moved : kept;
    into.push(at(3 * t), at(3 * t + 1), at(3 * t + 2));
  }
  mesh.geometry = sharing(geometry, kept);
  const leaf = new THREE.Mesh(sharing(geometry, moved), mesh.material);
  leaf.castShadow = mesh.castShadow;
  leaf.receiveShadow = mesh.receiveShadow;
  leaf.renderOrder = mesh.renderOrder;
  return leaf;
}

function sharing(geometry: THREE.BufferGeometry, index: number[]): THREE.BufferGeometry {
  const out = new THREE.BufferGeometry();
  for (const [name, attr] of Object.entries(geometry.attributes)) out.setAttribute(name, attr);
  out.setIndex(index);
  out.boundingBox = geometry.boundingBox?.clone() ?? null;
  out.boundingSphere = geometry.boundingSphere?.clone() ?? null;
  if (!out.boundingSphere) out.computeBoundingSphere();
  return out;
}
