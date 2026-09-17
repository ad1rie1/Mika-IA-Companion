import { describe, expect, it } from "vitest";
import {
  SpeechPresenter,
  VOICED_HOLD_MAX_MS,
  WAKE_UP_DELAY_MS,
  WAKE_UP_WINDOW_MS,
  type BodyPort,
  type FacePort,
  type ReadoutsPort,
  type StagePort,
  type TimerPort,
  type VoicePort,
} from "../SpeechPresenter";
import type {
  EmotionBlend,
  EmotionName,
  EmotionUpdateMessage,
  SleepPhase,
  SpeechMessage,
  VoicePersona,
} from "../../types";

// ── Faux ──────────────────────────────────────────────────────────────

/** Une voix pilotée à la main : chaque `speak()` reste en vol jusqu'à ce
 * que le test le fasse commencer (`start`) puis le règle (`end`). */
class FakeVoice implements VoicePort {
  isMuted = false;
  calls: Array<{
    text: string;
    emotion: EmotionName;
    onStart?: () => void;
    settle: (o: "played" | "skipped") => void;
  }> = [];
  wakeUpDelays: number[] = [];
  /** Ce que `queuedCount` doit rapporter (la file derrière celle qui joue). */
  queued = 0;

  get queuedCount() {
    return this.queued;
  }
  speak(text: string, emotion: EmotionName, _p: unknown, hooks: { onStart?: () => void }) {
    return new Promise<"played" | "skipped">((settle) => {
      this.calls.push({ text, emotion, onStart: hooks.onStart, settle });
    });
  }
  requestWakeUpDelay(ms: number) {
    this.wakeUpDelays.push(ms);
  }
  start(i: number) {
    this.calls[i].onStart?.();
  }
  end(i: number, outcome: "played" | "skipped" = "played") {
    this.calls[i].settle(outcome);
  }
}

interface AvatarCall {
  emotion: EmotionName;
  intensity: number;
  blend: EmotionBlend;
  persona: VoicePersona | undefined;
  ambient: boolean;
}

class FakeBody implements BodyPort {
  emotions: AvatarCall[] = [];
  speaking: boolean[] = [];
  replyPending: boolean[] = [];
  typing = 0;
  sleepPhases: SleepPhase[] = [];
  setEmotion(
    emotion: EmotionName,
    intensity: number,
    blend: EmotionBlend,
    persona: VoicePersona | undefined,
    opts: { ambient?: boolean }
  ) {
    this.emotions.push({ emotion, intensity, blend, persona, ambient: opts.ambient === true });
  }
  setSpeaking(s: boolean) {
    this.speaking.push(s);
  }
  setReplyPending(p: boolean) {
    this.replyPending.push(p);
  }
  noteUserTyping() {
    this.typing++;
  }
  setSleepPhase(phase: SleepPhase) {
    this.sleepPhases.push(phase);
  }
}

class FakeFace implements FacePort {
  emotions: Array<[EmotionName, number]> = [];
  setEmotion(emotion: EmotionName, intensity: number) {
    this.emotions.push([emotion, intensity]);
  }
}

class FakeStage implements StagePort {
  sleepPhases: SleepPhase[] = [];
  setSleepPhase(phase: SleepPhase) {
    this.sleepPhases.push(phase);
  }
}

class FakeReadouts implements ReadoutsPort {
  emotions: Array<[EmotionName, number]> = [];
  blends: Array<[EmotionBlend, number]> = [];
  innerStates: unknown[] = [];
  setEmotion(emotion: EmotionName, intensity: number) {
    this.emotions.push([emotion, intensity]);
  }
  setEmotionBlend(blend: EmotionBlend, intensity: number) {
    this.blends.push([blend, intensity]);
  }
  applyInnerState(state: unknown) {
    this.innerStates.push(state);
  }
}

/** Minuteries à la main, lues contre l'horloge du test. */
class FakeTimers implements TimerPort {
  pending: Array<{ id: number; fn: () => void; at: number }> = [];
  private seq = 0;
  constructor(private readonly now: () => number) {}
  set(fn: () => void, ms: number) {
    const id = ++this.seq;
    this.pending.push({ id, fn, at: this.now() + ms });
    return id;
  }
  clear(handle: unknown) {
    this.pending = this.pending.filter((t) => t.id !== handle);
  }
  /** Tire tout ce qui est échu à l'horloge courante. */
  fireDue() {
    const due = this.pending.filter((t) => t.at <= this.now());
    this.pending = this.pending.filter((t) => t.at > this.now());
    for (const t of due) t.fn();
  }
}

