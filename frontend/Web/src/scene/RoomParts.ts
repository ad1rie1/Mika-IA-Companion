import type * as THREE from "three";

/**
 * What Environment needs to know about a room, whoever built it: the
 * authored GLB (RoomModel.ts) or the procedural fallback (ProceduralRoom.ts).
 * Environment owns the lights and the animation; a room only says which of
 * its surfaces glow and where its lamps are.
 */
export interface RoomParts {
  root: THREE.Object3D;
  /** The surface seen through the window; Environment puts the sky on it. */
  windowSky: THREE.Mesh | null;
  /** Screen material (emissive), flickered by Environment. */
  monitorScreen: THREE.MeshStandardMaterial | null;
  /** Every other glowing material, scaled with the sleep-phase multiplier. */
  emissives: THREE.MeshStandardMaterial[];
  /** Named light positions (world), e.g. "DeskLamp", "BedLamp", "Ceiling". */
  lightAnchors: Partial<Record<LightAnchorName, THREE.Vector3>>;
  /** Wall-clock hands (rotate about local Z, 12 o'clock at rest). */
  clockHands: { hour: THREE.Object3D; minute: THREE.Object3D } | null;
}

export type LightAnchorName = "DeskLamp" | "BedLamp" | "Ceiling" | "Monitor" | "Window";

export const LIGHT_ANCHOR_NAMES: readonly LightAnchorName[] = [
  "DeskLamp",
  "BedLamp",
  "Ceiling",
  "Monitor",
  "Window",
];

/** Room bounds (three.js metres). Mika stands at (0, 0, -0.5); the room is
 * centred on her so the orbit camera (maxDistance 3.4) stays inside. */
export const ROOM = {
  minX: -4,
  maxX: 4,
  minZ: -4.5,
  maxZ: 3.5,
  height: 3.2,
  centerZ: -0.5,
};
