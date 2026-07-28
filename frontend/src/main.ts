import * as THREE from "three";
import { SceneManager } from "./scene/SceneManager";
import { Environment } from "./scene/Environment";
import { CameraController } from "./scene/CameraController";
import { VTuberModel } from "./vtuber/VTuberModel";
import { EmotionController } from "./vtuber/EmotionController";
import { AnimationSystem } from "./vtuber/animation/AnimationSystem";
import { AnimationDebugger } from "./vtuber/animation/AnimationDebugger";
import { LipSyncController } from "./audio/LipSyncController";
import { TTSService } from "./audio/TTSService";
import { WebSocketClient } from "./network/WebSocketClient";
import { IdentityService } from "./network/IdentityService";
import { ChatOverlay } from "./ui/ChatOverlay";
import { EmotionDisplay } from "./ui/EmotionDisplay";
import { InnerLifePanel } from "./ui/InnerLifePanel";
import { LoginOverlay } from "./ui/LoginOverlay";
import { WS_URL } from "./network/api";
import {
  isEmotionName,
  type EmotionName,
  type SleepPhase,
  type SpeechMessage,
} from "./types";

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

  // VTuber model + the whole body-animation stack (clips, state machine,
  // overlays, hands, gaze, blink) behind one facade.
  const vtuberModel = new VTuberModel(sceneManager.scene);
  const emotionController = new EmotionController();
  const animationSystem = new AnimationSystem();
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
    lipSyncController.setVRM(vrm);
    const root = vtuberModel.getRoot();
    if (root) cameraController.setFollowTarget(root);
    // Starts animating synchronously on the rest pose, then streams the
    // Mixamo clips in — not awaited so the app boots without waiting for
    // FBX downloads.
    void animationSystem
      .init(vrm, { root })
      .catch((e) => console.warn("AnimationSystem init failed:", e));
    console.log("VTuber model ready");
  } catch (e) {
    console.warn(
      "No VRM model found at /models/default.vrm - running without model.",
      "Place a .vrm file in frontend/public/models/default.vrm"
    );
    createPlaceholder(sceneManager);
  }

  // TTS with lip-sync + body-animation integration
  const tts = new TTSService({
    onSpeakStart: () => {
      animationSystem.setSpeaking(true);
    },
    onSpeakEnd: () => {
      animationSystem.setSpeaking(false);
      lipSyncController.stop();
    },
    onAudioData: (analyser) => {
      lipSyncController.startAudioDriven(analyser);
    },
    // [SIGH]/[LAUGH] tokens fire a body beat in sync with their audio.
    onProsodicCue: (cue) => {
      animationSystem.playCue(cue);
    },
  });

  // Auth: the WebSocket authenticates via the Django session cookie.
  //
  // The gate is driven by the *backend* (`auth_required` in /auth/whoami)
  // rather than a build-time flag, so the frontend can't be configured into
  // disagreeing with the server about whether a session is needed — that
  // combination produced a login-free UI whose WebSocket was then refused.
  // When no account exists yet the overlay switches to creating the first one.
  const auth = await new LoginOverlay().ensureAuthenticated();

  // WebSocket connection with identity handshake
  // Voice mute toggle — persisted so a muted session stays muted on reload.
  const muteBtn = document.getElementById("tts-mute");
  if (muteBtn) {
    const applyMuteUI = () => {
      muteBtn.textContent = tts.isMuted ? "🔇" : "🔊";
      muteBtn.classList.toggle("muted", tts.isMuted);
    };
    tts.setMuted(localStorage.getItem("vtuber_tts_muted") === "1");
    applyMuteUI();
    muteBtn.addEventListener("click", () => {
      tts.setMuted(!tts.isMuted);
      localStorage.setItem("vtuber_tts_muted", tts.isMuted ? "1" : "0");
      applyMuteUI();
    });
  }

  const ws = new WebSocketClient(WS_URL);
  // The server-issued id wins when authenticated: the consumer binds the
  // connection to user_{pk} and ignores any client claim, so sending the
  // locally generated web_* one would just describe an identity that the
  // backend already overrode.
  ws.setIdentity(
    auth.authenticated ? auth.person_id ?? identity.personId : identity.personId,
    auth.authenticated
      ? auth.display_name ?? auth.username ?? identity.displayName
      : identity.displayName
  );
  const chatOverlay = new ChatOverlay(ws);
  // The identity bar lets an anonymous visitor pick a name. Authenticated
  // users have one already, and letting them edit it here would suggest they
  // can change who Mika thinks they are — which is exactly what the session
  // is there to settle.
  if (!auth.authenticated) {
    wireIdentityBar(identity, ws);
  } else {
    document.getElementById("identity-bar")?.style.setProperty("display", "none");
  }

  // Connection badge: green "Connectée" that fades out after a few seconds,
  // amber spinner while a reconnect attempt is in flight, red with the retry
  // countdown otherwise.
  let settleTimer: number | null = null;
  ws.on("connection", (data) => {
    if (settleTimer !== null) {
      window.clearTimeout(settleTimer);
      settleTimer = null;
    }
    if (data.status === "unauthorized") {
      // Terminal: the client stopped retrying on purpose. Say what to do
      // instead of leaving a spinner turning forever.
      connectionStatus.className = "disconnected";
      connectionStatus.textContent = "Session expirée — reconnecte-toi";
      connectionStatus.onclick = () => window.location.reload();
      connectionStatus.style.cursor = "pointer";
      connectionStatus.title = "Cliquer pour se reconnecter";
      return;
    }
    if (data.status === "connected") {
      connectionStatus.className = "connected";
      connectionStatus.textContent = "Connectée";
      settleTimer = window.setTimeout(() => {
        connectionStatus.classList.add("settled");
      }, 3000);
    } else if (data.status === "reconnecting") {
      connectionStatus.className = "reconnecting";
      connectionStatus.textContent = "Reconnexion…";
    } else {
      connectionStatus.className = "disconnected";
      const retry = typeof data.retryInMs === "number"
        ? ` (réessai dans ${Math.round(data.retryInMs / 1000)}s)`
        : "";
      connectionStatus.textContent = `Déconnectée${retry}`;
    }
  });

  // Sleep phase plumbing. The InnerLifePanel extracts the phase from
  // every inner_state payload; the fan-out collapsed to two calls with
  // the animation rewrite (AnimationSystem forwards to the state
  // machine, overlays, blink, gaze and hands internally). We also stamp
  // `lastAsleepAt` while asleep so the TTS can insert a wake-up pause
  // on the first reply after waking.
  let lastAsleepAt: number | null = null;
  const applySleepPhase = (phase: SleepPhase) => {
    animationSystem.setSleepPhase(phase);
    environment.setSleepPhase(phase);
    if (phase !== "awake") {
      lastAsleepAt = performance.now();
    }
  };
  innerLifePanel.onSleepPhaseChange(applySleepPhase);

  const applyEmotion = (
    emotion: EmotionName,
    intensity: number,
    blend: SpeechMessage["emotion_blend"] = [],
    persona?: SpeechMessage["voice_persona"]
  ) => {
    emotionController.setEmotion(emotion, intensity);
    animationSystem.setEmotion(emotion, intensity, blend ?? [], persona);
    emotionDisplay.setEmotion(emotion, intensity);
  };

  const handleSpeech = (data: SpeechMessage) => {
    // Validate emotion from backend
    const emotion: EmotionName = isEmotionName(data.emotion)
      ? data.emotion
      : "neutral";
    const intensity: number =
      typeof data.emotion_intensity === "number"
        ? data.emotion_intensity
        : 0.7;

    // Face + body + UI
    applyEmotion(emotion, intensity, data.emotion_blend, data.voice_persona);

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

    // Speak — the backend decides whether this turn is voiced at all, and
    // in which voice (see backend/pipeline/voice.py). `speak: false` still
    // shows the text and animates the avatar; it just stays silent.
    if (data.speak === false || typeof data.text !== "string" || !data.text) {
      return;
    }
    const estimatedDuration = Math.min(data.text.length * 60, 15000);
    lipSyncController.startTextDriven(data.text, estimatedDuration);
    tts.speak(data.text, emotion, data.voice_profile);
  };

  ws.on("speech", handleSpeech);

  // Pure state refresh — no speech, no lip-sync, just inner_state.
  // Emitted by the backend when Mika's sleep phase transitions during
  // the night without any conversation turn happening.
  ws.on("inner_state_update", (data) => {
    innerLifePanel.applyInnerState(data.inner_state);
  });

  // Project reports — silent by default (no TTS). Show as a message
  // in the chat overlay so the user sees what Mika wrapped up. Prefixed
  // to distinguish from regular conversation.
  ws.on("project_report", (data) => {
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

  // Manual QA hooks: Alt+M cycles every loaded clip on the live model
  // (the only reliable retarget check on this rig), Alt+K skeleton,
  // Alt+S/E/T/G force sleep/emotions/talking/gestures, Alt+D panel.
  new AnimationDebugger({
    system: animationSystem,
    scene: sceneManager.scene,
    avatarScene: vtuberModel.vrm?.scene ?? null,
    applySleepPhase,
    applyEmotion: (emotion, intensity) => applyEmotion(emotion, intensity),
  });

  // Typing anywhere (outside another field) focuses the chat input, so you
  // can just start writing without clicking the box first.
  const chatInput = document.getElementById("chat-input") as HTMLTextAreaElement | null;
  document.addEventListener("keydown", (e) => {
    if (!chatInput) return;
    const target = e.target as HTMLElement;
    const inField =
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target.isContentEditable;
    if (inField || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key.length === 1 || e.key === "Enter") {
      chatInput.focus();
    }
  });

  // Update loop
  sceneManager.onUpdate((delta) => {
    cameraController.update(delta);
    emotionController.update(delta);
    // Owns every bone writer, in order: resetNormalizedPose → state
    // machine → clip mixer → additive overlays → hands → gaze → blink.
    animationSystem.update(delta);
    lipSyncController.update(delta);
    environment.update(delta);
    // vrm.update() applies expression weights and copies normalized bones to
    // raw ones — it must run AFTER every controller has written this frame's
    // pose. Calling it first made every expression and rotation land one
    // frame late, which is a ~25% timing error on a 4-frame blink at 30fps.
    vtuberModel.update(delta);
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