function harness() {
  let clock = 1_000;
  const now = () => clock;
  const voice = new FakeVoice();
  const body = new FakeBody();
  const face = new FakeFace();
  const stage = new FakeStage();
  const readouts = new FakeReadouts();
  const timers = new FakeTimers(now);
  const presenter = new SpeechPresenter({ voice, body, face, stage, readouts, now, timers });
  return {
    presenter,
    voice,
    body,
    face,
    stage,
    readouts,
    timers,
    advance(ms: number) {
      clock += ms;
      timers.fireDue();
    },
  };
}

const speech = (over: Partial<SpeechMessage> = {}): SpeechMessage => ({
  type: "speech",
  text: "Salut toi.",
  emotion: "excited",
  emotion_intensity: 0.8,
  emotion_blend: [{ emotion: "excited", weight: 0.8 }],
  voice_persona: "speaking",
  ...over,
});

const drift = (emotion: string, intensity = 0.4): EmotionUpdateMessage => ({
  type: "emotion_update",
  emotion,
  emotion_intensity: intensity,
  emotion_blend: [],
});

// Les micro-tâches de `.then().finally()` — quelques tours suffisent.
const flush = async () => {
  for (let i = 0; i < 4; i++) await Promise.resolve();
};

// ── La voix possède le visage ─────────────────────────────────────────

describe("SpeechPresenter — une réponse vocalisée", () => {
  it("met les afficheurs à jour à la trame, l'avatar au début réel de l'énoncé", () => {
    const h = harness();
    h.presenter.handleSpeech(speech());

    expect(h.readouts.emotions).toEqual([["excited", 0.8]]);
    expect(h.readouts.blends).toHaveLength(1);
    expect(h.body.emotions).toEqual([]);
    expect(h.face.emotions).toEqual([]);
    expect(h.voice.calls).toHaveLength(1);

    h.voice.start(0);
    expect(h.face.emotions).toEqual([["excited", 0.8]]);
    expect(h.body.emotions).toEqual([
      {
        emotion: "excited",
        intensity: 0.8,
        blend: [{ emotion: "excited", weight: 0.8 }],
        persona: "speaking",
        ambient: false,
      },
    ]);
  });

  it("une réponse jamais jouée (`skipped`) montre quand même son émotion", async () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.end(0, "skipped");
    await flush();
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited"]);
    expect(h.face.emotions).toEqual([["excited", 0.8]]);
  });

  it("une réponse jouée n'est montrée qu'une fois (onStart, pas la promesse)", async () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.start(0);
    h.voice.end(0, "played");
    await flush();
    expect(h.body.emotions).toHaveLength(1);
  });

  it("`speak: false` applique l'émotion immédiatement, sans appeler la voix", () => {
    const h = harness();
    h.presenter.handleSpeech(speech({ speak: false }));
    expect(h.voice.calls).toEqual([]);
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited"]);
  });

  it("muet ou sans texte : idem, immédiat et sans voix", () => {
    const h = harness();
    h.voice.isMuted = true;
    h.presenter.handleSpeech(speech());
    h.voice.isMuted = false;
    h.presenter.handleSpeech(speech({ text: "" }));
    expect(h.voice.calls).toEqual([]);
    expect(h.body.emotions).toHaveLength(2);
  });

  it("une émotion inconnue vaut neutral, une intensité absente 0.7", () => {
    const h = harness();
    h.presenter.handleSpeech(
      speech({ speak: false, emotion: "ecstatic", emotion_intensity: undefined })
    );
    expect(h.readouts.emotions).toEqual([["neutral", 0.7]]);
    expect(h.body.emotions[0].emotion).toBe("neutral");
  });

  it("clôt le regard « je réfléchis » dès la trame, avant la voix", () => {
    const h = harness();
    h.presenter.handleAck({ type: "ack", client_msg_id: "c1", status: "accepted" });
    h.presenter.handleSpeech(speech());
    expect(h.body.replyPending).toEqual([true, false]);
  });
});

// ── La dérive retenue ─────────────────────────────────────────────────

