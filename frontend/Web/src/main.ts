import * as THREE from "three";
import { SceneManager } from "./scene/SceneManager";
import { Environment } from "./scene/Environment";
import { CameraController } from "./scene/CameraController";
import { VTuberModel } from "./vtuber/VTuberModel";
import { EmotionController } from "./vtuber/EmotionController";
import { AnimationSystem } from "./vtuber/animation/AnimationSystem";
import { AnimationDebugger } from "./vtuber/animation/AnimationDebugger";
import { LipSyncController, msPerCharForRate } from "./audio/LipSyncController";
import { TTSService } from "./audio/TTSService";
import { WebSocketClient } from "./network/WebSocketClient";
import { IdentityService } from "./network/IdentityService";
import { ChatOverlay } from "./ui/ChatOverlay";
import { EmotionDisplay } from "./ui/EmotionDisplay";
import { InnerLifePanel } from "./ui/InnerLifePanel";
import { LoginOverlay } from "./ui/LoginOverlay";
import { SpeechPresenter } from "./ui/SpeechPresenter";
import { WS_URL } from "./network/api";
import { articulationFor } from "./vtuber/animation/affect";
import type { EmotionBlend, EmotionName } from "./types";

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

// Connection badge: green "Connectée" that fades out after a few seconds,
// amber spinner while a reconnect attempt is in flight, red with the retry
// countdown otherwise.
function wireConnectionBadge(ws: WebSocketClient, connectionStatus: HTMLElement) {
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
}

