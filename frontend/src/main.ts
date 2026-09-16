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
      if (root) cameraController.setFollowTarget(root);
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
        "Place a .vrm file in frontend/public/models/default.vrm"
      );
      createPlaceholder(sceneManager);
    });

  // What the avatar shows: face, body, gaze, hands.
  const applyAvatarEmotion = (
    emotion: EmotionName,
    intensity: number,
    blend: SpeechMessage["emotion_blend"] = [],
    persona?: SpeechMessage["voice_persona"],
    opts: { ambient?: boolean } = {}
  ) => {
    emotionController.setEmotion(emotion, intensity);
    animationSystem.setEmotion(emotion, intensity, blend ?? [], persona, opts);
  };

  // Avatar + the readout, at once — the debug hooks and silent replies.
  const applyEmotion = (
    emotion: EmotionName,
    intensity: number,
    blend: SpeechMessage["emotion_blend"] = [],
    persona?: SpeechMessage["voice_persona"],
    opts: { ambient?: boolean } = {}
  ) => {
    applyAvatarEmotion(emotion, intensity, blend, persona, opts);
    emotionDisplay.setEmotion(emotion, intensity);
  };

  // Une réplique vocale possède le visage tant qu'elle sonne. Ce que le
  // backend pousse entre-temps (`emotion_update`, la dérive de
  // l'oscillateur — souvent une TROISIÈME émotion, voir CLAUDE.md) est
  // gardé de côté et appliqué quand la voix s'est tue : la balise
  // [EMOTION:] est la vérité du tour, et la voix qui la dit ne doit pas
  // voir le visage glisser vers autre chose au milieu de la phrase.
  let voicedInFlight = 0;
  // Quand la première réplique en vol est partie : soupape de sécurité —
  // un énoncé dont le navigateur n'émet jamais onend/onerror (flake connue
  // de la Web Speech API) ne doit pas figer le visage jusqu'au rechargement.
  let voicedSince = 0;
  const VOICED_HOLD_MAX_MS = 60_000;
  let pendingDrift: {
    emotion: EmotionName;
    intensity: number;
    blend: SpeechMessage["emotion_blend"];
  } | null = null;
  const voiceOwnsFace = () =>
    voicedInFlight > 0 && performance.now() - voicedSince < VOICED_HOLD_MAX_MS;
  const flushDrift = () => {
    if (voiceOwnsFace() || !pendingDrift) return;
    const drift = pendingDrift;
    pendingDrift = null;
    applyAvatarEmotion(drift.emotion, drift.intensity, drift.blend, undefined, {
      ambient: true,
    });
  };

  // TTS with lip-sync + body-animation integration
  const tts = new TTSService({
    onSpeakStart: () => {
      animationSystem.setSpeaking(true);
    },
    onSpeakEnd: () => {
      animationSystem.setSpeaking(false);
      lipSyncController.stop();
      // La voix s'est tue et rien n'attend derrière : le visage est rendu à
      // la dérive. Ce chemin est aussi celui du reset synchrone de stop() /
      // setMuted(), là où la promesse de speak() peut ne jamais se résoudre.
      if (tts.queuedCount === 0) {
        voicedInFlight = 0;
        flushDrift();
      }
    },
    // [SIGH]/[LAUGH] tokens fire a body beat in sync with their audio.
    onProsodicCue: (cue) => {
      animationSystem.playCue(cue);
    },
    // Le plan de lip-sync doit suivre l'énoncé qui commence réellement à
    // jouer, pas celui qu'on vient de mettre en file (voir handleSpeech
    // ci-dessous) : deux répliques rapprochées faisaient sinon articuler la
    // bouche sur le texte suivant pendant que l'audio du précédent tournait
    // encore.
    onUtteranceStart: (text, rate) => {
      lipSyncController.startFromPlan(tts.lipSyncPlan(text), msPerCharForRate(rate));
    },
    // La synthèse dit où en est la voix (début réel, puis chaque mot là où
    // le navigateur le donne) : la bouche s'y recale au lieu de courir sur
    // une estimation qui finissait avant ou après l'audio.
    onSpeechProgress: (charIndex) => {
      lipSyncController.seekToChar(charIndex);
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

  const handleSpeech = (data: SpeechMessage) => {
    // Validate emotion from backend
    const emotion: EmotionName = isEmotionName(data.emotion)
      ? data.emotion
      : "neutral";
    const intensity: number =
      typeof data.emotion_intensity === "number"
        ? data.emotion_intensity
        : 0.7;
    const blend = data.emotion_blend ?? [];
    const persona = data.voice_persona;

    // The readouts follow the frame; the avatar follows the VOICE (below).
    emotionDisplay.setEmotion(emotion, intensity);
    innerLifePanel.setEmotionBlend(blend, intensity);
    innerLifePanel.applyInnerState(data.inner_state);
    // Whatever she was composing, this is it: the thinking gaze ends as
    // the text lands, the voice follows.
    animationSystem.setReplyPending(false);
    // A reply supersedes any drift that was waiting for the voice to end.
    pendingDrift = null;

    const showReply = () => applyAvatarEmotion(emotion, intensity, blend, persona);

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
    const willSpeak =
      data.speak !== false &&
      typeof data.text === "string" &&
      data.text.length > 0 &&
      !tts.isMuted;
    if (!willSpeak) {
      showReply();
      return;
    }
    // Le plan de lip-sync ET l'émotion du visage/corps partent de l'instant
    // où CE texte précis commence effectivement à jouer (`onStart` /
    // `onUtteranceStart`, déclenchés par TTSService au dépilement) — pas
    // ici, à la simple mise en file, où une réplique encore audible se
    // ferait voler la bouche et le visage par celle-ci.
    if (voicedInFlight === 0) voicedSince = performance.now();
    voicedInFlight++;
    let shown = false;
    void tts
      .speak(data.text as string, emotion, data.voice_profile, {
        onStart: () => {
          shown = true;
          showReply();
        },
      })
      .then(() => {
        // Never voiced (muted or stopped before its turn): the text is on
        // screen all the same, so the face should say it.
        if (!shown) showReply();
      })
      .finally(() => {
        voicedInFlight = Math.max(0, voicedInFlight - 1);
        flushDrift();
      });
  };

  ws.on("speech", handleSpeech);

  // Pure state refresh — no speech, no lip-sync, just inner_state.
  // Emitted by the backend when Mika's sleep phase transitions during
  // the night without any conversation turn happening.
  ws.on("inner_state_update", (data) => {
    innerLifePanel.applyInnerState(data.inner_state);
  });

  // Emotional state between turns. The backend oscillators keep moving
  // while Mika is silent — relaxing toward a home vector that itself
  // drifts with the time of day, tinted by whatever she's ruminating on —
  // and this is the only frame that carries that. Without it the face and
  // the readout stayed on the last reply for as long as nobody spoke.
  // Applied as drift: expression, gaze and hand mood follow, postures
  // follow, body one-shots don't (see decideGesture's `ambient` gate).
  ws.on("emotion_update", (data) => {
    if (!isEmotionName(data.emotion)) return;
    const intensity =
      typeof data.emotion_intensity === "number" ? data.emotion_intensity : 0;
    emotionDisplay.setEmotion(data.emotion, intensity);
    innerLifePanel.setEmotionBlend(data.emotion_blend ?? [], intensity);
    if (voiceOwnsFace()) {
      // Held until the voice ends — the newest drift wins.
      pendingDrift = {
        emotion: data.emotion,
        intensity,
        blend: data.emotion_blend ?? [],
      };
      return;
    }
    applyAvatarEmotion(data.emotion, intensity, data.emotion_blend, undefined, {
      ambient: true,
    });
  });

  // A message the server accepted is a reply she is now composing: the
  // gaze goes up and to the side until the `speech` frame lands.
  ws.on("ack", (data) => {
    if (data.status === "accepted") animationSystem.setReplyPending(true);
  });

  // Project reports — silent by default (no TTS). Show as a message
  // in the chat overlay so the user sees what Mika wrapped up. Prefixed
  // to distinguish from regular conversation.
  ws.on("project_report", (data) => {
    // Not a `Message` row, so it will never get a server id. Marked as
    // such, or the merge's "no id means not written yet, therefore
    // newest" rule pinned it to the bottom of the thread for the rest of
    // the session, below every reply that came after it.
    chatOverlay.addMessage(
      `[Projet · ${data.project_title}] ${data.text}`,
      "vtuber",
      { localOnly: true },
    );
  });

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
    applySleepPhase,
    applyEmotion: (emotion, intensity) => applyEmotion(emotion, intensity),
  });

  // Typing anywhere (outside another field) focuses the chat input, so you
  // can just start writing without clicking the box first.
  const chatInput = document.getElementById("chat-input") as HTMLTextAreaElement | null;
  // Someone typing to her is someone to listen to: eyes on them.
  chatInput?.addEventListener("input", () => animationSystem.noteUserTyping());
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
