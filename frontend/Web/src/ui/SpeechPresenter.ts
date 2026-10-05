import {
  isEmotionName,
  resolveSleepPhase,
  type AckMessage,
  type EmotionBlend,
  type EmotionName,
  type EmotionReading,
  type EmotionState,
  type EmotionUpdateMessage,
  type InnerState,
  type InnerStateUpdateMessage,
  type SleepPhase,
  type SpeechMessage,
  type VoicePersona,
  type VoiceProfile,
} from "../types";

/**
 * Ce que la voix doit savoir faire pour le presenter — le sous-ensemble de
 * `TTSService` qu'il touche, pour qu'un faux de dix lignes suffise en test.
 */
export interface VoicePort {
  readonly isMuted: boolean;
  /** Répliques encore en file derrière celle qui joue. */
  readonly queuedCount: number;
  /** `intensity` (0…1) dose l'inflexion de la voix, comme elle dose déjà
   * le visage, la bouche et le tempo du corps. */
  speak(
    text: string,
    emotion: EmotionName,
    profile: VoiceProfile | undefined,
    hooks: { onStart?: () => void },
    intensity?: number
  ): Promise<"played" | "skipped">;
  requestWakeUpDelay(ms: number): void;
}

/** Le visage (blend shapes d'émotion). Le mélange, quand il y en a un,
 * laisse transparaître l'émotion secondaire — un sourire teinté de
 * tristesse plutôt qu'un masque d'une seule émotion. */
export interface FacePort {
  setEmotion(emotion: EmotionName, intensity: number, blend?: EmotionBlend): void;
  /** Énergie 0…1 (rythme circadien + fatigue) : des paupières lourdes
   * quand elle est épuisée. Optionnel. */
  setEnergy?(energy: number): void;
}

/** Le corps : regard, mains, postures, one-shots, et les signaux de
 * conversation que la machine d'animation lit. */
export interface BodyPort {
  setEmotion(
    emotion: EmotionName,
    intensity: number,
    blend: EmotionBlend,
    persona: VoicePersona | undefined,
    opts: { ambient?: boolean }
  ): void;
  setSpeaking(speaking: boolean): void;
  setReplyPending(pending: boolean): void;
  noteUserTyping(): void;
  setSleepPhase(phase: SleepPhase): void;
  /** Énergie 0…1 : respiration, agitation, clignements, bâillements. */
  setEnergy?(energy: number): void;
  /** Le fond de sa journée (`emotion_state.global`) : le corps le porte,
   * mêlé au moment — le visage non. Optionnel. */
  setMood?(emotion: EmotionName, intensity: number): void;
  /** Où l'IA l'a mise dans sa chambre (un état, pas un ordre). */
  setPlace?(place: unknown): void;
}

/** La scène (lumières, fond) — ne suit que le sommeil. */
export interface StagePort {
  setSleepPhase(phase: SleepPhase): void;
}

/** Les afficheurs texte : l'émotion lue, le mélange, l'état intérieur. Ils
 * suivent la TRAME, jamais la voix — le texte est à l'écran avant que la
 * voix ne le dise. */
export interface ReadoutsPort {
  setEmotion(emotion: EmotionName, intensity: number): void;
  setEmotionBlend(blend: EmotionBlend, intensity: number): void;
  applyInnerState(state: InnerState | undefined): void;
}

