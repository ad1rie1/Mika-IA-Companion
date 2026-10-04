import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { LIGHT_ANCHOR_NAMES, type RoomParts } from "./RoomParts";

/**
 * The authored room (frontend/assets-src/room.blend → public/models/room.glb).
 *
 * The GLB carries a baked ambient-occlusion atlas as each material's glTF
 * occlusionTexture on UV set 1; GLTFLoader turns it into `aoMap` on uv
 * channel 1, so contact shadows exist without baking any *lighting* — the
 * room's lights stay dynamic (sleep dimming, time of day).
 *
 * Names are the contract with Blender (see assets-src/README.md):
 *   Window_Sky            card behind the window opening → sky shader
 *   Monitor_Screen        M_MonitorScreen, flickered
 *   Clock_HourHand/…Minute rotated to the real time
 *   LightAnchor_<Name>    empties marking where Environment puts lights
 *   DeskChair             one movable object (origin on the floor, under
 *                         the seat centre) for the locomotion code
 * Every other emissive material (lamps, neon, star, moon lamp, candle) is
 * tracked by Environment's sleep-phase multiplier.
 */

export const ROOM_URL = "/models/room.glb";

/** Ambient occlusion strength on the baked atlas (it only darkens the
 * indirect light — hemisphere, ambient, environment). */
const AO_INTENSITY = 1.0;

/** Big surfaces that must not cast shadows: the key light sits inside the
 * room box, so walls/ceiling casting would blacken everything. */
const NO_CAST = /^(Shell_|Window_Sky|Rug|CeilingLamp_|Curtain_Rod|Clock_|Neon_)/;

export async function loadRoomModel(
  url: string = ROOM_URL,
  maxAnisotropy = 8
): Promise<RoomParts> {
  const gltf = await new GLTFLoader().loadAsync(url);
  const root = gltf.scene;
  root.name = "RoomModel";

  let windowSky: THREE.Mesh | null = null;
  let monitorScreen: THREE.MeshStandardMaterial | null = null;
  const emissives = new Set<THREE.MeshStandardMaterial>();
  const textures = new Set<THREE.Texture>();

  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh) return;
    if (mesh.name === "Window_Sky") {
      windowSky = mesh;
      mesh.castShadow = false;
      mesh.receiveShadow = false;
      return;
    }
    mesh.castShadow = !NO_CAST.test(mesh.name) && !isNamedUnder(mesh, NO_CAST);
    mesh.receiveShadow = true;

    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const m of mats) {
      const mat = m as THREE.MeshStandardMaterial;
      if (!mat.isMeshStandardMaterial) continue;
      if (mat.aoMap) mat.aoMapIntensity = AO_INTENSITY;
      for (const t of [mat.map, mat.aoMap, mat.emissiveMap]) if (t) textures.add(t);
      const glows = mat.emissiveIntensity > 0 && mat.emissive.getHex() !== 0;
      if (mat.name === "M_MonitorScreen") {
        monitorScreen = mat;
        mesh.castShadow = false;
      } else if (glows) {
        emissives.add(mat);
        // a glowing shade casting a shadow of itself looks wrong
        mesh.castShadow = false;
      }
    }
  });

  for (const t of textures) t.anisotropy = maxAnisotropy;

  // Light anchors (empties exported as nodes).
  root.updateMatrixWorld(true);
  const lightAnchors: RoomParts["lightAnchors"] = {};
  for (const name of LIGHT_ANCHOR_NAMES) {
    const node = root.getObjectByName(`LightAnchor_${name}`);
    if (node) lightAnchors[name] = node.getWorldPosition(new THREE.Vector3());
  }

  const hour = root.getObjectByName("Clock_HourHand");
  const minute = root.getObjectByName("Clock_MinuteHand");

  return {
    root,
    windowSky,
    monitorScreen,
    emissives: [...emissives],
    lightAnchors,
    clockHands: hour && minute ? { hour, minute } : null,
  };
}

/** True when an ancestor's name matches (GLTFLoader nests multi-material
 * meshes under a Group carrying the node name). */
function isNamedUnder(obj: THREE.Object3D, re: RegExp): boolean {
  for (let p = obj.parent; p; p = p.parent) if (re.test(p.name)) return true;
  return false;
}
