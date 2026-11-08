import { describe, expect, it, vi } from "vitest";
import { EMPTY_MIKA, withInnerState, withMood, type MikaState } from "./state";
import {
  doingWords,
  faceOf,
  facetHtml,
  facetsOf,
  percent,
  projectHtml,
  promiseHtml,
  startVrmWhenShown,
  statusLine,
  type MediaWatch,
} from "./view";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();

function mika(inner: object, mood?: object): MikaState {
  const s = withInnerState(EMPTY_MIKA, inner);
  return mood ? withMood(s, mood) : s;
}

describe("statusLine", () => {
  const working = mika(
    { sleep_phase: "awake", place: "desk", activity: { name: "work", label: "travailler", until: null } },
    { emotion: "curious", emotion_intensity: 0.62 },
  );

  it("dit ce qu'elle fait, où, et son humeur — la pastille sans « éveillée »", () => {
    const line = statusLine(working, { link: "connected", typing: false, nowMs: NOW });
    expect(line.full).toBe("éveillée · travaille à son bureau · curieuse");
    expect(line.short).toBe("travaille à son bureau · curieuse");
    expect(line.state).toBe("eveillee");
  });

  it("endormie : « dort », sans rien d'autre", () => {
    const asleep = mika({ sleep_phase: "light_sleep", place: "bed" });
    expect(statusLine(asleep, { link: "connected", typing: false, nowMs: NOW })).toEqual({
      full: "dort",
      short: "dort",
      state: "dort",
    });
    expect(statusLine(mika({ sleep_phase: "rem" }), { link: "connected", typing: false, nowMs: NOW }).short).toBe("dort · rêve");
  });

  it("elle écrit : « en train d'écrire… » à la place de ce qu'elle fait", () => {
    const line = statusLine(working, { link: "connected", typing: true, nowMs: NOW });
    expect(line.short).toBe("en train d'écrire… · curieuse");
    expect(line.state).toBe("ecrit");
  });

  it("un problème de lien passe avant tout", () => {
    expect(statusLine(working, { link: "offline", typing: true, nowMs: NOW }).short).toBe("hors ligne");
    expect(statusLine(working, { link: "connecting", typing: false, nowMs: NOW }).full).toBe("connexion…");
    expect(statusLine(working, { link: "unauthorized", typing: false, nowMs: NOW }).short).toBe("session expirée");
  });

  it("une humeur légère ou neutre ne se dit pas ; rien d'autre : « éveillée »", () => {
    const calm = mika({ sleep_phase: "awake" }, { emotion: "happy", emotion_intensity: 0.1 });
    expect(statusLine(calm, { link: "connected", typing: false, nowMs: NOW })).toMatchObject({ full: "éveillée", short: "éveillée" });
  });
});

describe("doingWords", () => {
  it("une occupation inconnue se dit avec le libellé du serveur", () => {
    expect(doingWords(mika({ activity: { name: "juggle", label: "jongler", until: null } }), NOW)).toBe("en train de jongler");
    expect(doingWords(mika({ activity: { name: "x", label: "écouter la pluie", until: null } }), NOW)).toBe("en train d'écouter la pluie");
  });

  it("une occupation minutée s'éteint passé sa fin prévue", () => {
    const s = mika({ place: "window", activity: { name: "look_outside", label: "regarder dehors", until: NOW - 1000 } });
    expect(doingWords(s, NOW)).toBe("à la fenêtre");
    expect(doingWords(s, NOW - 5000)).toBe("regarde dehors à la fenêtre");
  });
});

describe("facetsOf", () => {
  it("le mélange, du plus fort au plus faible, quatre au plus, libellés français", () => {
    const s = mika({}, {
      emotion: "curious",
      emotion_intensity: 0.62,
      emotion_blend: [
        { emotion: "anxious", weight: 0.08 },
        { emotion: "curious", weight: 0.62 },
        { emotion: "thinking", weight: 0.22 },
        { emotion: "happy", weight: 0.41 },
        { emotion: "sad", weight: 0.05 },
        { emotion: "curious", weight: 0.3 },
      ],
    });
    expect(facetsOf(s.mood).map((f) => [f.label, f.value])).toEqual([
      ["Curieuse", 0.62],
      ["Contente", 0.41],
      ["Réfléchit…", 0.22],
      ["Anxieuse", 0.08],
    ]);
  });

  it("sans mélange, l'émotion seule ; sans humeur, rien", () => {
    expect(facetsOf(mika({}, { emotion: "sad", emotion_intensity: 0.5 }).mood)).toEqual([
      { emotion: "sad", label: "Triste", value: 0.5 },
    ]);
    expect(facetsOf(null)).toEqual([]);
    expect(facetsOf(mika({}, { emotion: "neutral", emotion_intensity: 0 }).mood)).toEqual([]);
  });

  it("percent arrondit et borne", () => {
    expect(percent(0.624)).toBe("62 %");
    expect(percent(1.4)).toBe("100 %");
    expect(percent(-1)).toBe("0 %");
  });
});

