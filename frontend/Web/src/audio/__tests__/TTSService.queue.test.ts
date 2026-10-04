import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TTSService, utteranceDeadlineMs } from "../TTSService";
import { msPerCharForRate } from "../cadence";

/**
 * La soupape de la file. La Web Speech API ne garantit ni `onend` ni
 * `onerror` — y compris après le `cancel()` de `stop()`/`setMuted(true)` —
 * et `processQueue` attend la promesse de chaque morceau : un seul énoncé
 * muet suffisait à empiler tous les `speak()` suivants sans jamais les
 * dépiler, pour toute la session. Le faux navigateur ci-dessous ne
 * déclenche jamais rien tout seul : chaque test joue le navigateur à la
 * main, et surtout joue son silence.
 */
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
  const cancel = vi.fn();
  vi.stubGlobal("speechSynthesis", {
    getVoices: () => [],
    onvoiceschanged: undefined as (() => void) | undefined,
    speak: (u: FakeUtterance) => {
      spoken.push(u);
    },
    cancel,
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
  return { spoken, cancel };
}

function service() {
  const ended: number[] = [];
  const started: number[] = [];
  const tts = new TTSService({
    onSpeakStart: () => started.push(1),
    onSpeakEnd: () => ended.push(1),
  });
  return { tts, ended, started };
}

const flush = async () => {
  for (let i = 0; i < 4; i++) await Promise.resolve();
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("TTSService — stop()/setMuted(true) libèrent la file", () => {
  it("repro : un énoncé sans onend, stop(), puis speak() — le second est bien lancé", async () => {
    // Le défaut confirmé : après stop(), `speechSynthesis.speak` n'était
    // appelé qu'une fois, `processing` restant à true pour la session.
    const { spoken } = installSpeechStubs();
    const { tts } = service();
    const first = tts.speak("un");
    spoken[0].onstart?.();
    // Jamais de onend/onerror, même après cancel().
    tts.stop();
    await expect(first).resolves.toBe("played");

    const second = tts.speak("deux");
    await flush();
    expect(spoken).toHaveLength(2);
    expect(spoken[1].text).toBe("deux");
    spoken[1].onstart?.();
    spoken[1].onend?.();
    await expect(second).resolves.toBe("played");
  });

  it("setMuted(true) mid-énoncé résout ce qui n'a jamais sonné en `skipped`", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    // Remis au moteur, mais le navigateur n'a pas encore émis onstart.
    const pending = tts.speak("pas encore commencé");
    expect(spoken).toHaveLength(1);
    tts.setMuted(true);
    await expect(pending).resolves.toBe("skipped");
    // Rien ne parlait : pas de onSpeakEnd fantôme.
    expect(ended).toHaveLength(0);
    // La file est libre : démuter puis parler relance la synthèse.
    tts.setMuted(false);
    void tts.speak("après");
    await flush();
    expect(spoken).toHaveLength(2);
  });

  it("setMuted(true) sur un énoncé déjà démarré : `played` (coupé en route), un seul onSpeakEnd", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    const first = tts.speak("bonjour");
    spoken[0].onstart?.();
    tts.setMuted(true);
    await expect(first).resolves.toBe("played");
    expect(ended).toHaveLength(1);
    expect(tts.getIsSpeaking()).toBe(false);
  });

  it("un onend tardif après stop() ne résout pas deux fois ni ne re-notifie onSpeakEnd", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    const settled = vi.fn();
    void tts.speak("un").then(settled);
    spoken[0].onstart?.();
    tts.stop();
    await flush();
    expect(settled).toHaveBeenCalledTimes(1);
    expect(ended).toHaveLength(1);

    // Le navigateur finit par réagir au cancel(), en retard.
    spoken[0].onerror?.({ error: "canceled" });
    spoken[0].onend?.();
    await flush();
    expect(settled).toHaveBeenCalledTimes(1);
    expect(ended).toHaveLength(1);
    expect(tts.getIsSpeaking()).toBe(false);
  });

  it("un onstart tardif sur un énoncé abandonné ne rallume pas l'animation", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, started } = service();
    void tts.speak("un");
    tts.stop();
    await flush();
    spoken[0].onstart?.();
    expect(tts.getIsSpeaking()).toBe(false);
    expect(started).toHaveLength(0);
  });

  it("stop() pendant une réponse segmentée coupe la boucle et libère la file", async () => {
    const { spoken } = installSpeechStubs();
    const { tts } = service();
    const first = tts.speak("Bonjour [PAUSE:300] tout le monde");
    spoken[0].onstart?.();
    tts.stop();
    await expect(first).resolves.toBe("played");
    // Le segment « tout le monde » n'est jamais remis au moteur.
    await vi.advanceTimersByTimeAsync(1000);
    expect(spoken).toHaveLength(1);
    void tts.speak("suite");
    await flush();
    expect(spoken).toHaveLength(2);
    expect(spoken[1].text).toBe("suite");
  });
});