describe("SpeechPresenter — la dérive pendant une voix en vol", () => {
  it("est retenue, la plus récente gagne, appliquée en ambient quand la voix se tait", () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.start(0);

    h.presenter.handleEmotionUpdate(drift("curious", 0.3));
    h.presenter.handleEmotionUpdate(drift("amused", 0.5));
    // Les afficheurs suivent la trame ; l'avatar reste sur la réponse.
    expect(h.readouts.emotions.map((e) => e[0])).toEqual(["excited", "curious", "amused"]);
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited"]);

    h.presenter.handleSpeakEnd();
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "amused"]);
    expect(h.body.emotions[1]).toMatchObject({ ambient: true, persona: undefined, intensity: 0.5 });
    expect(h.face.emotions[h.face.emotions.length - 1]).toEqual(["amused", 0.5]);
  });

  it("est aussi relâchée par la promesse de speak() (l'autre chemin de fin)", async () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.start(0);
    h.presenter.handleEmotionUpdate(drift("bored"));
    h.voice.end(0);
    await flush();
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "bored"]);
  });

  it("reste retenue tant qu'une réplique attend derrière (queuedCount > 0)", () => {
    const h = harness();
    h.presenter.handleSpeech(speech({ text: "un" }));
    h.presenter.handleSpeech(speech({ text: "deux", emotion: "happy" }));
    h.voice.start(0);
    h.presenter.handleEmotionUpdate(drift("bored"));

    h.voice.queued = 1;
    h.presenter.handleSpeakEnd(); // fin de « un », « deux » attend
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited"]);

    h.voice.start(1);
    h.voice.queued = 0;
    h.presenter.handleSpeakEnd();
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "happy", "bored"]);
  });

  it("une nouvelle réponse supplante la dérive qui attendait", () => {
    const h = harness();
    h.presenter.handleSpeech(speech({ text: "un" }));
    h.voice.start(0);
    h.presenter.handleEmotionUpdate(drift("bored"));
    h.presenter.handleSpeech(speech({ text: "deux", emotion: "happy" }));
    h.voice.start(1);
    h.presenter.handleSpeakEnd();
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "happy"]);
  });

  it("sans voix en vol, la dérive s'applique tout de suite, par le même chemin, en ambient", () => {
    const h = harness();
    h.presenter.handleEmotionUpdate({
      type: "emotion_update",
      emotion: "curious",
      emotion_intensity: 0.35,
      emotion_blend: [{ emotion: "curious", weight: 0.6 }],
    });
    expect(h.face.emotions).toEqual([["curious", 0.35]]);
    expect(h.body.emotions).toEqual([
      {
        emotion: "curious",
        intensity: 0.35,
        blend: [{ emotion: "curious", weight: 0.6 }],
        persona: undefined,
        ambient: true,
      },
    ]);
    expect(h.readouts.blends).toEqual([[[{ emotion: "curious", weight: 0.6 }], 0.35]]);
  });

  it("une dérive au nom inconnu est ignorée en entier", () => {
    const h = harness();
    h.presenter.handleEmotionUpdate(drift("ecstatic"));
    expect(h.readouts.emotions).toEqual([]);
    expect(h.body.emotions).toEqual([]);
  });

  it("une dérive sans intensité vaut 0", () => {
    const h = harness();
    h.presenter.handleEmotionUpdate({ type: "emotion_update", emotion: "sad" });
    expect(h.body.emotions[0]).toMatchObject({ emotion: "sad", intensity: 0, blend: [] });
  });
});

// ── La soupape ────────────────────────────────────────────────────────

describe("SpeechPresenter — VOICED_HOLD_MAX_MS", () => {
  it("passé le délai, une nouvelle dérive n'est plus retenue même sans onend", () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.start(0);
    h.advance(VOICED_HOLD_MAX_MS - 1);
    h.presenter.handleEmotionUpdate(drift("bored"));
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited"]);

    // À l'échéance, la dérive retenue est relâchée, puis la suivante passe
    // directement : la voix ne possède plus le visage.
    h.advance(1);
    h.presenter.handleEmotionUpdate(drift("sad"));
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "bored", "sad"]);
  });

  it("à l'échéance, la dérive déjà retenue est relâchée d'elle-même", () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.start(0);
    h.presenter.handleEmotionUpdate(drift("bored"));
    h.advance(VOICED_HOLD_MAX_MS - 1);
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited"]);
    h.advance(1);
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "bored"]);
    expect(h.body.emotions[1].ambient).toBe(true);
  });

  it("la voix qui se tait à temps désarme la minuterie", async () => {
    const h = harness();
    h.presenter.handleSpeech(speech());
    h.voice.start(0);
    h.voice.end(0);
    await flush();
    expect(h.timers.pending).toEqual([]);
  });

  it("le délai court depuis la PREMIÈRE réplique en vol, pas la dernière", () => {
    const h = harness();
    h.presenter.handleSpeech(speech({ text: "un" }));
    h.voice.start(0);
    h.advance(VOICED_HOLD_MAX_MS - 10);
    h.presenter.handleSpeech(speech({ text: "deux" }));
    h.advance(10);
    h.presenter.handleEmotionUpdate(drift("sad"));
    expect(h.body.emotions.map((e) => e.emotion)).toEqual(["excited", "sad"]);
  });
});

