import type {
  EmotionName,
  ProsodicCue,
  SpeechPlanSegment,
  VoiceProfile,
} from "../types";

export type { VoiceProfile } from "../types";

const NEUTRAL_PROFILE: VoiceProfile = { pitch: 1.0, rate: 1.0, gain: 1.0 };

/** Ce qu'il est advenu d'un `speak()` : joué (même coupé en route) ou
 * jamais commencé (muet, vidé par un mute ou un stop). */
export type SpeakOutcome = "played" | "skipped";

export interface SpeakHooks {
  /**
   * Appelé à l'instant où CET énoncé commence réellement — après le
   * silence de réveil, après ceux qui le précédaient dans la file. C'est là
   * que ce qui doit coïncider avec la voix (l'émotion du visage, le geste
   * du corps) doit s'appliquer, et non à la réception de la frame : deux
   * répliques rapprochées faisaient sinon changer le visage sur la seconde
   * pendant que la voix disait encore la première — le défaut déjà corrigé
   * pour la bouche via onUtteranceStart, étendu au reste du corps.
   */
  onStart?: () => void;
}

// Temps que chaque effet non verbal occupe dans la restitution. Sert de
// budget d'attente à playSfx et de durée de silence au plan de lip-sync :
// deux valeurs distinctes se seraient désynchronisées de la bouche.
const SFX_DURATION_MS: Record<ProsodicCue, number> = {
  sigh: 600,
  laugh: 900,
  breath: 350,
};

// Web Speech API accepts pitch in [0,2] and rate in [0.1,10]; the product of
// an emotion multiplier and a persona multiplier can leave that window.
const clampPitch = (v: number) => Math.max(0.1, Math.min(2, v));
const clampRate = (v: number) => Math.max(0.5, Math.min(2, v));

export interface TTSEvents {
  onSpeakStart: () => void;
  onSpeakEnd: () => void;
  /** Fired when a [SIGH]/[LAUGH]/[BREATH] token is reached, right
   * before its synthetic audio plays — so a body gesture can start in
   * sync with the sound. */
  onProsodicCue?: (cue: ProsodicCue) => void;
  /**
   * Fired for the queued item that is actually about to play — after any
   * pending wake-up delay, right before synthesis starts for real.
   *
   * The caller used to build the lip-sync plan itself at `speak()` time,
   * which is when the text is *enqueued*, not when it starts sounding: two
   * replies close together had the mouth animate the second one's phonemes
   * while the first was still audible, because `speak()` only queues.
   * Passing the text back here lets the caller derive the plan
   * (`lipSyncPlan(text)`) at the moment it actually applies.
   */
  onUtteranceStart?: (text: string, rate: number) => void;
  /**
   * « La voix en est à ce caractère du texte de la réponse. » Émis à
   * `utterance.onstart` (index du début du morceau qui sonne) et, là où le
   * navigateur les fournit, à chaque frontière de mot (`onboundary`). Le
   * lip-sync s'y recale : l'estimation texte ne peut plus dériver de toute
   * la latence de synthèse ni se terminer avant la voix.
   */
  onSpeechProgress?: (charIndex: number) => void;
}

// Emotion-to-voice modulation: pitch and rate adjustments
const EMOTION_VOICE: Record<
  string,
  { pitch: number; rate: number }
> = {
  neutral: { pitch: 1.0, rate: 1.0 },
  happy: { pitch: 1.15, rate: 1.05 },
  excited: { pitch: 1.3, rate: 1.15 },
  love: { pitch: 1.1, rate: 0.9 },
  proud: { pitch: 1.05, rate: 0.95 },
  grateful: { pitch: 1.1, rate: 0.95 },
  playful: { pitch: 1.2, rate: 1.1 },
  amused: { pitch: 1.15, rate: 1.05 },
  hopeful: { pitch: 1.1, rate: 1.0 },
  relieved: { pitch: 1.0, rate: 0.9 },
  sad: { pitch: 0.85, rate: 0.85 },
  angry: { pitch: 0.9, rate: 1.15 },
  scared: { pitch: 1.2, rate: 1.2 },
  disgusted: { pitch: 0.85, rate: 0.9 },
  frustrated: { pitch: 0.9, rate: 1.1 },
  lonely: { pitch: 0.9, rate: 0.85 },
  anxious: { pitch: 1.1, rate: 1.15 },
  bored: { pitch: 0.85, rate: 0.8 },
  jealous: { pitch: 0.95, rate: 1.05 },
  surprised: { pitch: 1.3, rate: 1.1 },
  thinking: { pitch: 0.95, rate: 0.85 },
  confused: { pitch: 1.05, rate: 0.9 },
  embarrassed: { pitch: 1.1, rate: 0.9 },
  nostalgic: { pitch: 0.95, rate: 0.85 },
  dreamy: { pitch: 1.05, rate: 0.8 },
  determined: { pitch: 0.95, rate: 1.05 },
  mischievous: { pitch: 1.15, rate: 1.05 },
  curious: { pitch: 1.1, rate: 1.0 },
  melancholic: { pitch: 0.85, rate: 0.8 },
};

