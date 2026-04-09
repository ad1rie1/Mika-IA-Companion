import type { EmotionName } from "../vtuber/EmotionController";

export interface TTSEvents {
  onSpeakStart: () => void;
  onSpeakEnd: () => void;
  onAudioData: (analyser: AnalyserNode) => void;
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
  private speechQueue: Array<{ text: string; emotion: EmotionName }> = [];
  private processing = false;

  constructor(events: TTSEvents) {
    this.events = events;
    this.initVoice();
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

  async speak(text: string, emotion: EmotionName = "neutral") {
    this.speechQueue.push({ text, emotion });
    if (!this.processing) {
      this.processQueue();
    }
  }

  private async processQueue() {
    this.processing = true;

    while (this.speechQueue.length > 0) {
      const item = this.speechQueue.shift()!;
      await this.speakImmediate(item.text, item.emotion);
    }

    this.processing = false;
  }

  private speakImmediate(text: string, emotion: EmotionName): Promise<void> {
    return new Promise((resolve) => {
      if (!text.trim()) {
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
      const voiceMod = EMOTION_VOICE[emotion] || EMOTION_VOICE.neutral;
      utterance.pitch = voiceMod.pitch;
      utterance.rate = voiceMod.rate;
      utterance.volume = 1.0;

      // Connect to Web Audio API for analysis
      const ctx = this.ensureAudioContext();
      if (ctx.state === "suspended") {
        ctx.resume();
      }

      utterance.onstart = () => {
        this.isSpeaking = true;
        this.events.onSpeakStart();

        // Try to capture audio for analysis via MediaStreamDestination
        // Web Speech API doesn't expose audio stream directly,
        // so we use a periodic amplitude check on the analyser
        if (this.analyser) {
          this.events.onAudioData(this.analyser);
        }
      };

      utterance.onend = () => {
        this.isSpeaking = false;
        this.events.onSpeakEnd();
        resolve();
      };

      utterance.onerror = (e) => {
        // "canceled" is expected when we call speechSynthesis.cancel()
        if (e.error !== "canceled") {
          console.warn("TTS error:", e.error);
        }
        this.isSpeaking = false;
        this.events.onSpeakEnd();
        resolve();
      };

      speechSynthesis.speak(utterance);
    });
  }

  stop() {
    this.speechQueue = [];
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