/** Minuteries injectables (les tests n'attendent pas soixante secondes). */
export interface TimerPort {
  set(fn: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

export interface SpeechPresenterDeps {
  voice: VoicePort;
  face: FacePort;
  body: BodyPort;
  stage: StagePort;
  readouts: ReadoutsPort;
  /** Horloge monotone en ms (`performance.now` en prod). */
  now?: () => number;
  timers?: TimerPort;
}

/**
 * Soupape de sécurité : un énoncé dont le navigateur n'émet jamais
 * onend/onerror (flake connue de la Web Speech API) ne doit pas figer le
 * visage jusqu'au rechargement. Passé ce délai depuis le départ de la
 * première réplique en vol, la voix ne possède plus le visage.
 */
export const VOICED_HOLD_MAX_MS = 60_000;

/** Elle dormait il y a moins de ça : la première réplique attend
 * `WAKE_UP_DELAY_MS` de silence, pour qu'elle ait l'air d'émerger. */
export const WAKE_UP_WINDOW_MS = 10_000;
export const WAKE_UP_DELAY_MS = 1_300;

interface Drift {
  emotion: EmotionName;
  intensity: number;
  blend: EmotionBlend;
}

/**
 * Le fond de sa journée dans une trame (`emotion_state.global`, son humeur
 * à elle — ADR 0032), validé à l'entrée : du JSON jamais vérifié, comme
 * l'émotion. Null quand il manque ou ne se lit pas (un serveur plus ancien,
 * une trame d'erreur) : le corps garde alors le fond qu'il avait.
 */
function moodOf(state: EmotionState | undefined): EmotionReading | null {
  const global = state?.global;
  if (!global || !isEmotionName(global.emotion)) return null;
  const intensity = global.intensity;
  if (typeof intensity !== "number" || !Number.isFinite(intensity)) return null;
  return { emotion: global.emotion, intensity };
}

/**
 * Ce que la voix dit, le visage le montre — au moment où ça sonne.
 *
 * Une trame `speech` met les afficheurs à jour tout de suite, mais
 * l'émotion de l'avatar (visage, one-shot du corps, biais de regard, humeur
 * des mains) part de l'instant où CET énoncé commence effectivement à jouer
 * (`onStart` de `speak()`), après le silence de réveil et après les
 * répliques qui le précédaient dans la file. Tant qu'une réplique vocalisée
 * est en vol, la dérive `emotion_update` — souvent une TROISIÈME émotion,
 * voir CLAUDE.md — est gardée de côté (la plus récente gagne) et appliquée
 * quand la voix s'est tue : la balise [EMOTION:] est la vérité du tour, et
 * la voix qui la dit ne doit pas voir le visage glisser au milieu de la
 * phrase.
 *
 * Aucun import de Three.js ni du DOM : tout arrive par les ports.
 */
export class SpeechPresenter {
  private readonly voice: VoicePort;
  private readonly face: FacePort;
  private readonly body: BodyPort;
  private readonly stage: StagePort;
  private readonly readouts: ReadoutsPort;
  private readonly now: () => number;
  private readonly timers: TimerPort;

  /** Répliques vocalisées mises en file et pas encore réglées. */
  private voicedInFlight = 0;
  /** Départ de la première réplique en vol (base de la soupape). */
  private voicedSince = 0;
  private holdValve: unknown = null;
  private pendingDrift: Drift | null = null;
  private lastAsleepAt: number | null = null;

  constructor(deps: SpeechPresenterDeps) {
    this.voice = deps.voice;
    this.face = deps.face;
    this.body = deps.body;
    this.stage = deps.stage;
    this.readouts = deps.readouts;
    this.now = deps.now ?? (() => performance.now());
    this.timers = deps.timers ?? {
      set: (fn, ms) => setTimeout(fn, ms),
      clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    };
  }

  // ── Trames serveur ────────────────────────────────────────────────

  handleSpeech(data: SpeechMessage): void {
    const emotion: EmotionName = isEmotionName(data.emotion) ? data.emotion : "neutral";
    const intensity =
      typeof data.emotion_intensity === "number" ? data.emotion_intensity : 0.7;
    const blend = data.emotion_blend ?? [];
    const persona = data.voice_persona;

    // Les afficheurs suivent la trame ; l'avatar suit la VOIX (plus bas).
    this.readouts.setEmotion(emotion, intensity);
    this.readouts.setEmotionBlend(blend, intensity);
    this.readouts.applyInnerState(data.inner_state);
    this.applyBodyState(data.inner_state);
    this.applyMood(data.emotion_state);
    // Quoi qu'elle composait, c'est ceci : le regard « je réfléchis » cesse
    // quand le texte arrive, la voix suit.
    this.body.setReplyPending(false);

    // Une trame sans texte n'est pas une réplique : elle s'est tue, ou la
    // réponse ne viendra pas (`protocol.py::silence`). Le visage garde ce
    // qu'il montrait — pas de one-shot du corps, pas de visage volé à une
    // voix encore en vol, ni persona ni dérive en attente touchés.
    if (typeof data.text !== "string" || data.text.length === 0) return;

    // Une réponse supplante toute dérive qui attendait la fin de la voix.
    this.pendingDrift = null;

    const showReply = () => this.applyAvatar(emotion, intensity, blend, persona, {});

    // Pause de réveil : endormie il y a moins de dix secondes (encore
    // marquée endormie, ou passée éveillée dans ce même payload), la voix
    // est précédée d'un court silence. Une fois par réveil.
    if (this.lastAsleepAt !== null && this.now() - this.lastAsleepAt < WAKE_UP_WINDOW_MS) {
      this.voice.requestWakeUpDelay(WAKE_UP_DELAY_MS);
      this.lastAsleepAt = null;
    }

    // Le backend décide si ce tour est vocalisé (old/backend/pipeline/voice.py).
    // `speak: false` montre le texte et anime l'avatar, sans un son.
    const willSpeak = data.speak !== false && !this.voice.isMuted;
    if (!willSpeak) {
      showReply();
      return;
    }

    // L'émotion du visage/corps part de l'instant où CE texte commence à
    // jouer (`onStart`, déclenché par la voix au dépilement) — pas ici, à
    // la mise en file, où une réplique encore audible se ferait voler le
    // visage par celle-ci.
    this.noteVoicedEnqueued();
    let shown = false;
    void this.voice
      .speak(
        data.text as string,
        emotion,
        data.voice_profile,
        {
          onStart: () => {
            shown = true;
            showReply();
          },
        },
        intensity
      )
      .then(() => {
        // Jamais jouée (muet ou stop avant son tour) : le texte est à
        // l'écran quand même, le visage doit le dire.
        if (!shown) showReply();
      })
      .finally(() => {
        this.voicedInFlight = Math.max(0, this.voicedInFlight - 1);
        if (this.voicedInFlight === 0) this.clearValve();
        this.flushDrift();
      });
  }

  /** État intérieur seul — ni voix, ni lip-sync (transition de sommeil la
   * nuit, action de projet mise en attente). */
  handleInnerStateUpdate(data: InnerStateUpdateMessage): void {
    this.readouts.applyInnerState(data.inner_state);
    this.applyBodyState(data.inner_state);
  }

  /** La fatigue se voit sur l'avatar, pas seulement dans le panneau. */
  private applyBodyState(state: InnerState | undefined): void {
    // Le lieu voyage dans le même état intérieur : un changement se marche,
    // le même lieu renvoyé (reconnexion) ne fait rien.
    if (state?.place !== undefined) this.body.setPlace?.(state.place);
    const energy = state?.energy;
    if (typeof energy !== "number" || !Number.isFinite(energy)) return;
    this.face.setEnergy?.(energy);
    this.body.setEnergy?.(energy);
  }

  /**
   * Le fond passe au corps dès la trame, jamais retenu derrière la voix :
   * ce n'est pas un visage volé à la réplique en vol, c'est la posture de
   * la journée, et le visage reste sur le moment.
   */
  private applyMood(state: EmotionState | undefined): void {
    const mood = moodOf(state);
    if (mood) this.body.setMood?.(mood.emotion, mood.intensity);
  }

  /**
   * La dérive entre deux tours : les oscillateurs bougent pendant qu'elle
   * se tait, et c'est la seule trame qui le porte. Appliquée par le MÊME
   * chemin qu'une réponse avec `ambient: true` — expression, regard, mains
   * et postures suivent, les one-shots du corps non (voir `decideGesture`).
   */
  handleEmotionUpdate(data: EmotionUpdateMessage): void {
    if (!isEmotionName(data.emotion)) return;
    const intensity =
      typeof data.emotion_intensity === "number" ? data.emotion_intensity : 0;
    const blend = data.emotion_blend ?? [];
    this.readouts.setEmotion(data.emotion, intensity);
    this.readouts.setEmotionBlend(blend, intensity);
    this.applyMood(data.emotion_state);
    if (this.voiceOwnsFace()) {
      // Retenue jusqu'à la fin de la voix — la plus récente gagne.
      this.pendingDrift = { emotion: data.emotion, intensity, blend };
      return;
    }
    this.applyAvatar(data.emotion, intensity, blend, undefined, { ambient: true });
  }

  /** Un message accepté est une réponse qu'elle compose : le regard part
   * en haut et de côté jusqu'à la trame `speech`. */
  handleAck(data: AckMessage): void {
    if (data.status === "accepted") this.body.setReplyPending(true);
  }

  /** Quelqu'un lui écrit : les yeux sur lui. */
  noteUserTyping(): void {
    this.body.noteUserTyping();
  }

  // ── Voix ──────────────────────────────────────────────────────────

  /** Brancher sur `TTSEvents.onSpeakStart`. */
  handleSpeakStart(): void {
    this.body.setSpeaking(true);
  }

  /**
   * Brancher sur `TTSEvents.onSpeakEnd`. La voix s'est tue et rien
   * n'attend derrière : le visage est rendu à la dérive. C'est aussi le
   * chemin du reset synchrone de `stop()` / `setMuted()`, là où la promesse
   * de `speak()` peut ne jamais se résoudre.
   */
  handleSpeakEnd(): void {
    this.body.setSpeaking(false);
    if (this.voice.queuedCount === 0) {
      this.voicedInFlight = 0;
      this.clearValve();
      this.flushDrift();
    }
  }

  // ── Sommeil ───────────────────────────────────────────────────────

  /**
   * Fan-out d'une phase (animation + scène + tampon de réveil). Gardée à
   * l'entrée : une phase que le backend n'a jamais déclarée vaut « awake »
   * plutôt qu'une exception au milieu d'un handler.
   */
  setSleepPhase(value: unknown): void {
    const phase = resolveSleepPhase(value);
    this.body.setSleepPhase(phase);
    this.stage.setSleepPhase(phase);
    if (phase !== "awake") this.lastAsleepAt = this.now();
  }

  // ── Debug ─────────────────────────────────────────────────────────

  /** Avatar + afficheur d'un coup, hors de toute voix (raccourcis QA). */
  showEmotion(emotion: EmotionName, intensity: number, blend: EmotionBlend = []): void {
    this.applyAvatar(emotion, intensity, blend, undefined, {});
    this.readouts.setEmotion(emotion, intensity);
  }

  // ── Interne ───────────────────────────────────────────────────────

  private applyAvatar(
    emotion: EmotionName,
    intensity: number,
    blend: EmotionBlend,
    persona: VoicePersona | undefined,
    opts: { ambient?: boolean }
  ): void {
    this.face.setEmotion(emotion, intensity, blend);
    this.body.setEmotion(emotion, intensity, blend, persona, opts);
  }

  private voiceOwnsFace(): boolean {
    return this.voicedInFlight > 0 && this.now() - this.voicedSince < VOICED_HOLD_MAX_MS;
  }

  private noteVoicedEnqueued(): void {
    if (this.voicedInFlight === 0) {
      this.voicedSince = this.now();
      // La soupape ne se contente pas de laisser passer la PROCHAINE
      // dérive : celle déjà retenue est relâchée à l'échéance, sinon une
      // humeur stable (aucune nouvelle trame) laissait le visage figé.
      this.clearValve();
      this.holdValve = this.timers.set(() => {
        this.holdValve = null;
        this.flushDrift();
      }, VOICED_HOLD_MAX_MS);
    }
    this.voicedInFlight++;
  }

  private clearValve(): void {
    if (this.holdValve !== null) {
      this.timers.clear(this.holdValve);
      this.holdValve = null;
    }
  }

  private flushDrift(): void {
    if (this.voiceOwnsFace() || !this.pendingDrift) return;
    const drift = this.pendingDrift;
    this.pendingDrift = null;
    this.applyAvatar(drift.emotion, drift.intensity, drift.blend, undefined, {
      ambient: true,
    });
  }
}