describe("faceOf", () => {
  const all = new Set(["neutral", "sleep", "thinking", "tired", "curious", "sad", "happy"]);

  it("endormie, puis elle écrit, puis son humeur marquée", () => {
    expect(faceOf(mika({ sleep_phase: "deep_sleep" }, { emotion: "happy", emotion_intensity: 0.9 }), true, all)).toEqual({
      portrait: "sleep",
      aura: "nuit",
      asleep: true,
    });
    expect(faceOf(mika({}, { emotion: "happy", emotion_intensity: 0.9 }), true, all).portrait).toBe("thinking");
    expect(faceOf(mika({}, { emotion: "curious", emotion_intensity: 0.6 }), false, all)).toEqual({
      portrait: "curious",
      aura: "crepuscule",
      asleep: false,
    });
    expect(faceOf(mika({}, { emotion: "sad", emotion_intensity: 0.6 }), false, all).aura).toBe("froide");
    expect(faceOf(mika({}, { emotion: "happy", emotion_intensity: 0.6 }), false, all).aura).toBe("chaude");
  });

  it("fatiguée : « tired », sauf une émotion forte", () => {
    expect(faceOf(mika({ energy: 0.2 }, { emotion: "happy", emotion_intensity: 0.3 }), false, all).portrait).toBe("tired");
    expect(faceOf(mika({ energy: 0.2 }, { emotion: "happy", emotion_intensity: 0.7 }), false, all).portrait).toBe("happy");
  });

  it("une humeur légère, ou un portrait absent, montre le neutre", () => {
    expect(faceOf(mika({}, { emotion: "happy", emotion_intensity: 0.1 }), false, all).portrait).toBe("neutral");
    expect(faceOf(mika({}, { emotion: "jealous", emotion_intensity: 0.8 }), false, all).portrait).toBe("neutral");
    // sans manifeste, on ne sait pas ce qui manque : l'humeur telle quelle
    expect(faceOf(mika({}, { emotion: "jealous", emotion_intensity: 0.8 }), false, null).portrait).toBe("jealous");
  });
});

describe("les lignes de « Ce qu'elle fait » et de sa colonne du chat", () => {
  it("une facette : son nom échappé, sa barre et son nombre bornés de même", () => {
    expect(facetHtml({ emotion: "curious", label: "Curieuse <b>", value: 0.624 })).toBe(
      '<div class="facet"><span>Curieuse &lt;b&gt;</span><span class="bar"><i style="width:62%"></i></span><span class="num">62 %</span></div>',
    );
    expect(facetHtml({ emotion: "happy", label: "Contente", value: 1.4 })).toContain('style="width:100%"');
    expect(facetHtml({ emotion: "happy", label: "Contente", value: 1.4 })).toContain("100 %");
  });

  it("une promesse, échappée", () => {
    const html = promiseHtml("t'envoyer <la liste>");
    expect(html).toContain('<div class="sc-line">');
    expect(html).toContain("<span>t&#39;envoyer &lt;la liste&gt;</span>");
  });

  it("un projet : son statut en mots ; un statut inconnu n'a pas d'étiquette, jamais la clé anglaise", () => {
    expect(projectHtml({ title: "Labo de trading", status: "paused" })).toContain('Labo de trading <span class="tag">en pause</span>');
    expect(projectHtml({ title: "Site de rando", status: "active" })).toContain('<span class="tag">en cours</span>');
    const unknown = projectHtml({ title: "Le <grenier>", status: "archived" });
    expect(unknown).toContain("<span>Le &lt;grenier&gt;</span>");
    expect(unknown).not.toContain("tag");
    expect(unknown).not.toContain("archived");
    expect(projectHtml({ title: "Vide", status: "" })).not.toContain("tag");
  });
});

describe("sa VRM ne se charge que si son coin se voit", () => {
  /** Une requête média qu'on fait changer à la main. */
  function media(narrow: boolean): MediaWatch & { set(narrow: boolean): void; listeners: Set<() => void> } {
    const listeners = new Set<() => void>();
    const m = {
      matches: narrow,
      listeners,
      addEventListener: (_type: "change", fn: () => void) => listeners.add(fn),
      removeEventListener: (_type: "change", fn: () => void) => listeners.delete(fn),
      set(next: boolean) {
        m.matches = next;
        for (const fn of [...listeners]) fn();
      },
    };
    return m;
  }

  it("sur un grand écran, tout de suite", () => {
    const start = vi.fn();
    startVrmWhenShown("", media(false), start);
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("sur un téléphone, rien ; la fenêtre élargie, une seule fois", () => {
    const start = vi.fn();
    const m = media(true);
    startVrmWhenShown("?theme=dark", m, start);
    expect(start).not.toHaveBeenCalled();
    m.set(true);
    expect(start).not.toHaveBeenCalled();
    m.set(false);
    expect(start).toHaveBeenCalledTimes(1);
    m.set(true);
    m.set(false);
    expect(start).toHaveBeenCalledTimes(1);
    expect(m.listeners.size).toBe(0);
  });

  it("?vrm=0 la coupe partout", () => {
    const start = vi.fn();
    const m = media(true);
    startVrmWhenShown("?vrm=0", media(false), start);
    startVrmWhenShown("?vrm=0", m, start);
    m.set(false);
    expect(start).not.toHaveBeenCalled();
  });
});
