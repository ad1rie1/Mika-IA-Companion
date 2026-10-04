import { afterEach, describe, expect, it, vi } from "vitest";
import { TTSService } from "../TTSService";

/**
 * Web Speech API minimale — juste ce que TTSService touche réellement
 * (initVoice / speakTextChunk / setMuted / stop). Ni jsdom ni navigateur :
 * `vi.stubGlobal` suffit et vitest désinstalle les stubs entre fichiers.
 * Le mock ne déclenche jamais `onstart`/`onend` tout seul — le test simule
 * le navigateur à la main, exactement comme une vraie synthèse le ferait
 * de façon asynchrone.
 */
class FakeUtterance {
  pitch = 1;
  rate = 1;
  volume = 1;
  voice: unknown = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  constructor(public text: string) {}
}

function installSpeechStubs() {
  const spoken: FakeUtterance[] = [];
  const cancel = vi.fn();
  const fakeSynthesis = {
    getVoices: () => [],
    onvoiceschanged: undefined as (() => void) | undefined,
    speak: (u: FakeUtterance) => {
      spoken.push(u);
    },
    cancel,
  };
  vi.stubGlobal("speechSynthesis", fakeSynthesis);
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TTSService.setMuted(true) — reset synchrone de isSpeaking", () => {
  it("coupe l'animation même si le navigateur ne déclenche jamais onend/onerror", () => {
    const { spoken } = installSpeechStubs();
    const ended: number[] = [];
    const tts = new TTSService({
      onSpeakStart: () => {},
      onSpeakEnd: () => ended.push(1),
    });

    void tts.speak("bonjour");
    // Le navigateur démarre réellement l'énoncé.
    spoken[0].onstart?.();
    expect(tts.getIsSpeaking()).toBe(true);

    tts.setMuted(true);

    // Le défaut confirmé : sans le reset synchrone, isSpeaking restait
    // bloqué à true et l'avatar continuait à parler visuellement.
    expect(tts.getIsSpeaking()).toBe(false);
    expect(ended).toHaveLength(1);
  });

  it("ne déclenche pas onSpeakEnd une seconde fois quand le navigateur finit par répondre", () => {
    const { spoken } = installSpeechStubs();
    const ended: number[] = [];
    const tts = new TTSService({
      onSpeakStart: () => {},
      onSpeakEnd: () => ended.push(1),
    });

    void tts.speak("bonjour");
    spoken[0].onstart?.();
    tts.setMuted(true);
    expect(ended).toHaveLength(1);

    // cancel() finit par faire réagir l'énoncé annulé, en retard.
    spoken[0].onerror?.({ error: "canceled" });
    expect(ended).toHaveLength(1);
  });

  it("ne fait rien si rien ne parlait", () => {
    installSpeechStubs();
    const ended: number[] = [];
    const tts = new TTSService({
      onSpeakStart: () => {},
      onSpeakEnd: () => ended.push(1),
    });

    tts.setMuted(true);
    expect(ended).toHaveLength(0);
  });
});

describe("TTSService — onUtteranceStart suit l'énoncé qui joue réellement", () => {
  it("le second texte n'attaque son plan qu'une fois le premier terminé", async () => {
    // Le défaut confirmé : main.ts appelait startFromPlan(text) à la
    // réception de CHAQUE frame `speech`, donc dès la mise en file — deux
    // répliques rapprochées faisaient articuler la bouche sur la seconde
    // pendant que l'audio de la première tournait encore. onUtteranceStart
    // ne doit se déclencher qu'au dépilement réel de chaque item.
    const { spoken } = installSpeechStubs();
    const started: string[] = [];
    const tts = new TTSService({
      onSpeakStart: () => {},
      onSpeakEnd: () => {},
      onUtteranceStart: (text) => started.push(text),
    });

    void tts.speak("premier");
    void tts.speak("deuxième");

    // "premier" est dépilé et parle déjà ; "deuxième" attend en file,
    // toujours dans le même tick synchrone.
    expect(started).toEqual(["premier"]);
    expect(spoken).toHaveLength(1);

    // L'énoncé "premier" se termine réellement.
    spoken[0].onstart?.();
    spoken[0].onend?.();
    // Laisse la boucle de la file reprendre (await côté processQueue).
    await Promise.resolve();
    await Promise.resolve();

    expect(started).toEqual(["premier", "deuxième"]);
    expect(spoken).toHaveLength(2);
    expect(spoken[1].text).toBe("deuxième");
  });
});
