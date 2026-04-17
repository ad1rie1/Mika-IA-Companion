import * as THREE from "three";
import { SceneManager } from "./scene/SceneManager";
import { Environment } from "./scene/Environment";
import { CameraController } from "./scene/CameraController";
import { VTuberModel } from "./vtuber/VTuberModel";
import {
  EmotionController,
  type EmotionName,
} from "./vtuber/EmotionController";
import { AnimationMixer } from "./vtuber/AnimationMixer";
import { GazeController } from "./vtuber/GazeController";
import { LipSyncController } from "./audio/LipSyncController";
import { TTSService } from "./audio/TTSService";
import { WebSocketClient } from "./network/WebSocketClient";
import { IdentityService } from "./network/IdentityService";
import { ChatOverlay } from "./ui/ChatOverlay";
import { EmotionDisplay } from "./ui/EmotionDisplay";
import { InnerLifePanel } from "./ui/InnerLifePanel";

// All valid backend emotion names for validation
const VALID_EMOTIONS = new Set<string>([
  "neutral",
  "happy", "excited", "love", "proud", "grateful",
  "playful", "amused", "hopeful", "relieved",
  "sad", "angry", "scared", "disgusted", "frustrated",
  "lonely", "anxious", "bored", "jealous",
  "surprised", "thinking", "confused", "embarrassed",
  "nostalgic", "dreamy", "determined", "mischievous",
  "curious", "melancholic",
]);

function wireIdentityBar(identity: IdentityService, ws: WebSocketClient) {
  const nameInput = document.getElementById("identity-name") as HTMLInputElement;
  const resetBtn = document.getElementById("identity-reset") as HTMLButtonElement;
  if (!nameInput || !resetBtn) return;

  if (identity.displayName) {
    nameInput.value = identity.displayName;
  }

  const commitName = () => {
    const value = nameInput.value.trim();
    if (value !== (identity.displayName ?? "")) {
      identity.setDisplayName(value);
      ws.setIdentity(identity.personId, identity.displayName);
      // Re-send identify so the backend picks up the new display name.
      ws.send({
        type: "identify",
        person_id: identity.personId,
        display_name: identity.displayName,
      });
    }
  };
  nameInput.addEventListener("blur", commitName);
  nameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      nameInput.blur();
    }
  });

  resetBtn.addEventListener("click", () => {
    if (!confirm("Réinitialiser ton identité ? Mika ne te reconnaîtra plus.")) return;
    identity.reset();
    ws.setIdentity(identity.personId, null);
    nameInput.value = "";
    // A reload is the cleanest way to restart the greeting flow with the new ID.
    window.location.reload();
  });
}

