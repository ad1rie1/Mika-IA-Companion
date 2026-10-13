import { center, size, type Box, type Side } from "./meshParts";

/**
 * Ce que la pièce du client web (public/models/room.glb) dessine des objets
 * du monde : à chaque identifiant d'objet, les nœuds du GLB qui le montrent —
 * ce qu'on vise pour agir dessus, ce qu'on cache quand une édition le retire.
 * Le pendant de `export_unity.py` (la table `O(…)` des objets), sur les noms
 * des maillages joints de la pièce web (`roomlib.join`). Un objet du monde
 * absent d'ici est montré par une silhouette ; un nœud absent du GLB (la pièce
 * procédurale de secours) est ignoré.
 */
export const ROOM_OBJECTS: Readonly<Record<string, readonly string[]>> = {
  writing_desk: ["Desk", "Desk_Keyboard", "Desk_Monitor", "Monitor_Screen", "Desk_Props"],
  desk_chair: ["DeskChair"],
  bed_frame: ["Bed_Frame", "Bed_Mattress", "Bed_Pillow", "Bed_Cushion", "Bed_Duvet", "Bed_Throw"],
  nightstand: ["Bedside_Table"],
  wardrobe: ["Wardrobe"],
  shelves: ["Bookshelf", "Bookshelf_Items"],
  snake_plant: ["Plant_SnakePotJ", "Plant_SnakeLeaves"],
  ficus: ["Plant_Fig", "Plant_FigLeaves"],
  // Le ciel qu'on voit par la fenêtre en fait partie : on vise la fenêtre en regardant dehors.
  window_pane: ["Window_Frame", "Window_Sky"],
  bedroom_door: ["Door", "Door_Handle"],
  desk_lamp: ["DeskLamp", "DeskLamp_Head", "DeskLamp_Bulb"],
};

/** Un morceau d'un maillage du GLB : une composante connexe d'une de ses primitives. */
export interface LeafPart {
  node: string;
  material: string;
  box: Box;
}

/**
 * Un battant qui tourne sur sa charnière selon l'état de son objet (le
 * `StateHinge` d'Unity, réglé comme `RoomImporter.Hinges`) : quels morceaux
 * le composent, où est la charnière (un coin de leur boîte), de quel côté il
 * s'ouvre, de combien et en combien de temps.
 */
export interface HingeSpec {
  object: string;
  /** Le nom du battant (celui de l'export Unity). */
  name: string;
  /** Les nœuds du GLB où chercher ses morceaux ; le premier porte la carcasse. */
  nodes: readonly string[];
  /**
   * Ce morceau en fait-il partie ? `body` : la boîte du plus gros morceau du
   * premier nœud (la carcasse de l'armoire, le cadre de la fenêtre).
   */
  takes(part: LeafPart, body: Box): boolean;
  /** La charnière : un coin de la boîte du plus gros morceau du battant (le panneau, pas sa poignée). */
  pivot: { x: Side; y: Side; z: Side };
  /** Où va le bord libre quand il s'ouvre (vers la pièce). */
  opensToward: { x: number; z: number };
  angleDeg: number;
  durationS: number;
}

/** La façade de l'armoire : ce qui est devant la carcasse. */
const onWardrobeFront = (part: LeafPart, body: Box) => part.box.min[0] >= body.max[0] - 0.003;

export const HINGES: readonly HingeSpec[] = [
  {
    // La porte : le panneau peint et la poignée en laiton (l'interrupteur, blanc, reste au mur).
    object: "bedroom_door",
    name: "Door_Leaf",
    nodes: ["Door", "Door_Handle"],
    takes: (part) =>
      (part.node === "Door" && part.material === "M_DoorPaint") ||
      (part.node === "Door_Handle" && part.material === "M_Brass"),
    pivot: { x: "max", y: "min", z: "min" },
    opensToward: { x: 0, z: -1 },
    angleDeg: 95,
    durationS: 1.2,
  },
  {
    // La fenêtre n'a pas de vrai vantail dans les sources : la croisée (les
    // deux meneaux, 4 cm d'épaisseur, dans le cadre) en sert, comme côté Unity.
    object: "window_pane",
    name: "Window_Sash",
    nodes: ["Window_Frame"],
    takes: (part, body) => {
      const [dx] = size(part.box);
      const [, cy, cz] = center(part.box);
      return dx > 0.03 && dx < 0.05 && cy > body.min[1] && cy < body.max[1] && cz > body.min[2] && cz < body.max[2];
    },
    pivot: { x: "max", y: "min", z: "min" },
    opensToward: { x: 1, z: 0 },
    angleDeg: 70,
    durationS: 1.6,
  },
  {
    // « droite / gauche » vues depuis la pièce, face à l'armoire (regard vers −x).
    object: "wardrobe",
    name: "Wardrobe_DoorR",
    nodes: ["Wardrobe"],
    takes: (part, body) => onWardrobeFront(part, body) && center(part.box)[2] < center(body)[2],
    pivot: { x: "max", y: "min", z: "min" },
    opensToward: { x: 1, z: 0 },
    angleDeg: 100,
    durationS: 1.2,
  },
  {
    object: "wardrobe",
    name: "Wardrobe_DoorL",
    nodes: ["Wardrobe"],
    takes: (part, body) => onWardrobeFront(part, body) && center(part.box)[2] >= center(body)[2],
    pivot: { x: "max", y: "min", z: "max" },
    opensToward: { x: 1, z: 0 },
    angleDeg: 100,
    durationS: 1.2,
  },
];

/** Les états qu'un battant connaît ; un autre état ne le fait pas bouger. */
export const HINGE_OPEN = "open";
export const HINGE_CLOSED = "closed";

/**
 * La réaction brève de son corps à un geste qu'on lui fait (le
 * `GestureRules.TouchGesture` d'Unity) : une caresse sur la tête lui fait
 * baisser un peu la tête, une pichenette la fait sursauter. Ce qu'elle en
 * ressent revient ensuite par la dérive de son humeur.
 */
export const TOUCH_REACTIONS: Readonly<Record<string, string>> = {
  pat_head: "gesture_bashful",
  poke: "gesture_surprised",
};

/** Le clip qui montre un geste du monde (`wave`…) quand c'est elle qui le fait. */
export const GESTURE_CLIPS: Readonly<Record<string, string>> = {
  wave: "gesture_wave",
  nod: "gesture_nod",
  shake_head: "gesture_headshake",
};

/** Le clip d'une clé d'animation d'affordance (`drink`, `press`…) : `gesture_<clé>` s'il existe. */
export function affordanceClip(animation: string | null | undefined): string | null {
  return animation ? `gesture_${animation}` : null;
}
