/**
 * Mika en VRM dans son coin — le port de `frontendv2/maquette/mika-vrm.js`, au même cadrage : son visage seul
 * dans le rond de la pastille, son buste dans la colonne du chat. Le modèle est celui du client web
 * (`frontend/Web/public/models/default.vrm`, VRM 0.x, ~100 Mo, non versionné), servi sous
 * `/ext/models/default.vrm` ou par `VITE_MIKA_VRM_URL`. Une vie simple et procédurale : souffle, clignements,
 * regard vers le pointeur, tête qui bouge, humeur sur le visage, bouche quand elle parle.
 *
 * Chargé à part (import dynamique) : three et three-vrm ne retardent pas l'écran. Sans WebGL, ou sans le
 * fichier, le portrait reste.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import type { MikaCorner } from "./corner";
import { emotionCategory } from "./labels";
import type { MikaStore } from "./store";

export function vrmUrl(): string {
  const env = import.meta.env.VITE_MIKA_VRM_URL;
  return typeof env === "string" && env.trim() ? env.trim() : "/ext/models/default.vrm";
}

/** L'humeur sur le visage, avec les expressions de base (VRM 0.x converties par three-vrm). */
const FACES: Record<string, Partial<Record<Expression, number>>> = {
  happy: { happy: 0.55 },
  excited: { happy: 0.7 },
  playful: { happy: 0.4 },
  love: { happy: 0.5 },
  curious: { happy: 0.16, relaxed: 0.12 },
  thinking: { relaxed: 0.12 },
  determined: {},
  tired: { relaxed: 0.38 },
  sad: { sad: 0.45 },
  melancholic: { sad: 0.3 },
  angry: { angry: 0.4 },
  surprised: { surprised: 0.35 },
  neutral: {},
};

/** Une humeur hors de la table : un visage de sa famille, à peine marqué. */
const BY_CATEGORY: Record<string, Partial<Record<Expression, number>>> = {
  positive: { happy: 0.35 },
  negative: { sad: 0.25 },
  complex: { relaxed: 0.1 },
};

const EXPRESSIONS = ["happy", "relaxed", "sad", "angry", "surprised", "aa", "ih", "ou", "ee", "oh", "blink"] as const;
type Expression = (typeof EXPRESSIONS)[number];
const VISEMES: readonly Expression[] = ["aa", "ih", "ou", "ee", "oh"];

function faceFor(portrait: string): Partial<Record<Expression, number>> {
  if (FACES[portrait]) return FACES[portrait];
  const category = emotionCategory(portrait);
  return (category && BY_CATEGORY[category]) || {};
}

const BONES = [
  "hips", "spine", "chest", "upperChest", "neck", "head", "leftShoulder", "rightShoulder",
  "leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm", "leftHand", "rightHand",
] as const;
type Bone = (typeof BONES)[number];