async function init() {
  const container = document.getElementById("app")!;
  const connectionStatus = document.getElementById("connection-status")!;

  // Scene setup
  const sceneManager = new SceneManager(container);
  const environment = new Environment(sceneManager.scene);
  const cameraController = new CameraController(
    sceneManager.camera,
    sceneManager.renderer.domElement
  );

  // VTuber model
  const vtuberModel = new VTuberModel(sceneManager.scene);
  const emotionController = new EmotionController();
  const animationMixer = new AnimationMixer();
  const gazeController = new GazeController();
  const lipSyncController = new LipSyncController();
  const emotionDisplay = new EmotionDisplay();
  const innerLifePanel = new InnerLifePanel();

  // Persistent identity — loaded from localStorage, survives reloads +
  // WebSocket reconnects. This is what makes the theory-of-mind layer
  // (PersonProfile / Commitment / per-person emotional memory) actually
  // work across sessions on the web.
  const identity = new IdentityService();

  // Try loading VRM model
  try {
    const vrm = await vtuberModel.load("/models/default.vrm");
    emotionController.setVRM(vrm);
    animationMixer.setVRM(vrm);
    gazeController.setVRM(vrm);
    lipSyncController.setVRM(vrm);
    console.log("VTuber model ready");
  } catch (e) {
    console.warn(
      "No VRM model found at /models/default.vrm - running without model.",
      "Place a .vrm file in frontend/public/models/default.vrm"
    );
    createPlaceholder(sceneManager);
  }

  // TTS with lip-sync integration
  const tts = new TTSService({
    onSpeakStart: () => {
      animationMixer.setSpeaking(true);
    },
    onSpeakEnd: () => {
      animationMixer.setSpeaking(false);
      lipSyncController.stop();
    },
    onAudioData: (analyser) => {
      lipSyncController.startAudioDriven(analyser);
    },
  });

  // WebSocket connection with identity handshake
  const ws = new WebSocketClient();
  ws.setIdentity(identity.personId, identity.displayName);
  const chatOverlay = new ChatOverlay(ws);
  wireIdentityBar(identity, ws);

  ws.on("connection", (data) => {
    if (data.status === "connected") {
      connectionStatus.className = "connected";
      connectionStatus.textContent = "Connected";
    } else {
      connectionStatus.className = "disconnected";
      connectionStatus.textContent = "Disconnected";
    }
  });

  // Sleep phase plumbing. The InnerLifePanel extracts the phase from
  // every inner_state payload; we fan it out to the animation mixer
  // (avatar dozes) and the environment (lights dim). We also stamp
  // `lastAsleepAt` every tick while asleep so the TTS can insert a
  // wake-up pause on the first reply after waking — no matter whether
  // the speech payload carries an already-awake phase or not.
  let lastAsleepAt: number | null = null;
  innerLifePanel.onSleepPhaseChange((phase) => {
    animationMixer.setSleepPhase(phase);
    environment.setSleepPhase(phase);
    gazeController.setSleepPhase(phase);
    // Sleep owns the neck bone. When asleep, stop applying emotion-
    // driven head pose to avoid layered conflicts (curious tilt +
    // sleep forward tilt = broken geometry).
    emotionController.setSuppressHeadPose(phase !== "awake");
    if (phase !== "awake") {
      lastAsleepAt = performance.now();
    }
  });

  const handleSpeech = (data: any) => {
    // Validate emotion from backend
    const rawEmotion = data.emotion as string;
    const emotion: EmotionName = VALID_EMOTIONS.has(rawEmotion)
      ? (rawEmotion as EmotionName)
      : "neutral";
    const intensity: number =
      typeof data.emotion_intensity === "number"
        ? data.emotion_intensity
        : 0.7;

    // Facial expression + gaze direction
    emotionController.setEmotion(emotion, intensity);
    gazeController.setEmotion(emotion, intensity);
    emotionDisplay.setEmotion(emotion, intensity);

    // Ambivalence panel + rest of inner state
    innerLifePanel.setEmotionBlend(data.emotion_blend || [], intensity);
    innerLifePanel.applyInnerState(data.inner_state);

    // Wake-up pause: if Mika was asleep within the last 10s (either
    // she's still marked asleep OR she just transitioned awake in the
    // same payload), prefix the TTS with ~1.3s of silence so she
    // sounds like she's surfacing from sleep. Fires once per wake.
    if (
      lastAsleepAt !== null &&
      performance.now() - lastAsleepAt < 10000
    ) {
      tts.requestWakeUpDelay(1300);
      lastAsleepAt = null;
    }

    // Speak
    const estimatedDuration = Math.min(data.text.length * 60, 15000);
    lipSyncController.startTextDriven(data.text, estimatedDuration);
    tts.speak(data.text, emotion);
  };

  ws.on("speech", handleSpeech);

  // Pure state refresh — no speech, no lip-sync, just inner_state.
  // Emitted by the backend when Mika's sleep phase transitions during
  // the night without any conversation turn happening.
  ws.on("inner_state_update", (data: any) => {
    innerLifePanel.applyInnerState(data.inner_state);
  });

  // Project reports — silent by default (no TTS). Show as a message
  // in the chat overlay so the user sees what Mika wrapped up. Prefixed
  // to distinguish from regular conversation.
  ws.on("project_report", (data: any) => {
    try {
      chatOverlay.addMessage(
        `[Projet · ${data.project_title}] ${data.text}`,
        "vtuber",
      );
    } catch {
      console.log(`[project_report ${data.project_title}] ${data.text}`);
    }
  });

  ws.connect();

  // Update loop
  sceneManager.onUpdate((delta) => {
    cameraController.update();
    vtuberModel.update(delta);
    emotionController.update(delta);
    animationMixer.update(delta);
    // Gaze runs after the mixer so the eye bone rotations aren't
    // overwritten by any higher-level pose logic further up.
    gazeController.update(delta);
    lipSyncController.update(delta);
    environment.update(delta);
  });
}

function createPlaceholder(sceneManager: SceneManager) {
  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.2, 0.6, 8, 16),
    new THREE.MeshStandardMaterial({ color: 0x6366f1 })
  );
  body.position.set(0, 0.9, -0.5);
  body.castShadow = true;
  sceneManager.scene.add(body);

  const head = new THREE.Mesh(
    new THREE.SphereGeometry(0.18, 16, 16),
    new THREE.MeshStandardMaterial({ color: 0xffd5b4 })
  );
  head.position.set(0, 1.5, -0.5);
  head.castShadow = true;
  sceneManager.scene.add(head);
}

init().catch(console.error);