export class TTSService {
  private audioContext: AudioContext | null = null;
  private events: TTSEvents;
  private preferredVoice: SpeechSynthesisVoice | null = null;
  private isSpeaking = false;
  private speechQueue: Array<{
    text: string;
    emotion: EmotionName;
    profile: VoiceProfile;
    hooks: SpeakHooks | undefined;
    settle: (outcome: SpeakOutcome) => void;
  }> = [];
  private processing = false;
  // Next speak() call will be prefixed with this many ms of silence.
  // Used by the wake-up flow: if Mika was asleep and is now replying,
  // pause briefly so she sounds like she's waking up, not answering
  // instantly from a dead sleep.
  private nextPreDelayMs = 0;
  // Voice identity of the utterance currently being built. Set by
  // speakImmediate so the deeper utterance construction can read it
  // without threading the profile through every segment helper.
  private activeProfile: VoiceProfile = NEUTRAL_PROFILE;

  constructor(events: TTSEvents) {
    this.events = events;
    this.initVoice();
  }

  /** Queue a one-shot delay before the next speech utterance. */
  requestWakeUpDelay(ms: number): void {
    this.nextPreDelayMs = Math.max(this.nextPreDelayMs, Math.floor(ms));
  }

  /**
   * Parse non-verbal tokens embedded in the text into a sequence of
   * playback segments. Supported tokens:
   *   [PAUSE:300]   → 300ms silence (ms optional, default 500)
   *   [PAUSE]       → 500ms silence
   *   [SIGH]        → synthetic sigh (~600ms)
   *   [LAUGH]       → synthetic short laugh (~500ms)
   *   [BREATH]      → synthetic inhale (~350ms)
   *
   * The tokens let Mika embed prosodic cues directly in her response,
   * so "Hmm... [SIGH] bon écoute, [PAUSE:400] je crois que oui."
   * becomes actual audio beats, not just typed punctuation.
   */
  private parseSegments(
    text: string
  ): Array<
    | { type: "speech"; text: string; start: number }
    | { type: "pause"; ms: number }
    | { type: "sfx"; kind: "sigh" | "laugh" | "breath" }
  > {
    const TOKEN_RE = /\[(PAUSE(?::(\d+))?|SIGH|LAUGH|BREATH)\]/gi;
    const segments: Array<
      | { type: "speech"; text: string; start: number }
      | { type: "pause"; ms: number }
      | { type: "sfx"; kind: "sigh" | "laugh" | "breath" }
    > = [];

    // `start` est l'index du premier caractère RETENU dans le texte
    // complet : la synthèse rapporte ses frontières de mot relativement au
    // morceau qu'elle joue, et c'est cet offset qui les ramène au texte.
    const pushSpeech = (from: number, to: number) => {
      const raw = text.slice(from, to);
      const lead = raw.length - raw.trimStart().length;
      const chunk = raw.trim();
      if (chunk) segments.push({ type: "speech", text: chunk, start: from + lead });
    };

    let cursor = 0;
    let match: RegExpExecArray | null;
    while ((match = TOKEN_RE.exec(text)) !== null) {
      // Text before the token
      if (match.index > cursor) pushSpeech(cursor, match.index);
      const kind = match[1].toUpperCase();
      if (kind.startsWith("PAUSE")) {
        const ms = match[2] ? parseInt(match[2], 10) : 500;
        segments.push({ type: "pause", ms: Math.min(3000, Math.max(50, ms)) });
      } else if (kind === "SIGH") {
        segments.push({ type: "sfx", kind: "sigh" });
      } else if (kind === "LAUGH") {
        segments.push({ type: "sfx", kind: "laugh" });
      } else if (kind === "BREATH") {
        segments.push({ type: "sfx", kind: "breath" });
      }
      cursor = match.index + match[0].length;
    }
    // Trailing text
    if (cursor < text.length) pushSpeech(cursor, text.length);
    return segments;
  }

