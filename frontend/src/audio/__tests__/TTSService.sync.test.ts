import { afterEach, describe, expect, it, vi } from "vitest";
import { TTSService } from "../TTSService";

class FakeUtterance {
  pitch = 1;
  rate = 1;
  volume = 1;
  voice: unknown = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onboundary: ((e: { name: string; charIndex: number }) => void) | null = null;
  constructor(public text: string) {}
}

function installSpeechStubs() {
  const spoken: FakeUtterance[] = [];
  vi.stubGlobal("speechSynthesis", {
    getVoices: () => [],
    onvoiceschanged: undefined as (() => void) | undefined,
    speak: (u: FakeUtterance) => {
      spoken.push(u);
    },
    cancel: vi.fn(),
  });
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  vi.stubGlobal("window", globalThis);
  vi.stubGlobal(
    "AudioContext",
    class {
      state = "running";
      resume() {
        return Promise.resolve();
      }
    }
  );
  return { spoken };
}

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TTSService.speak — hooks and outcome", () => {
  it("onStart fires at dequeue, the promise resolves 'played' when the voice ends", async () => {
    const { spoken } = installSpeechStubs();
    const tts = new TTSService({ onSpeakStart: () => {}, onSpeakEnd: () => {} });
    let started = 0;
    const outcome = tts.speak("bonjour", "neutral", undefined, { onStart: () => started++ });
    expect(started).toBe(1);
    spoken[0].onstart?.();
    spoken[0].onend?.();
    await expect(outcome).resolves.toBe("played");
  });

  it("the second reply's onStart waits for the first to finish", async () => {
    const { spoken } = installSpeechStubs();
    const tts = new TTSService({ onSpeakStart: () => {}, onSpeakEnd: () => {} });
    const started: string[] = [];
    void tts.speak("premier", "neutral", undefined, { onStart: () => started.push("premier") });
    void tts.speak("deuxième", "neutral", undefined, { onStart: () => started.push("deuxième") });
    expect(started).toEqual(["premier"]);
    spoken[0].onstart?.();
    spoken[0].onend?.();
    await flush();
    expect(started).toEqual(["premier", "deuxième"]);
  });

  it("muting drops the queue: the queued reply resolves 'skipped' and never started", async () => {
    const { spoken } = installSpeechStubs();
    const tts = new TTSService({ onSpeakStart: () => {}, onSpeakEnd: () => {} });
    let secondStarted = false;
    const first = tts.speak("premier");
    const second = tts.speak("deuxième", "neutral", undefined, {
      onStart: () => {
        secondStarted = true;
      },
    });
    spoken[0].onstart?.();
    tts.setMuted(true);
    await expect(second).resolves.toBe("skipped");
    expect(secondStarted).toBe(false);
    // The one in flight was cancelled by the browser, late — still settles.
    spoken[0].onerror?.({ error: "canceled" });
    await expect(first).resolves.toBe("played");
  });

  it("speaking while muted resolves 'skipped' immediately", async () => {
    installSpeechStubs();
    const tts = new TTSService({ onSpeakStart: () => {}, onSpeakEnd: () => {} });
    tts.setMuted(true);
    await expect(tts.speak("rien")).resolves.toBe("skipped");
  });

  it("stop() settles what was queued", async () => {
    const { spoken } = installSpeechStubs();
    const tts = new TTSService({ onSpeakStart: () => {}, onSpeakEnd: () => {} });
    void tts.speak("premier");
    const second = tts.speak("deuxième");
    spoken[0].onstart?.();
    tts.stop();
    await expect(second).resolves.toBe("skipped");
  });
});

describe("TTSService — what the lip-sync is told", () => {
  it("onUtteranceStart carries the effective rate (emotion × persona)", () => {
    installSpeechStubs();
    const rates: number[] = [];
    const tts = new TTSService({
      onSpeakStart: () => {},
      onSpeakEnd: () => {},
      onUtteranceStart: (_text, rate) => rates.push(rate),
    });
    void tts.speak("vite", "excited");
    expect(rates[0]).toBeCloseTo(1.15, 5);
    expect(tts.effectiveRate("excited", { pitch: 1, rate: 0.9, gain: 1 })).toBeCloseTo(1.035, 5);
  });

  it("onSpeechProgress: index 0 when the sound starts, then each word boundary", () => {
    const { spoken } = installSpeechStubs();
    const progress: number[] = [];
    const tts = new TTSService({
      onSpeakStart: () => {},
      onSpeakEnd: () => {},
      onSpeechProgress: (i) => progress.push(i),
    });
    void tts.speak("bonjour tout le monde");
    spoken[0].onstart?.();
    spoken[0].onboundary?.({ name: "word", charIndex: 8 });
    spoken[0].onboundary?.({ name: "sentence", charIndex: 0 }); // ignored
    spoken[0].onboundary?.({ name: "word", charIndex: 13 });
    expect(progress).toEqual([0, 8, 13]);
  });

  it("the lip-sync plan carries each spoken chunk's start in the full text", () => {
    installSpeechStubs();
    const tts = new TTSService({ onSpeakStart: () => {}, onSpeakEnd: () => {} });
    expect(tts.lipSyncPlan("Bonjour [SIGH] tout le monde")).toEqual([
      { type: "speech", text: "Bonjour", start: 0 },
      { type: "silence", ms: 600 },
      { type: "speech", text: "tout le monde", start: 15 },
    ]);
    expect(tts.lipSyncPlan("  Salut")).toEqual([{ type: "speech", text: "Salut", start: 2 }]);
    expect(tts.lipSyncPlan("[PAUSE:300]Oui")).toEqual([
      { type: "silence", ms: 300 },
      { type: "speech", text: "Oui", start: 11 },
    ]);
  });
});