// ── Réveil et sommeil ─────────────────────────────────────────────────

describe("SpeechPresenter — réveil", () => {
  it("dormait il y a moins de dix secondes : un silence de réveil, une seule fois", () => {
    const h = harness();
    h.presenter.setSleepPhase("deep_sleep");
    h.advance(WAKE_UP_WINDOW_MS - 1);
    h.presenter.setSleepPhase("awake");
    h.presenter.handleSpeech(speech({ text: "un" }));
    h.presenter.handleSpeech(speech({ text: "deux" }));
    expect(h.voice.wakeUpDelays).toEqual([WAKE_UP_DELAY_MS]);
  });

  it("dormait il y a plus de dix secondes : pas de silence", () => {
    const h = harness();
    h.presenter.setSleepPhase("rem");
    h.advance(WAKE_UP_WINDOW_MS);
    h.presenter.handleSpeech(speech());
    expect(h.voice.wakeUpDelays).toEqual([]);
  });

  it("n'a jamais dormi : pas de silence", () => {
    const h = harness();
    h.presenter.setSleepPhase("awake");
    h.presenter.handleSpeech(speech());
    expect(h.voice.wakeUpDelays).toEqual([]);
  });

  it("une phase propage vers le corps et la scène ; une inconnue vaut awake", () => {
    const h = harness();
    h.presenter.setSleepPhase("light_sleep");
    expect(() => h.presenter.setSleepPhase("dormant")).not.toThrow();
    expect(h.body.sleepPhases).toEqual(["light_sleep", "awake"]);
    expect(h.stage.sleepPhases).toEqual(["light_sleep", "awake"]);
  });

  it("une phase inconnue ne compte pas comme un sommeil", () => {
    const h = harness();
    h.presenter.setSleepPhase("dormant");
    h.presenter.handleSpeech(speech());
    expect(h.voice.wakeUpDelays).toEqual([]);
  });

  it("une trame speech au payload douteux ne casse pas le handler", () => {
    const h = harness();
    expect(() =>
      h.presenter.handleSpeech({
        type: "speech",
        text: "…",
        emotion: 42 as unknown as string,
        emotion_intensity: "fort" as unknown as number,
        inner_state: { sleep_phase: "dormant" } as never,
      })
    ).not.toThrow();
    expect(h.voice.calls).toHaveLength(1);
    expect(h.readouts.innerStates).toHaveLength(1);
  });
});

// ── Signaux de conversation ───────────────────────────────────────────

describe("SpeechPresenter — signaux", () => {
  it("seul un ack `accepted` ouvre le regard « je réfléchis »", () => {
    const h = harness();
    h.presenter.handleAck({ type: "ack", client_msg_id: "a", status: "rate_limited" });
    h.presenter.handleAck({ type: "ack", client_msg_id: "b", status: "overloaded" });
    expect(h.body.replyPending).toEqual([]);
    h.presenter.handleAck({ type: "ack", client_msg_id: "c", status: "accepted" });
    expect(h.body.replyPending).toEqual([true]);
  });

  it("noteUserTyping et les bornes de la voix vont au corps", () => {
    const h = harness();
    h.presenter.noteUserTyping();
    h.presenter.handleSpeakStart();
    h.presenter.handleSpeakEnd();
    expect(h.body.typing).toBe(1);
    expect(h.body.speaking).toEqual([true, false]);
  });

  it("inner_state_update ne touche que les afficheurs", () => {
    const h = harness();
    h.presenter.handleInnerStateUpdate({ type: "inner_state_update", inner_state: undefined });
    expect(h.readouts.innerStates).toEqual([undefined]);
    expect(h.body.emotions).toEqual([]);
  });

  it("showEmotion (debug) touche avatar et afficheur, hors de toute voix", () => {
    const h = harness();
    h.presenter.showEmotion("proud", 0.9);
    expect(h.face.emotions).toEqual([["proud", 0.9]]);
    expect(h.body.emotions[0]).toMatchObject({ emotion: "proud", ambient: false });
    expect(h.readouts.emotions).toEqual([["proud", 0.9]]);
  });
});