  /**
   * Le même découpage, réduit à ce dont le lip-sync a besoin : ce qui est
   * prononcé, et le temps réservé sans qu'un mot soit dit. Exposé parce que
   * la chaîne brute n'est pas ce qui sort des haut-parleurs — sans lui la
   * bouche articulait les caractères de « [PAUSE:400] » puis dérivait du
   * reste de la phrase de toute la durée des silences.
   */
  lipSyncPlan(text: string): SpeechPlanSegment[] {
    return this.parseSegments(text).map((seg) => {
      if (seg.type === "speech") {
        return { type: "speech", text: seg.text, start: seg.start };
      }
      const ms = seg.type === "pause" ? seg.ms : SFX_DURATION_MS[seg.kind];
      return { type: "silence", ms };
    });
  }

  /**
   * Play a synthetic non-verbal effect. Uses raw WebAudio so we don't
   * need asset files. Quality is "good enough for a VTuber", not voice-
   * actor studio grade — the point is prosodic presence, not realism.
   */
  private async playSfx(kind: "sigh" | "laugh" | "breath"): Promise<void> {
    // Le mute passe par speechSynthesis.cancel(), qui n'a aucune prise sur
    // WebAudio : sans cette garde le soupir sortait après le clic sur 🔇.
    if (this.muted) return;
    const ctx = this.ensureAudioContext();
    if (ctx.state === "suspended") {
      // Awaited: a suspended context never fires `onended`, and the queue
      // awaits this promise — a silent resume() left Mika mute for the rest
      // of the session if her first reply contained a prosodic token before
      // the user had interacted with the page.
      try {
        await ctx.resume();
      } catch {
        // Autoplay policy still blocking (no user gesture yet): skip the
        // effect rather than hanging the speech queue on it.
        return;
      }
    }
    const now = ctx.currentTime;

    const budgetMs = SFX_DURATION_MS[kind];
    let rendered: Promise<void>;
    switch (kind) {
      case "sigh":
        rendered = this.renderSigh(ctx, now);
        break;
      case "laugh":
        rendered = this.renderLaugh(ctx, now);
        break;
      case "breath":
        rendered = this.renderBreath(ctx, now);
        break;
    }
    // Belt and braces: a context suspended mid-render (tab backgrounded)
    // would otherwise never resolve.
    await Promise.race([
      rendered,
      new Promise<void>((r) => setTimeout(r, budgetMs + 250)),
    ]);
  }

  /** Synthetic sigh: filtered noise, descending pitch, 600ms envelope. */
  private renderSigh(ctx: AudioContext, now: number): Promise<void> {
    const duration = 0.6;
    const buffer = ctx.createBuffer(1, ctx.sampleRate * duration, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) {
      data[i] = (Math.random() * 2 - 1) * 0.6;
    }
    const src = ctx.createBufferSource();
    src.buffer = buffer;

    const filter = ctx.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.setValueAtTime(420, now);
    filter.frequency.linearRampToValueAtTime(260, now + duration);
    filter.Q.value = 4;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.25, now + 0.08);
    gain.gain.linearRampToValueAtTime(0, now + duration);