describe("TTSService — échéance par énoncé", () => {
  it("est bornée par la longueur du texte et le débit, avec ×2 + forfait", () => {
    expect(utteranceDeadlineMs("", 1)).toBe(5000);
    expect(utteranceDeadlineMs("abcdefghij", 1)).toBe(10 * msPerCharForRate(1) * 2 + 5000);
    // Un débit plus rapide raccourcit l'échéance, un plus lent l'allonge.
    expect(utteranceDeadlineMs("abcdefghij", 2)).toBeLessThan(utteranceDeadlineMs("abcdefghij", 1));
    expect(utteranceDeadlineMs("abcdefghij", 0.5)).toBeGreaterThan(utteranceDeadlineMs("abcdefghij", 1));
  });

  it("libère la file quand onend/onerror ne viennent jamais", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    const text = "une phrase que le moteur abandonne en silence";
    const first = tts.speak(text);
    const second = tts.speak("la suivante");
    spoken[0].onstart?.();
    expect(tts.getIsSpeaking()).toBe(true);

    const budget = utteranceDeadlineMs(text, spoken[0].rate);
    // Juste avant l'échéance : rien ne bouge.
    await vi.advanceTimersByTimeAsync(budget - 1);
    expect(spoken).toHaveLength(1);
    expect(tts.getIsSpeaking()).toBe(true);

    await vi.advanceTimersByTimeAsync(1);
    await expect(first).resolves.toBe("played");
    expect(ended).toHaveLength(1);
    expect(tts.getIsSpeaking()).toBe(false);
    // La suivante est partie toute seule.
    expect(spoken).toHaveLength(2);
    expect(spoken[1].text).toBe("la suivante");
    spoken[1].onstart?.();
    spoken[1].onend?.();
    await expect(second).resolves.toBe("played");
  });

  it("un énoncé que le moteur ne démarre jamais est clos `skipped` à l'échéance", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    const first = tts.speak("jamais démarré");
    await vi.advanceTimersByTimeAsync(utteranceDeadlineMs("jamais démarré", spoken[0].rate));
    await expect(first).resolves.toBe("skipped");
    expect(ended).toHaveLength(0);
  });

  it("un onend tardif après l'échéance ne fait rien", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    const settled = vi.fn();
    void tts.speak("tard").then(settled);
    spoken[0].onstart?.();
    await vi.advanceTimersByTimeAsync(utteranceDeadlineMs("tard", spoken[0].rate));
    await flush();
    expect(settled).toHaveBeenCalledTimes(1);
    expect(ended).toHaveLength(1);

    spoken[0].onend?.();
    await flush();
    expect(settled).toHaveBeenCalledTimes(1);
    expect(ended).toHaveLength(1);
  });

  it("le chemin normal (onend à l'heure) reste `played`, et l'échéance n'agit plus ensuite", async () => {
    const { spoken } = installSpeechStubs();
    const { tts, ended } = service();
    const first = tts.speak("à l'heure");
    spoken[0].onstart?.();
    spoken[0].onend?.();
    await expect(first).resolves.toBe("played");
    expect(ended).toHaveLength(1);
    // Le timer a été désarmé : bien après le budget, rien ne se re-déclenche.
    await vi.advanceTimersByTimeAsync(utteranceDeadlineMs("à l'heure", 1) * 3);
    expect(ended).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("l'échéance est réarmée au premier son : la latence de synthèse n'entame pas le budget", async () => {
    const { spoken } = installSpeechStubs();
    const { tts } = service();
    const text = "un texte assez long pour que ça compte vraiment";
    const first = tts.speak(text);
    const budget = utteranceDeadlineMs(text, spoken[0].rate);
    // Le moteur met presque tout le budget à démarrer…
    await vi.advanceTimersByTimeAsync(budget - 10);
    spoken[0].onstart?.();
    // …et dispose alors encore de tout le budget pour parler.
    await vi.advanceTimersByTimeAsync(budget - 10);
    expect(tts.getIsSpeaking()).toBe(true);
    spoken[0].onend?.();
    await expect(first).resolves.toBe("played");
  });
});
