/**
 * Les morceaux d'un maillage, sans three.js : la pièce (room.glb) joint en un
 * seul maillage par meuble des boîtes qui, dans les scripts Blender, étaient
 * des objets séparés (`roomlib.join`). Une porte d'armoire, la croisée d'une
 * fenêtre, un battant de porte s'y retrouvent comme des composantes connexes
 * — des triangles reliés par leurs sommets. L'exporteur glTF dédouble les
 * sommets aux arêtes vives (normales, UV), si bien qu'on les soude par
 * position avant de chercher ce qui se touche.
 */

export type Vec3 = [number, number, number];

export interface Box {
  min: Vec3;
  max: Vec3;
}

export interface Component {
  /** Les triangles (numéro t : sommets 3t, 3t+1, 3t+2 de l'index). */
  triangles: number[];
  box: Box;
}

/** Les sommets se soudent à un dixième de millimètre près. */
const WELD = 1e4;

/**
 * Les composantes connexes d'un maillage triangulé. `positions` : x, y, z à
 * la suite (dans l'espace où l'on veut les boîtes) ; `index` : null pour un
 * maillage non indexé.
 */
export function components(positions: ArrayLike<number>, index: ArrayLike<number> | null): Component[] {
  const count = index ? index.length : positions.length / 3;
  const triangles = Math.floor(count / 3);
  const vertex = (k: number) => (index ? index[k] : k);
  const key = (v: number) =>
    `${Math.round(positions[3 * v] * WELD)},${Math.round(positions[3 * v + 1] * WELD)},${Math.round(positions[3 * v + 2] * WELD)}`;

  const ids = new Map<string, number>();
  const parent: number[] = [];
  const idOf = (v: number) => {
    const k = key(v);
    let id = ids.get(k);
    if (id === undefined) {
      id = parent.length;
      parent.push(id);
      ids.set(k, id);
    }
    return id;
  };
  const find = (x: number): number => {
    while (parent[x] !== x) {
      parent[x] = parent[parent[x]];
      x = parent[x];
    }
    return x;
  };

  const first: number[] = new Array(triangles);
  for (let t = 0; t < triangles; t++) {
    const a = idOf(vertex(3 * t));
    const b = idOf(vertex(3 * t + 1));
    const c = idOf(vertex(3 * t + 2));
    first[t] = a;
    for (const o of [b, c]) {
      const ra = find(a);
      const ro = find(o);
      if (ra !== ro) parent[ra] = ro;
    }
  }

  const byRoot = new Map<number, Component>();
  for (let t = 0; t < triangles; t++) {
    const root = find(first[t]);
    let comp = byRoot.get(root);
    if (!comp) {
      comp = { triangles: [], box: { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] } };
      byRoot.set(root, comp);
    }
    comp.triangles.push(t);
    for (let k = 0; k < 3; k++) {
      const v = vertex(3 * t + k);
      for (let axis = 0; axis < 3; axis++) {
        const p = positions[3 * v + axis];
        if (p < comp.box.min[axis]) comp.box.min[axis] = p;
        if (p > comp.box.max[axis]) comp.box.max[axis] = p;
      }
    }
  }
  return [...byRoot.values()];
}

export function size(box: Box): Vec3 {
  return [box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]];
}

export function center(box: Box): Vec3 {
  return [(box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2];
}

export function volume(box: Box): number {
  const [x, y, z] = size(box);
  return x * y * z;
}

export function union(boxes: readonly Box[]): Box | null {
  if (boxes.length === 0) return null;
  const out: Box = { min: [...boxes[0].min], max: [...boxes[0].max] };
  for (const b of boxes.slice(1)) {
    for (let axis = 0; axis < 3; axis++) {
      out.min[axis] = Math.min(out.min[axis], b.min[axis]);
      out.max[axis] = Math.max(out.max[axis], b.max[axis]);
    }
  }
  return out;
}

export type Side = "min" | "max";

/** Un coin d'une boîte (le pivot d'une charnière : « le bord x max, en bas, côté z min »). */
export function corner(box: Box, at: { x: Side; y: Side; z: Side }): Vec3 {
  return [box[at.x][0], box[at.y][1], box[at.z][2]];
}

/**
 * Le sens d'une ouverture autour de l'axe vertical (three.js, main droite) :
 * +1 quand une rotation positive emmène le bord libre du battant (`free`,
 * depuis la charnière) vers `toward`, −1 sinon. Une rotation θ autour de +Y
 * déplace (x, z) dans la direction (z, −x).
 */
export function openingSign(free: { x: number; z: number }, toward: { x: number; z: number }): 1 | -1 {
  return free.z * toward.x - free.x * toward.z >= 0 ? 1 : -1;
}
