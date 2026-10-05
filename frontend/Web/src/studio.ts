import * as THREE from "three";
import { SceneManager } from "./scene/SceneManager";
import { Environment } from "./scene/Environment";
import { CameraController } from "./scene/CameraController";
import { VTuberModel } from "./vtuber/VTuberModel";
import { EmotionController } from "./vtuber/EmotionController";
import { AnimationSystem } from "./vtuber/animation/AnimationSystem";
import { LipSyncController, msPerCharForRate } from "./audio/LipSyncController";
import { TTSService } from "./audio/TTSService";
import { SpeechPresenter } from "./ui/SpeechPresenter";
import { articulationFor } from "./vtuber/animation/affect";
import { PLACE_IDS } from "./vtuber/locomotion/roomLayout";
import {
  EMOTION_NAMES,
  isEmotionName,
  type EmotionBlend,
  type EmotionName,
  type SleepPhase,
} from "./types";

/**
 * Studio — a dev-only stage for Mika, no backend, no login.
 *
 * Wires the exact same objects as main.ts (scene, room, model, face, body,
 * lip-sync, voice, presenter) and replaces the WebSocket with a panel:
 * play an emotion as a reply or as drift, speak a line (with the real
 * voice, or simulated so the body and mouth run without audio), force a
 * sleep phase, fire any gesture, frame the camera. Served by `npm run dev`
 * at /studio.html; not part of the production build.
 *
 * `window.studio` exposes the same handles for console scripting.
 */

const SLEEP_PHASES: SleepPhase[] = ["awake", "light_sleep", "rem", "deep_sleep"];