export function startVrm(corner: MikaCorner, store: MikaStore, url: string = vrmUrl()): void {
  const { canvas, stage, live } = corner;
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "low-power" });
  } catch (err) {
    console.warn("WebGL indisponible, le portrait reste :", err);
    return;
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(20, 1, 0.05, 20);
  const key = new THREE.DirectionalLight(0xffffff, Math.PI * 0.75);
  key.position.set(0.8, 1.6, 2.2);
  scene.add(key, new THREE.AmbientLight(0xffffff, 0.55));
  const gaze = new THREE.Object3D();
  scene.add(gaze);

  let vrm: VRM | null = null;
  let sign = 1;
  let headY = 1.35;
  const bones: Partial<Record<Bone, THREE.Object3D>> = {};
  const state = { portrait: "neutral", asleep: false, typing: false, talkUntil: 0, pointer: new THREE.Vector2(0, 0) };
  corner.onFace((face) => {
    state.portrait = face.portrait;
    state.asleep = face.asleep;
  });
  store.subscribe((snap) => {
    state.typing = snap.typing;
  });
  store.onTalk((ms) => {
    state.talkUntil = performance.now() + (ms || 1800);
  });

  live.hidden = false;
  live.textContent = "VRM…";

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  loader.load(
    url,
    (gltf) => {
      const loaded = gltf.userData.vrm as VRM | undefined;
      if (!loaded) {
        console.warn("Pas de VRM dans ce fichier, le portrait reste.");
        live.hidden = true;
        return;
      }
      vrm = loaded;
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      vrm.scene.traverse((o) => {
        o.frustumCulled = false;
      });
      const root = new THREE.Group();
      const vrm0 = vrm.meta?.metaVersion === "0";
      root.rotation.y = vrm0 ? Math.PI : 0; // un VRM 0.x regarde -Z : on le tourne vers la caméra
      sign = vrm0 ? -1 : 1; // les rotations s'écrivent en convention VRM 1.0
      root.add(vrm.scene);
      scene.add(root);
      for (const name of BONES) {
        const node = vrm.humanoid.getNormalizedBoneNode(name);
        if (node) bones[name] = node;
      }
      restPose();
      vrm.update(0);
      const p = new THREE.Vector3();
      bones.head?.getWorldPosition(p);
      headY = p.y || headY;
      if (vrm.lookAt) {
        vrm.lookAt.target = gaze;
        vrm.lookAt.autoUpdate = true;
      }
      frame();
      corner.vrmReady(true);
      live.textContent = "VRM";
      window.setTimeout(() => {
        live.hidden = true;
      }, 2500);
    },
    (ev) => {
      if (ev.total) live.textContent = `VRM ${Math.round((ev.loaded / ev.total) * 100)} %`;
    },
    (err) => {
      console.warn("VRM indisponible, le portrait reste :", err);
      live.hidden = true;
    },
  );

  function restPose(): void {
    // Les bras le long du corps (le repos d'un VRM est un T), les épaules un peu basses, les coudes à peine pliés.
    const z = (name: Bone, v: number) => {
      const b = bones[name];
      if (b) b.rotation.z = v * sign;
    };
    z("leftUpperArm", -1.2);
    z("rightUpperArm", 1.2);
    z("leftLowerArm", -0.12);
    z("rightLowerArm", 0.12);
    z("leftShoulder", 0.06);
    z("rightShoulder", -0.06);
    if (bones.leftHand) bones.leftHand.rotation.x = 0.1;
    if (bones.rightHand) bones.rightHand.rotation.x = 0.1;
  }

  /** Le buste dans la carte ; réduite, son visage seul dans le rond. */
  function frame(): void {
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const mini = corner.size === "mini";
    const visible = mini ? 0.2 : h > 380 ? 0.66 : 0.5; // hauteur vue, en mètres : son visage, ou son buste
    const d = visible / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)));
    const target = mini ? headY + 0.065 : headY - 0.04; // visage vers 36 % de la hauteur en carte
    camera.position.set(0, target + 0.01, d);
    camera.lookAt(0, target, 0);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(frame).observe(stage);
  corner.onSize(() => window.setTimeout(frame, 270));
  addEventListener("pointermove", (e) => {
    const r = stage.getBoundingClientRect();
    state.pointer.set(
      THREE.MathUtils.clamp(((e.clientX - (r.left + r.width / 2)) / innerWidth) * 2, -1, 1),
      THREE.MathUtils.clamp(((e.clientY - (r.top + r.height * 0.3)) / innerHeight) * 2, -1, 1),
    );
  });

  const current = Object.fromEntries(EXPRESSIONS.map((n) => [n, 0])) as Record<Expression, number>;
  let nextBlink = 2;
  let blink = -1;
  let viseme: Expression = "aa";
  let visemeChange = 0;

  const clock = new THREE.Clock();
  let accu = 0;
  function loop(): void {
    requestAnimationFrame(loop);
    const dt = Math.min(clock.getDelta(), 0.1);
    accu += dt;
    if (document.hidden || accu < 1 / 40) return; // 40 images/s au plus, rien quand l'onglet est caché
    if (!canvas.offsetParent && !corner.el.offsetParent) {
      accu = 0; // pas de dessin quand elle n'est pas affichée
      return;
    }
    const delta = accu;
    accu = 0;
    if (!vrm) return;
    const t = clock.elapsedTime;

    // Le souffle et la tête.
    const breath = Math.sin(t * 1.6);
    if (bones.chest) bones.chest.rotation.x = breath * 0.012;
    if (bones.spine) bones.spine.rotation.x = breath * 0.006;
    const bow = state.asleep ? 0.32 : state.typing ? 0.1 : 0;
    const followX = state.asleep ? 0 : state.pointer.x * 0.22;
    const followY = state.asleep ? 0 : state.pointer.y * 0.1;
    if (bones.neck) {
      bones.neck.rotation.y = followX * 0.4 * -sign + Math.sin(t * 0.31) * 0.03;
      bones.neck.rotation.x = (bow * 0.4 + followY * 0.4) * sign * -1;
    }
    if (bones.head) {
      bones.head.rotation.y = followX * 0.6 * -sign + Math.sin(t * 0.47) * 0.04;
      bones.head.rotation.x = (bow * 0.6 + followY * 0.6 + Math.sin(t * 0.23) * 0.02) * sign * -1;
      bones.head.rotation.z = Math.sin(t * 0.37) * 0.035 * sign;
    }
    gaze.position.set(state.pointer.x * 1.2, headY - state.pointer.y * 0.6 - (state.typing ? 0.5 : 0), 1.4);

    // Le visage : l'humeur, les clignements, la bouche quand elle parle.
    const target = Object.fromEntries(EXPRESSIONS.map((n) => [n, 0])) as Record<Expression, number>;
    Object.assign(target, faceFor(state.portrait));
    nextBlink -= delta;
    if (nextBlink <= 0 && blink < 0) {
      blink = 0;
      nextBlink = 2.4 + Math.random() * 3.5;
    }
    if (blink >= 0) {
      blink += delta;
      target.blink = Math.sin(Math.min(blink / 0.16, 1) * Math.PI);
      if (blink > 0.16) blink = -1;
    }
    if (state.asleep) target.blink = 1;
    if (performance.now() < state.talkUntil) {
      visemeChange -= delta;
      if (visemeChange <= 0) {
        viseme = VISEMES[Math.floor(Math.random() * VISEMES.length)];
        visemeChange = 0.08 + Math.random() * 0.07;
      }
      target[viseme] = 0.35 + Math.random() * 0.35;
    }
    const expressions = vrm.expressionManager;
    for (const n of EXPRESSIONS) {
      const speed = n === "blink" ? 1 : Math.min(1, delta * 10);
      current[n] += (target[n] - current[n]) * speed;
      if (expressions?.getExpression(n)) expressions.setValue(n, current[n]);
    }
    vrm.update(delta);
    renderer.render(scene, camera);
  }
  loop();
}