    src.connect(filter).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + duration);
    return new Promise((r) => {
      src.onended = () => r();
    });
  }

  /** Synthetic laugh: 3-4 short voiced pulses, descending pitch. */
  private renderLaugh(ctx: AudioContext, now: number): Promise<void> {
    const pulses = 3 + Math.floor(Math.random() * 2); // 3 or 4
    const pulseDur = 0.09;
    const spacing = 0.11;
    const basePitch = 280 + Math.random() * 40; // per-laugh variation
    const totalDur = pulses * spacing + 0.05;

    const gainMaster = ctx.createGain();
    gainMaster.gain.value = 0.18;
    gainMaster.connect(ctx.destination);

    for (let i = 0; i < pulses; i++) {
      const pulseStart = now + i * spacing;
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.value = basePitch * (1 - i * 0.08);

      // Add a noise component for raspiness
      const noiseBuf = ctx.createBuffer(1, ctx.sampleRate * pulseDur, ctx.sampleRate);
      const nd = noiseBuf.getChannelData(0);
      for (let j = 0; j < nd.length; j++) nd[j] = (Math.random() * 2 - 1) * 0.35;
      const noise = ctx.createBufferSource();
      noise.buffer = noiseBuf;

      const env = ctx.createGain();
      env.gain.setValueAtTime(0, pulseStart);
      env.gain.linearRampToValueAtTime(1.0, pulseStart + 0.015);
      env.gain.linearRampToValueAtTime(0, pulseStart + pulseDur);

      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = 1400;

      osc.connect(env);
      noise.connect(env);
      env.connect(filter).connect(gainMaster);
      osc.start(pulseStart);
      osc.stop(pulseStart + pulseDur);
      noise.start(pulseStart);
      noise.stop(pulseStart + pulseDur);
    }

    return new Promise((r) => setTimeout(r, totalDur * 1000));
  }

  /** Synthetic inhale: brief high-passed hiss. */
  private renderBreath(ctx: AudioContext, now: number): Promise<void> {
    const duration = 0.35;
    const buffer = ctx.createBuffer(1, ctx.sampleRate * duration, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * 0.5;
    const src = ctx.createBufferSource();
    src.buffer = buffer;

    const filter = ctx.createBiquadFilter();
    filter.type = "highpass";
    filter.frequency.value = 900;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.12, now + 0.07);
    gain.gain.linearRampToValueAtTime(0, now + duration);

    src.connect(filter).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + duration);
    return new Promise((r) => {
      src.onended = () => r();
    });
  }

  private initVoice() {
    const pickVoice = () => {
      const voices = speechSynthesis.getVoices();
      // Prefer a French female voice
      this.preferredVoice =
        voices.find(
          (v) => v.lang.startsWith("fr") && v.name.toLowerCase().includes("female")
        ) ||
        voices.find((v) => v.lang.startsWith("fr")) ||
        voices.find((v) => v.lang.startsWith("en") && v.name.toLowerCase().includes("female")) ||
        voices[0] ||
        null;

      if (this.preferredVoice) {
        console.log(`TTS voice: ${this.preferredVoice.name} (${this.preferredVoice.lang})`);
      }
    };

    pickVoice();
    if (speechSynthesis.onvoiceschanged !== undefined) {
      speechSynthesis.onvoiceschanged = pickVoice;
    }
  }

  /**
   * Le contexte WebAudio ne sert qu'aux effets [SIGH]/[LAUGH]/[BREATH] :
   * la Web Speech API ne donne aucun accès à son flux audio, donc rien
   * d'analysable n'y transite. Une synthèse future rendant de vrais buffers
   * les jouerait ici et pourrait alors piloter le lip-sync depuis l'audio.
   */
  private ensureAudioContext(): AudioContext {
    if (!this.audioContext) {
      this.audioContext = new AudioContext();
    }
    return this.audioContext;
  }

  /**
   * Mute switch. Muting drops queued utterances and cuts the current one
   * short. `speechSynthesis.cancel()` is *supposed* to fire the utterance's
   * end event, but nothing guarantees the browser actually does (a known
   * Web Speech API flake) — without the synchronous reset below, a mute
   * hitting that case left `isSpeaking` stuck true and the talking
   * animation running forever. Mirrors `stop()`'s reset; `forceSpeechEnded`
   * is what keeps the two from double-firing `onSpeakEnd` when the browser
   * event does eventually arrive. Unmuting only affects future replies.
   */
  setMuted(muted: boolean) {
    this.muted = muted;
    if (muted) {
      this.dropQueue();
      this.nextPreDelayMs = 0;
      this.interruptEpoch++;
      if ("speechSynthesis" in window) {
        speechSynthesis.cancel();
      }
      this.forceSpeechEnded();
    }
  }

  get isMuted(): boolean {
    return this.muted;
  }

  /** Replies still waiting behind the one in flight. */
  get queuedCount(): number {
    return this.speechQueue.length;
  }

  private muted = false;

  // Jeton d'interruption, incrémenté par `setMuted(true)` et par `stop()`.
  // `speechSynthesis.cancel()` ne tue que l'énoncé en cours, jamais la boucle
  // qui enchaîne les segments : le chemin segmenté capture donc cette valeur
  // et abandonne les segments restants dès qu'elle change.
  private interruptEpoch = 0;

  /**
   * Met le texte en file. La promesse se résout quand l'énoncé a fini de
   * jouer (ou dès qu'il est certain qu'il ne jouera pas) : c'est ce qui
   * permet à l'appelant de savoir qu'une réplique vocale est encore en vol
   * — et donc que le visage lui appartient.
   */
  speak(
    text: string,
    emotion: EmotionName = "neutral",
    profile: VoiceProfile = NEUTRAL_PROFILE,
    hooks?: SpeakHooks
  ): Promise<SpeakOutcome> {
    if (this.muted) return Promise.resolve("skipped");
    return new Promise<SpeakOutcome>((settle) => {
      this.speechQueue.push({ text, emotion, profile, hooks, settle });
      if (!this.processing) {
        this.processQueue();
      }
    });
  }

  private async processQueue() {
    this.processing = true;

    while (this.speechQueue.length > 0) {
      const item = this.speechQueue.shift()!;
      let outcome: SpeakOutcome = "skipped";
      try {
        outcome = await this.speakImmediate(item.text, item.emotion, item.profile, item.hooks);
      } finally {
        item.settle(outcome);
      }
    }

    this.processing = false;
  }

  /** Vide la file en prévenant chaque item qu'il ne jouera jamais. */
  private dropQueue() {
    const dropped = this.speechQueue.splice(0, this.speechQueue.length);
    for (const item of dropped) item.settle("skipped");
  }

  /** Débit effectif d'un énoncé : modulation d'émotion × identité vocale,
   * borné comme `utterance.rate` l'est. */
  effectiveRate(emotion: EmotionName, profile: VoiceProfile = NEUTRAL_PROFILE): number {
    const voiceMod = EMOTION_VOICE[emotion] || EMOTION_VOICE.neutral;
    return clampRate(voiceMod.rate * profile.rate);
  }

  private async speakImmediate(
    text: string,
    emotion: EmotionName,
    profile: VoiceProfile = NEUTRAL_PROFILE,
    hooks?: SpeakHooks
  ): Promise<SpeakOutcome> {
    this.activeProfile = profile;
    // Consume any pending wake-up delay before the actual utterance.
    // Drained here (not in processQueue) so back-to-back speeches within
    // a single response don't keep re-delaying.
    if (this.nextPreDelayMs > 0) {
      const delay = this.nextPreDelayMs;
      this.nextPreDelayMs = 0;
      await new Promise((r) => setTimeout(r, delay));
    }

    // Un mute arrivé pendant le silence de réveil : l'énoncé ne joue pas.
    if (this.muted) return "skipped";

    // Ce tour précis commence maintenant — pas au moment où speak() l'a mis
    // en file, ni pendant le silence du réveil ci-dessus. C'est le signal
    // sur lequel le lip-sync et le visage doivent se caler.
    hooks?.onStart?.();
    this.events.onUtteranceStart?.(text, this.effectiveRate(emotion, profile));

    // Parse non-verbal tokens and handle the segmented path if any are
    // present. Fall through to the single-utterance path when the text
    // is clean speech (common case — avoids adding latency to every reply).
    const hasTokens = /\[(PAUSE(?::\d+)?|SIGH|LAUGH|BREATH)\]/i.test(text);
    if (hasTokens) {
      await this.speakSegmented(text, emotion);
    } else {
      await this.speakTextChunk(text, emotion);
    }
    return "played";
  }

  /**
   * Speak the text after splitting it into segments around non-verbal
   * tokens. Fires a single onSpeakStart at the beginning of the first
   * audible segment and a single onSpeakEnd after the last one, so the
   * lip-sync controller sees the whole reply as one coherent event.
   */
  private async speakSegmented(
    text: string,
    emotion: EmotionName
  ): Promise<void> {
    const segments = this.parseSegments(text);
    if (segments.length === 0) return;
    const epoch = this.interruptEpoch;

    // Emit "start" on the first segment that actually makes sound.
    let started = false;
    const emitStart = () => {
      if (started) return;
      started = true;
      this.events.onSpeakStart();
    };

    for (const seg of segments) {
      // Un mute ou un stop arrivé pendant le segment précédent doit couper
      // net. Sans cette garde, le `cancel()` ne tuait que l'énoncé en cours
      // et la boucle jouait quand même le soupir puis la fin de la réponse.
      if (this.muted || epoch !== this.interruptEpoch) break;

      if (seg.type === "speech") {
        emitStart();
        await this.speakTextChunk(seg.text, emotion, /*suppressEvents*/ true, seg.start);
      } else if (seg.type === "pause") {
        await new Promise((r) => setTimeout(r, seg.ms));
      } else if (seg.type === "sfx") {
        emitStart();
        this.events.onProsodicCue?.(seg.kind);
        await this.playSfx(seg.kind);
      }
    }

    if (started) {
      this.events.onSpeakEnd();
    }
  }

  /**
   * Speak a single chunk of plain text (no tokens). Returns a promise
   * resolved when the utterance ends or errors. When `suppressEvents` is
   * true, the start/end callbacks are NOT fired — used by the segmented
   * path which manages these lifecycle events at a higher level.
   */
  private speakTextChunk(
    text: string,
    emotion: EmotionName,
    suppressEvents = false,
    charBase = 0
  ): Promise<void> {
    return new Promise((resolve) => {
      // Muet : ne jamais relancer la synthèse. Couvre la course entre le
      // `cancel()` du mute et le segment suivant, déjà en vol ici.
      if (this.muted || !text.trim()) {
        resolve();
        return;
      }

      // Cancel any ongoing speech
      speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);

      if (this.preferredVoice) {
        utterance.voice = this.preferredVoice;
      }

      // Apply emotion modulation
      // Emotion modulation first, then the voice identity on top of it:
      // an excited *thought* is still quieter than an excited sentence.
      const voiceMod = EMOTION_VOICE[emotion] || EMOTION_VOICE.neutral;
      const profile = this.activeProfile;
      utterance.pitch = clampPitch(voiceMod.pitch * profile.pitch);
      utterance.rate = clampRate(voiceMod.rate * profile.rate);
      utterance.volume = Math.max(0, Math.min(1, profile.gain));

      // Réveille le contexte WebAudio pendant qu'un geste utilisateur est
      // encore proche, pour qu'un [SIGH] plus loin dans la réponse sorte.
      const ctx = this.ensureAudioContext();
      if (ctx.state === "suspended") {
        ctx.resume();
      }

      utterance.onstart = () => {
        this.isSpeaking = true;
        // Le son commence ici, pas à la mise en file : premier recalage.
        this.events.onSpeechProgress?.(charBase);
        if (!suppressEvents) {
          this.events.onSpeakStart();
        }
      };

      // Frontières de mot (Chrome/Edge avec les voix locales, Firefox) :
      // `charIndex` est relatif au texte de CET énoncé, d'où l'offset.
      utterance.onboundary = (e) => {
        if (e.name === "word") {
          this.events.onSpeechProgress?.(charBase + e.charIndex);
        }
      };

      utterance.onend = () => {
        // Si `stop()`/`setMuted(true)` a déjà remis `isSpeaking` à `false`
        // (leur propre reset synchrone), cet événement arrive en retard sur
        // un énoncé déjà considéré terminé : ne pas re-notifier `onSpeakEnd`.
        const wasSpeaking = this.isSpeaking;
        this.isSpeaking = false;
        if (!suppressEvents && wasSpeaking) {
          this.events.onSpeakEnd();
        }
        resolve();
      };

      utterance.onerror = (e) => {
        // "canceled" is expected when we call speechSynthesis.cancel()
        if (e.error !== "canceled") {
          console.warn("TTS error:", e.error);
        }
        const wasSpeaking = this.isSpeaking;
        this.isSpeaking = false;
        if (!suppressEvents && wasSpeaking) {
          this.events.onSpeakEnd();
        }
        resolve();
      };

      speechSynthesis.speak(utterance);
    });
  }

  stop() {
    this.dropQueue();
    this.interruptEpoch++;
    speechSynthesis.cancel();
    this.forceSpeechEnded();
  }

  /**
   * Réinitialisation synchrone de l'état "parle", partagée par `stop()` et
   * `setMuted(true)` : après un `cancel()`, rien ne garantit que le
   * navigateur déclenche `onend`/`onerror` sur l'énoncé annulé. La garde
   * `if (this.isSpeaking)` fait aussi le travail inverse — si le navigateur
   * déclenche quand même l'événement (avant ou après cet appel), l'un des
   * deux trouve `isSpeaking` déjà à `false` et ne re-déclenche pas
   * `onSpeakEnd` une seconde fois (voir `speakTextChunk`, qui ne notifie
   * que si l'énoncé parlait encore juste avant).
   */
  private forceSpeechEnded() {
    if (this.isSpeaking) {
      this.isSpeaking = false;
      this.events.onSpeakEnd();
    }
  }

  getIsSpeaking(): boolean {
    return this.isSpeaking;
  }
}
