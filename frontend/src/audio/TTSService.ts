import type { EmotionName, ProsodicCue, VoiceProfile } from "../types";

export type { VoiceProfile } from "../types";

const NEUTRAL_PROFILE: VoiceProfile = { pitch: 1.0, rate: 1.0, gain: 1.0 };

// Web Speech API accepts pitch in [0,2] and rate in [0.1,10]; the product of
// an emotion multiplier and a persona multiplier can leave that window.
const clampPitch = (v: number) => Math.max(0.1, Math.min(2, v));
const clampRate = (v: number) => Math.max(0.5, Math.min(2, v));

export interface TTSEvents {
  onSpeakStart: () => void;
  onSpeakEnd: () => void;
  onAudioData: (analyser: AnalyserNode) => void;
  /** Fired when a [SIGH]/[LAUGH]/[BREATH] token is reached, right
   * before its synthetic audio plays — so a body gesture can start in
   * sync with the sound. */
  onProsodicCue?: (cue: ProsodicCue) => void;
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
  private analyser: AnalyserNode | null = null;
  private events: TTSEvents;
  private preferredVoice: SpeechSynthesisVoice | null = null;
  private isSpeaking = false;
  private speechQueue: Array<{
    text: string;
    emotion: EmotionName;
    profile: VoiceProfile;
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
    | { type: "speech"; text: string }
    | { type: "pause"; ms: number }
    | { type: "sfx"; kind: "sigh" | "laugh" | "breath" }
  > {
    const TOKEN_RE = /\[(PAUSE(?::(\d+))?|SIGH|LAUGH|BREATH)\]/gi;
    const segments: Array<
      | { type: "speech"; text: string }
      | { type: "pause"; ms: number }
      | { type: "sfx"; kind: "sigh" | "laugh" | "breath" }
    > = [];

    let cursor = 0;
    let match: RegExpExecArray | null;
    while ((match = TOKEN_RE.exec(text)) !== null) {
      // Text before the token
      if (match.index > cursor) {
        const chunk = text.slice(cursor, match.index).trim();
        if (chunk) segments.push({ type: "speech", text: chunk });
      }
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
    if (cursor < text.length) {
      const chunk = text.slice(cursor).trim();
      if (chunk) segments.push({ type: "speech", text: chunk });
    }
    return segments;
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

    let rendered: Promise<void>;
    let budgetMs: number;
    switch (kind) {
      case "sigh":
        rendered = this.renderSigh(ctx, now);
        budgetMs = 600;
        break;
      case "laugh":
        rendered = this.renderLaugh(ctx, now);
        budgetMs = 900;
        break;
      case "breath":
        rendered = this.renderBreath(ctx, now);
        budgetMs = 350;
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

  private ensureAudioContext(): AudioContext {
    if (!this.audioContext) {
      this.audioContext = new AudioContext();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;
    }
    return this.audioContext;
  }

  getAnalyser(): AnalyserNode | null {
    return this.analyser;
  }

  /**
   * Mute switch. Muting drops queued utterances and cuts the current one
   * short (speechSynthesis.cancel() fires the utterance's end event, so
   * onSpeakEnd/lip-sync teardown still run). Unmuting only affects future
   * replies.
   */
  setMuted(muted: boolean) {
    this.muted = muted;
    if (muted) {
      this.speechQueue.length = 0;
      this.nextPreDelayMs = 0;
      this.interruptEpoch++;
      if ("speechSynthesis" in window) {
        speechSynthesis.cancel();
      }
    }
  }

  get isMuted(): boolean {
    return this.muted;
  }

  private muted = false;

  // Jeton d'interruption, incrémenté par `setMuted(true)` et par `stop()`.
  // `speechSynthesis.cancel()` ne tue que l'énoncé en cours, jamais la boucle
  // qui enchaîne les segments : le chemin segmenté capture donc cette valeur
  // et abandonne les segments restants dès qu'elle change.
  private interruptEpoch = 0;

  async speak(
    text: string,
    emotion: EmotionName = "neutral",
    profile: VoiceProfile = NEUTRAL_PROFILE
  ) {
    if (this.muted) return;
    this.speechQueue.push({ text, emotion, profile });
    if (!this.processing) {
      this.processQueue();
    }
  }

  private async processQueue() {
    this.processing = true;

    while (this.speechQueue.length > 0) {
      const item = this.speechQueue.shift()!;
      await this.speakImmediate(item.text, item.emotion, item.profile);
    }

    this.processing = false;
  }

  private async speakImmediate(
    text: string,
    emotion: EmotionName,
    profile: VoiceProfile = NEUTRAL_PROFILE
  ): Promise<void> {
    this.activeProfile = profile;
    // Consume any pending wake-up delay before the actual utterance.
    // Drained here (not in processQueue) so back-to-back speeches within
    // a single response don't keep re-delaying.
    if (this.nextPreDelayMs > 0) {
      const delay = this.nextPreDelayMs;
      this.nextPreDelayMs = 0;
      await new Promise((r) => setTimeout(r, delay));
    }

    // Parse non-verbal tokens and handle the segmented path if any are
    // present. Fall through to the single-utterance path when the text
    // is clean speech (common case — avoids adding latency to every reply).
    const hasTokens = /\[(PAUSE(?::\d+)?|SIGH|LAUGH|BREATH)\]/i.test(text);
    if (hasTokens) {
      await this.speakSegmented(text, emotion);
      return;
    }
    await this.speakTextChunk(text, emotion);
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
        await this.speakTextChunk(seg.text, emotion, /*suppressEvents*/ true);
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
    suppressEvents = false
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

      // Connect to Web Audio API for analysis
      const ctx = this.ensureAudioContext();
      if (ctx.state === "suspended") {
        ctx.resume();
      }

      utterance.onstart = () => {
        this.isSpeaking = true;
        if (!suppressEvents) {
          this.events.onSpeakStart();
        }

        // NOTE: do NOT emit onAudioData here. The Web Speech API gives no
        // access to its audio stream, so nothing is ever connected into
        // `this.analyser` — handing it out switched the LipSyncController to
        // its audio-driven branch, where getByteFrequencyData() returns
        // silence and the mouth never moved at all. The text-driven
        // estimation started by the caller is the working path; onAudioData
        // is reserved for a future TTS that returns real audio buffers.
      };

      utterance.onend = () => {
        this.isSpeaking = false;
        if (!suppressEvents) {
          this.events.onSpeakEnd();
        }
        resolve();
      };

      utterance.onerror = (e) => {
        // "canceled" is expected when we call speechSynthesis.cancel()
        if (e.error !== "canceled") {
          console.warn("TTS error:", e.error);
        }
        this.isSpeaking = false;
        if (!suppressEvents) {
          this.events.onSpeakEnd();
        }
        resolve();
      };

      speechSynthesis.speak(utterance);
    });
  }

  stop() {
    this.speechQueue = [];
    this.interruptEpoch++;
    speechSynthesis.cancel();
    if (this.isSpeaking) {
      this.isSpeaking = false;
      this.events.onSpeakEnd();
    }
  }

  getIsSpeaking(): boolean {
    return this.isSpeaking;
  }
}
