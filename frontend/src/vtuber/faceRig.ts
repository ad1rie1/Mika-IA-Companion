import * as THREE from "three";
import {
  VRMExpression,
  VRMExpressionMorphTargetBind,
  type VRM,
} from "@pixiv/three-vrm";

/**
 * Raw morph targets as named VRM expressions.
 *
 * The Perula model ships 342 morph targets but only exposes 118 of them
 * through its VRM blend-shape groups — and the rich custom groups
 * (`Shocked`, `Sad1`, `Angry1`, `LMAO`…) each bundle a cartoon effect with
 * the facial movement: swirl eyes, a sweat drop, tears on any sadness at
 * any intensity. Registering the underlying morphs one by one lets each
 * layer compose exactly what it needs (a brow, a lid, a blush that fades
 * in on its own clock) instead of buying a whole bundle.
 *
 * A raw expression is named `raw:<morph>` so it can never collide with a
 * group of the model (`Blink` the group vs `blink` the preset already
 * coexist; a third spelling would be one too many). Registration is
 * idempotent and per-VRM, and a morph the model does not carry is simply
 * not registered — callers check `has()`, exactly as they already do for
 * the model's own groups.
 */
export const RAW_PREFIX = "raw:";

export function rawName(morph: string): string {
  return RAW_PREFIX + morph;
}

/**
 * Register `raw:<morph>` expressions for every listed morph found on the
 * model. Returns the morph names actually available (registered now or
 * earlier). Meshes are grouped by morph index: primitives of one glTF mesh
 * share their target list, different meshes may not.
 */
export function registerRawMorphs(vrm: VRM, morphs: readonly string[]): Set<string> {
  const manager = vrm.expressionManager;
  const available = new Set<string>();
  if (!manager || !vrm.scene) return available;

  const meshes: THREE.Mesh[] = [];
  vrm.scene.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (mesh.isMesh && mesh.morphTargetDictionary && mesh.morphTargetInfluences) {
      meshes.push(mesh);
    }
  });

  for (const morph of morphs) {
    const name = rawName(morph);
    if (manager.getExpression(name)) {
      available.add(morph);
      continue;
    }
    const byIndex = new Map<number, THREE.Mesh[]>();
    for (const mesh of meshes) {
      const index = mesh.morphTargetDictionary![morph];
      if (index === undefined) continue;
      const list = byIndex.get(index) ?? [];
      list.push(mesh);
      byIndex.set(index, list);
    }
    if (byIndex.size === 0) continue;

    const expression = new VRMExpression(name);
    for (const [index, primitives] of byIndex) {
      expression.addBind(new VRMExpressionMorphTargetBind({ primitives, index, weight: 1 }));
    }
    manager.registerExpression(expression);
    available.add(morph);
  }
  return available;
}

/**
 * Morphs that draw a manga SYMBOL rather than move a face: tears and
 * blush (owned by the physiology layer, which gives them their own slow
 * clock), sweat drops, gloom shadows, swirl / heart / star / ><-eyes, black
 * or white eyes, pinpoint pupils, oversized highlights. The model's
 * custom groups bundle them with the real facial movement — `Shocked`
 * (surprise) draws swirl eyes and a sweat drop, `Sad1` a tear at ANY
 * sadness intensity, `Angry1` tears and a red face.
 */
export const SYMBOL_MORPHS: ReadonlySet<string> = new Set([
  "Tear", "Tear2", "TearFlow", "EyeWatery",
  "FaceRed", "FaceRed2", "FaceRed3",
  "FaceSweat", "FaceSweat2", "FaceShadow", "FaceShadow2", "FaceShadow3",
  "FaceSnot", "FaceSnotLong", "FaceSnotBubbles", "FaceSnotBubblesBig", "FaceSnotBubblesSmall",
  "Eye@@", "EyeStar", "EyeHeart", "EyeHeartSmall", "Eye><", "Eye0 0", "Eye0 0VSmall", "Eye0 0USmall",
  "EyeBlack", "EyeWhite", "EyeStare", "EyeHide", "EyeBlackCircles",
  "EyeIrisWhite", "EyeIrisClear", "EyeIrisSmall", "EyeIrisBig",
  "EyePupilBlackLine", "EyePupilCircle", "EyePupilSmall",
  "EyeHighlightHide", "EyeHighlightBig", "EyeHighlightDown", "EyeHighlightStar", "EyeHighlightHeart",
  "Mouth△", "Mouth^", "Mouthω", "Mouth□",
]);

/** Eye-direction morphs: the gaze controller owns where the eyes point
 * (bones, with saccades and aversions) — an expression that also rolls
 * the irises up (`Shy`, `Disgust`) fights it. */
export function isGazeMorph(morph: string): boolean {
  return /^eyeLook/i.test(morph);
}

export const CLEAN_PREFIX = "clean:";

export function cleanName(group: string): string {
  return CLEAN_PREFIX + group;
}

function morphNameOf(mesh: THREE.Mesh, index: number): string | null {
  const dict = mesh.morphTargetDictionary;
  if (!dict) return null;
  for (const [name, i] of Object.entries(dict)) if (i === index) return name;
  return null;
}

/**
 * Register `clean:<group>` copies of the model's expression groups with
 * every bind on a stripped morph removed (default: symbols and gaze).
 * The author's composition of brows, lids and mouth is kept as tuned.
 * Returns the groups registered (now or earlier).
 */
export function registerCleanGroups(
  vrm: VRM,
  groups: readonly string[],
  strip: (morph: string) => boolean = (m) => SYMBOL_MORPHS.has(m) || isGazeMorph(m)
): Set<string> {
  const manager = vrm.expressionManager;
  const available = new Set<string>();
  if (!manager) return available;

  for (const group of groups) {
    const name = cleanName(group);
    if (manager.getExpression(name)) {
      available.add(group);
      continue;
    }
    const source = manager.getExpression(group);
    if (!source) continue;
    const expression = new VRMExpression(name);
    expression.isBinary = source.isBinary;
    for (const bind of source.binds) {
      if (bind instanceof VRMExpressionMorphTargetBind) {
        const morph = bind.primitives[0] ? morphNameOf(bind.primitives[0], bind.index) : null;
        if (morph && strip(morph)) continue;
        expression.addBind(
          new VRMExpressionMorphTargetBind({
            primitives: bind.primitives,
            index: bind.index,
            weight: bind.weight,
          })
        );
      }
    }
    manager.registerExpression(expression);
    available.add(group);
  }
  return available;
}