async function boot() {
  const container = document.getElementById("app")!;
  const sceneManager = new SceneManager(container);
  const environment = new Environment(sceneManager.scene);
  // The desk chair is hers to pull out: once the room is in (GLB or the
  // procedural fallback, both name it), the locomotion moves it.
  void environment.ready.then(() =>
    animationSystem.setPlaceProp("desk", environment.group.getObjectByName("DeskChair") ?? null)
  );
  const cameraController = new CameraController(
    sceneManager.camera,
    sceneManager.renderer.domElement
  );
  const vtuberModel = new VTuberModel(sceneManager.scene);
  const emotionController = new EmotionController();
  const animationSystem = new AnimationSystem();
  const lipSync = new LipSyncController();

  const tts = new TTSService({
    onSpeakStart: () => presenter.handleSpeakStart(),
    onSpeakEnd: () => {
      lipSync.stop();
      presenter.handleSpeakEnd();
    },
    onProsodicCue: (cue) => animationSystem.playCue(cue),
    onUtteranceStart: (text, rate) => {
      const msPerChar = msPerCharForRate(rate);
      lipSync.startFromPlan(tts.lipSyncPlan(text), msPerChar);
      animationSystem.beginUtterance(text, msPerChar);
    },
    onUtteranceEnd: () => lipSync.stop(),
    onSpeechProgress: (charIndex) => lipSync.seekToChar(charIndex),
  });
  const face = {
    setEmotion: (emotion: EmotionName, intensity: number, blend?: EmotionBlend) => {
      emotionController.setEmotion(emotion, intensity, blend);
      lipSync.setArticulation(articulationFor(emotion, intensity));
    },
    setEnergy: (energy: number) => emotionController.setEnergy(energy),
  };
  const presenter = new SpeechPresenter({
    voice: tts,
    face,
    body: animationSystem,
    stage: environment,
    readouts: {
      setEmotion: () => {},
      setEmotionBlend: () => {},
      applyInnerState: () => {},
    },
  });

  // No backend here: she starts on the rug, so the first button walks.
  animationSystem.setPlace("center", { instant: true });
  void vtuberModel.load("/models/default.vrm").then((vrm) => {
    emotionController.setVRM(vrm);
    lipSync.setVRM(vrm);
    const root = vtuberModel.getRoot();
    const head = vrm.humanoid?.getRawBoneNode("head");
    if (head) cameraController.setFollowTarget(head, new THREE.Vector3(0, 0.05, 0));
    else if (root) cameraController.setFollowTarget(root);
    void animationSystem
      .init(vrm, { root, camera: sceneManager.camera })
      .then(() => fillGestures())
      .catch((e) => console.warn("AnimationSystem init failed:", e));
  });

  sceneManager.onUpdate((delta) => {
    cameraController.update(delta);
    emotionController.update(delta);
    animationSystem.setSpeechCursor(lipSync.currentCharOffset);
    animationSystem.update(delta);
    lipSync.update(delta);
    environment.update(delta);
    vtuberModel.update(delta);
  });

  // ── Panel ───────────────────────────────────────────────────────────
  const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const emo = $<HTMLSelectElement>("emo");
  const emo2 = $<HTMLSelectElement>("emo2");
  for (const name of EMOTION_NAMES) {
    emo.add(new Option(name, name));
    emo2.add(new Option(name, name));
  }
  emo.value = "happy";

  const readEmotion = (): { emotion: EmotionName; intensity: number; blend: EmotionBlend } => {
    const emotion = isEmotionName(emo.value) ? emo.value : "neutral";
    const intensity = Number($<HTMLInputElement>("emo-int").value);
    const blend: EmotionBlend = [{ emotion, weight: 1 }];
    if (isEmotionName(emo2.value)) {
      blend.push({ emotion: emo2.value, weight: Number($<HTMLInputElement>("emo2-w").value) });
    }
    return { emotion, intensity, blend };
  };

  const showEmotion = (ambient: boolean) => {
    const { emotion, intensity, blend } = readEmotion();
    if (ambient) {
      presenter.handleEmotionUpdate({
        type: "emotion_update",
        emotion,
        emotion_intensity: intensity,
        emotion_blend: blend,
      } as Parameters<SpeechPresenter["handleEmotionUpdate"]>[0]);
    } else {
      presenter.showEmotion(emotion, intensity, blend);
    }
  };
  $("emo-reply").onclick = () => showEmotion(false);
  $("emo-drift").onclick = () => showEmotion(true);

  // Simulated speech: the body and the mouth run exactly as they would
  // behind a real voice (same plan, same cursor), with no audio at all —
  // what headless browsers and muted sessions need.
  let simTimer: number | null = null;
  const simulate = (text: string) => {
    const { emotion, intensity, blend } = readEmotion();
    presenter.showEmotion(emotion, intensity, blend);
    const rate = tts.effectiveRate(emotion, undefined, intensity);
    const msPerChar = msPerCharForRate(rate);
    const plan = tts.lipSyncPlan(text);
    const ms = plan.reduce(
      (sum, seg) =>
        sum + (seg.type === "silence" ? seg.ms : seg.text.replace(/\s+/g, " ").length * msPerChar),
      0
    );
    if (simTimer !== null) window.clearTimeout(simTimer);
    lipSync.startFromPlan(plan, msPerChar);
    animationSystem.beginUtterance(text, msPerChar);
    animationSystem.setSpeaking(true);
    simTimer = window.setTimeout(() => {
      simTimer = null;
      lipSync.stop();
      animationSystem.setSpeaking(false);
    }, ms);
  };
  $("say-sim").onclick = () => simulate($<HTMLTextAreaElement>("say").value);
  $("say-voice").onclick = () => {
    const { emotion, intensity, blend } = readEmotion();
    presenter.handleSpeech({
      type: "speech",
      text: $<HTMLTextAreaElement>("say").value,
      emotion,
      emotion_intensity: intensity,
      emotion_blend: blend,
      speak: true,
    });
  };
  $("say-stop").onclick = () => {
    tts.stop();
    lipSync.stop();
    if (simTimer !== null) window.clearTimeout(simTimer);
    simTimer = null;
    animationSystem.setSpeaking(false);
  };

  let pending = false;
  $("pending").onclick = () => {
    pending = !pending;
    animationSystem.setReplyPending(pending);
    $("pending").textContent = pending ? "Réfléchit ✓" : "Réfléchit";
  };
  $("typing").onclick = () => presenter.noteUserTyping();

  const sleepRow = $("sleep-row");
  for (const phase of SLEEP_PHASES) {
    const b = document.createElement("button");
    b.textContent = phase;
    b.onclick = () => presenter.setSleepPhase(phase);
    sleepRow.appendChild(b);
  }

  const placeRow = $("place-row");
  for (const place of PLACE_IDS) {
    const b = document.createElement("button");
    b.textContent = place;
    b.onclick = () => animationSystem.setPlace(place);
    placeRow.appendChild(b);
  }

  const fillGestures = () => {
    const row = $("gesture-row");
    row.textContent = "";
    for (const name of animationSystem.listClips().filter((n) => n.startsWith("gesture") && !n.endsWith("~m"))) {
      const b = document.createElement("button");
      b.textContent = name.replace(/^gesture_/, "");
      b.onclick = () => animationSystem.playGesture(name);
      row.appendChild(b);
    }
  };

  // Camera framings: the orbit pivot moves with the framing so a close-up
  // still orbits around her face, not her chest.
  const FRAMES: Record<string, { pivotY: number; offset: THREE.Vector3; min: number }> = {
    // Her eyes sit at ~1.16 m (measured on the head/eye bones).
    face: { pivotY: 1.14, offset: new THREE.Vector3(0, 0.01, 0.42), min: 0.25 },
    bust: { pivotY: 1.02, offset: new THREE.Vector3(0, 0.04, 0.95), min: 0.4 },
    body: { pivotY: 0.7, offset: new THREE.Vector3(0, 0.15, 2.3), min: 1.1 },
    room: { pivotY: 1.0, offset: new THREE.Vector3(1.6, 0.8, 2.6), min: 1.1 },
  };
  const frame = (name: string) => {
    const f = FRAMES[name];
    const root = vtuberModel.getRoot();
    if (!f || !root) return;
    cameraController.setFollowTarget(root, new THREE.Vector3(0, f.pivotY, 0));
    cameraController.controls.minDistance = f.min;
    cameraController.controls.maxDistance = Math.max(3.4, f.offset.length() + 0.2);
    const pivot = root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, f.pivotY, 0));
    sceneManager.camera.position.copy(pivot).add(f.offset);
  };
  document.querySelectorAll<HTMLButtonElement>("[data-cam]").forEach((b) => {
    b.onclick = () => frame(b.dataset.cam!);
  });

  const state = $("studio-state");
  window.setInterval(() => {
    const s = animationSystem.getDebugState();
    state.textContent =
      `état ${s.state}  clip ${s.clip ?? "—"}\n` +
      `émotion ${s.emotion} ${s.intensity.toFixed(2)}  tempo ${s.tempo.toFixed(2)}\n` +
      `attention ${s.attention}  clips ${s.clipCount}\n` +
      `lieu ${animationSystem.place.place ?? "—"}  posture ${animationSystem.place.posture}` +
      (animationSystem.place.moving ? "  (en route)" : "");
  }, 250);

  (window as unknown as { studio: unknown }).studio = {
    THREE,
    sceneManager,
    environment,
    cameraController,
    vtuberModel,
    emotionController,
    animationSystem,
    lipSync,
    tts,
    presenter,
    simulate,
    frame,
  };
}

boot().catch(console.error);