async function init() {
  const container = document.getElementById("app")!;
  const connectionStatus = document.getElementById("connection-status")!;

  // Scene setup
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

  // Try loading VRM model — deliberately NOT awaited, for the same reason
  // the Mixamo clips aren't: it's the heaviest asset of the two (tens of
  // MB to download AND parse), and nothing downstream of it depends on it.
  // Awaiting here kept the page blank — no login form, no chat, no socket,
  // so no history catch-up either — for the whole download. Every consumer
  // already handles "not loaded yet", so the avatar simply shows up when
  // it's ready.
  void vtuberModel
    .load("/models/default.vrm")
    .then((vrm) => {
      emotionController.setVRM(vrm);
      lipSyncController.setVRM(vrm);
      const root = vtuberModel.getRoot();
      // The pivot rides her head (eye level), wherever she walks, sits or
      // lies; the camera is carried along at the angle the user chose.
      const head = vrm.humanoid?.getRawBoneNode("head");
      if (head) cameraController.setFollowTarget(head, new THREE.Vector3(0, 0.05, 0));
      else if (root) cameraController.setFollowTarget(root);
      // Starts animating synchronously on the rest pose, then streams the
      // Mixamo clips in — not awaited so the app boots without waiting for
      // FBX downloads.
      // The camera is the viewer: her eyes and head keep contact with it,
      // with the gaze aversions of a real conversation (see attention.ts).
      void animationSystem
        .init(vrm, { root, camera: sceneManager.camera })
        .catch((e) => console.warn("AnimationSystem init failed:", e));
      console.log("VTuber model ready");
    })
    .catch(() => {
      console.warn(
        "No VRM model found at /models/default.vrm - running without model.",
        "Place a .vrm file in frontend/Web/public/models/default.vrm"
      );
      createPlaceholder(sceneManager);
    });

  // What the voice says, the face shows — at the moment it sounds. The
  // presenter holds every bit of voice/drift/sleep state (see
  // SpeechPresenter.ts); main.ts only wires frames and events into it.
  // `presenter` is read inside callbacks the TTS fires later, so declaring
  // it after the TTS it depends on is fine.
  const tts = new TTSService({
    onSpeakStart: () => presenter.handleSpeakStart(),
    onSpeakEnd: () => {
      lipSyncController.stop();
      presenter.handleSpeakEnd();
    },
    // [SIGH]/[LAUGH] tokens fire a body beat in sync with their audio.
    onProsodicCue: (cue) => {
      animationSystem.playCue(cue);
    },
    // Le plan de lip-sync doit suivre l'énoncé qui commence réellement à
    // jouer, pas celui qu'on vient de mettre en file : deux répliques
    // rapprochées faisaient sinon articuler la bouche sur le texte suivant
    // pendant que l'audio du précédent tournait encore.
    onUtteranceStart: (text, rate) => {
      const msPerChar = msPerCharForRate(rate);
      lipSyncController.startFromPlan(tts.lipSyncPlan(text), msPerChar);
      // The head and brows punctuate the same text, fired as the lip-sync
      // cursor reaches each beat (see animation/speechBeats.ts).
      animationSystem.beginUtterance(text, msPerChar);
    },
    // La synthèse dit où en est la voix (début réel, puis chaque mot là où
    // le navigateur le donne) : la bouche s'y recale au lieu de courir sur
    // une estimation qui finissait avant ou après l'audio.
    onSpeechProgress: (charIndex) => {
      lipSyncController.seekToChar(charIndex);
    },
  });
  // The face port also sets how wide the mouth articulates: it follows the
  // reply's emotion at the moment the voice starts, like the expression.
  let fatigue = 0;
  const face = {
    setEmotion: (emotion: EmotionName, intensity: number, blend?: EmotionBlend) => {
      emotionController.setEmotion(emotion, intensity, blend);
      lipSyncController.setArticulation(articulationFor(emotion, intensity, fatigue));
    },
    setEnergy: (energy: number) => {
      fatigue = Math.max(0, Math.min(1, (0.55 - energy) / 0.4));
      emotionController.setEnergy(energy);
    },
  };
  const presenter = new SpeechPresenter({
    voice: tts,
    face,
    body: animationSystem,
    stage: environment,
    readouts: {
      setEmotion: (emotion, intensity) => emotionDisplay.setEmotion(emotion, intensity),
      setEmotionBlend: (blend, intensity) => innerLifePanel.setEmotionBlend(blend, intensity),
      applyInnerState: (state) => innerLifePanel.applyInnerState(state),
    },
  });
  // The InnerLifePanel extracts the phase from every inner_state payload
  // and fans it out here (animation + environment + wake-up stamp).
  innerLifePanel.onSleepPhaseChange((phase) => presenter.setSleepPhase(phase));

  // Auth: the WebSocket authenticates via the server's session cookie.
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
  const effectivePersonId = auth.authenticated
    ? auth.person_id ?? identity.personId
    : identity.personId;
  ws.setIdentity(
    effectivePersonId,
    auth.authenticated
      ? auth.display_name ?? auth.username ?? identity.displayName
      : identity.displayName
  );
  // The cached thread is scoped to that id. Without it, resetting the
  // identity — or a second account on the same browser — kept the previous
  // person's conversation on screen under a new name.
  const chatOverlay = new ChatOverlay(ws, effectivePersonId);
  // Approving a project action needs an operator account (the server answers
  // 403 otherwise). With auth disabled server-side nothing is gated.
  innerLifePanel.setCanApprove(!auth.authenticated || auth.operator === true);
  // The identity bar lets an anonymous visitor pick a name. Authenticated
  // users have one already, and letting them edit it here would suggest they
  // can change who Mika thinks they are — which is exactly what the session
  // is there to settle.
  if (!auth.authenticated) {
    wireIdentityBar(identity, ws);
  } else {
    document.getElementById("identity-bar")?.style.setProperty("display", "none");
  }

  wireConnectionBadge(ws, connectionStatus);

  ws.on("speech", (data) => presenter.handleSpeech(data));
  ws.on("inner_state_update", (data) => presenter.handleInnerStateUpdate(data));
  ws.on("emotion_update", (data) => presenter.handleEmotionUpdate(data));
  ws.on("ack", (data) => presenter.handleAck(data));
  // Pas de trame `project_report` : le serveur v2 n'en émet pas. Ce qu'elle
  // raconte d'un projet arrive comme une parole (`speech`), dans le fil.

  ws.connect();

  // Manual QA hooks: Alt+M cycles every loaded clip on the live model
  // (the only reliable retarget check on this rig), Alt+K skeleton,
  // Alt+S/E/T/G force sleep/emotions/talking/gestures, Alt+D panel.
  new AnimationDebugger({
    system: animationSystem,
    scene: sceneManager.scene,
    // Read when the skeleton helper is toggled, not here: the VRM loads in
    // the background and is usually still missing at this point.
    get avatarScene() {
      return vtuberModel.vrm?.scene ?? null;
    },
    applySleepPhase: (phase) => presenter.setSleepPhase(phase),
    applyEmotion: (emotion, intensity) => presenter.showEmotion(emotion, intensity),
  });

  // Typing anywhere (outside another field) focuses the chat input, so you
  // can just start writing without clicking the box first.
  const chatInput = document.getElementById("chat-input") as HTMLTextAreaElement | null;
  // Someone typing to her is someone to listen to: eyes on them.
  chatInput?.addEventListener("input", () => presenter.noteUserTyping());
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
    // The voice's position in the reply (one frame old — nothing reads it
    // at that precision) drives the speech beats.
    animationSystem.setSpeechCursor(lipSyncController.currentCharOffset);
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
