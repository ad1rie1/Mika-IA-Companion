import type { VRM, VRMExpression, VRMExpressionManager } from "@pixiv/three-vrm";
import type { SpeechPlanSegment } from "../types";
import { rawName, registerRawMorphs } from "../vtuber/faceRig";

import { DEFAULT_MS_PER_CHAR, msPerCharForRate } from "./cadence";
import {
  VISEMES,
  VISEME_INDEX,
  frenchVisemeFrames,
  spokenLength,
  type Viseme,
  type VisemeFrame,
} from "./frenchVisemes";

// Ré-exportés : main.ts les importe d'ici, et l'arithmétique vit dans
// `cadence.ts` parce que TTSService en a besoin sans tirer three-vrm.
export { DEFAULT_MS_PER_CHAR, msPerCharForRate };

/**
 * Lip-sync : la bouche articule le français que la voix prononce.
 *
 * La Web Speech API ne donne aucun accès à son flux audio : la bouche est
 * pilotée depuis le texte (frenchVisemes.ts — graphème → phonème → visème),
 * recalée par `seekToChar` à chaque frontière de mot que la synthèse
 * annonce. Ce fichier ne fait que le rendu : coarticulation, plafond
 * d'ouverture, et écriture sur le visage.
 *
 * Deux sorties possibles, choisies visème par visème au chargement du
 * modèle :
 * - les 15 morphs VRChat `vrc.v_*` quand le modèle les porte (Perula oui),
 *   enregistrés comme expressions `raw:vrc.v_*` (faceRig.ts) — une vraie
 *   fermeture des lèvres sur « p », la lèvre sous les dents sur « f » ;
 * - sinon les 5 presets VRM (aa/ih/ou/ee/oh), via PRESET_FALLBACK, pour que
 *   n'importe quel modèle continue de parler.
 */

/** Morph VRChat d'un visème : `vrc.v_aa`, `vrc.v_pp`… */
export const vrcMorph = (viseme: Viseme): string => `vrc.v_${viseme.toLowerCase()}`;

/** Visèmes effectivement pilotés : `sil` est l'absence de tous les autres. */
const DRIVEN_VISEMES = VISEMES.filter((v) => v !== "sil");
export const VRC_VISEME_MORPHS: readonly string[] = DRIVEN_VISEMES.map(vrcMorph);

type MouthPreset = "aa" | "ih" | "ou" | "ee" | "oh";
const MOUTH_PRESETS: readonly MouthPreset[] = ["aa", "ih", "ou", "ee", "oh"];

/**
 * Repli sur les presets VRM. Une fermeture (`PP`) n'a pas de preset : c'est
 * la bouche au repos, que l'attaque rapide de la fermeture rend lisible entre
 * deux voyelles. Les voyelles plafonnent sous 1 : un preset est une forme
 * pleine, et les modèles génériques l'ont souvent généreuse.
 */
export const PRESET_FALLBACK: Readonly<Record<Viseme, Partial<Record<MouthPreset, number>>>> = {
  sil: {},
  PP: {},
  FF: { ih: 0.25 },
  TH: { ee: 0.2, aa: 0.1 },
  DD: { ih: 0.3, aa: 0.12 },
  kk: { aa: 0.3, ih: 0.15 },
  CH: { ou: 0.45, ih: 0.15 },
  SS: { ih: 0.35, ee: 0.25 },
  nn: { ih: 0.25, aa: 0.1 },
  RR: { ou: 0.25, aa: 0.15 },
  aa: { aa: 0.8 },
  E: { ee: 0.6, aa: 0.15 },
  ih: { ih: 0.7 },
  oh: { oh: 0.75 },
  ou: { ou: 0.75 },
};

// ── Coarticulation ──────────────────────────────────────────────────
// On ne passe pas d'une forme à l'autre au changement de frame : la bouche
// prépare la suivante avant de quitter la courante, et les muscles ont des
// vitesses différentes selon le geste.

/** Dernière fraction d'une frame qui glisse déjà vers la suivante. */
const ANTICIPATION = 0.3;
/** …bornée en temps : une pause de 600 ms ne prépare pas le mot suivant
 * pendant 180 ms. */
const ANTICIPATION_MAX_MS = 70;
/** Ouverture conservée à travers un blanc entre deux mots. */
const GAP_OPENNESS = 0.7;
/** Vitesses de poursuite (1/s, lissage exponentiel indépendant du framerate).
 * Attaque : τ ≈ 21 ms pour une fermeture, 33 ms pour une autre consonne,
 * 42 ms pour une voyelle. */
const ATTACK_CLOSURE = 48;
const ATTACK_CONSONANT = 30;
const ATTACK_VOWEL = 24;
/** Retour au repos (fin de phrase, pause) : plus lent que toute attaque,
 * τ ≈ 83 ms — la bouche se détend, elle ne claque pas. */
const RELEASE = 12;
/** Passage d'une forme à une autre : la sortante s'efface à peu près au
 * rythme où l'entrante arrive (τ ≈ 38 ms). Relâcher au rythme du repos ici
 * laissait les lèvres à moitié closes pendant toute la voyelle qui suit un
 * « p ». */
const CROSSFADE = 26;
/** …et plus vite encore quand c'est une fermeture qui arrive (τ ≈ 25 ms) :
 * sans lui, le « a » qui s'éteint garde la bouche ouverte sous le « p », et
 * l'occlusive ne se lit pas. */
const YIELD = 40;
/** Cible totale au-dessus de laquelle une forme sortante est un passage de
 * relais et non un retour au repos. */
const TRANSITION_MIN = 0.15;
/** Les gestes qui doivent se voir nets : lèvres closes, lèvre sous les dents,
 * dents serrées. */
const CLOSURES: ReadonlySet<Viseme> = new Set<Viseme>(["PP", "FF", "SS"]);
const VOWEL_VISEMES: ReadonlySet<Viseme> = new Set<Viseme>(["aa", "E", "ih", "oh", "ou"]);
/** Poids de forme au-dessus duquel une fermeture « tient » la cible. */
const CLOSURE_DOMINANCE = 0.3;

// ── Plafond d'ouverture ─────────────────────────────────────────────
// D'autres contrôleurs écrivent sur la même bouche (sourire de l'émotion,
// micro-mouvements idle) et les morphs s'additionnent sur les sommets : un
// « a » plein sur une bouche déjà ouverte par la surprise déforme le visage.

/** Somme maximale des visèmes entre eux (deux formes en fondu = une bouche). */
const MAX_VISEME_SUM = 1.0;
/** Somme maximale visèmes + charge buccale des autres expressions. */
const MAX_MOUTH_TOTAL = 1.3;
/** Ce que la parole garde au minimum, même sur un visage hilare. */
const MIN_VISEME_ALLOWANCE = 0.45;
/** Morphs de bouche reconnus par leur nom (VRChat, ARKit, presets japonais). */
const MOUTH_MORPH_RE = /mouth|jaw|lip|tongue|teeth|tooth|^vrc\.v_|^mth|^[あいうえおん]$/i;
/** Ceux qui ouvrent la bouche comptent plein ; un sourire, une moue, à 40 %. */
const OPENING_MORPH_RE = /open|jawopen|lowerdown|^あ$|^お$/i;
const SHAPE_MORPH_FACTOR = 0.4;

// ── Articulation ────────────────────────────────────────────────────

const ARTICULATION_MIN = 0.4;
const ARTICULATION_MAX = 1.2;
/** Part de la réduction d'articulation subie par les fermetures : une voix
 * lasse ouvre moins la bouche, mais ses « p » ferment toujours les lèvres. */
const CLOSURE_ARTICULATION_SHARE = 0.3;

const VISEME_COUNT = VISEMES.length;
const SIL = VISEME_INDEX.sil;
const ATTACK_RATES = VISEMES.map((v) =>
  CLOSURES.has(v) ? ATTACK_CLOSURE : VOWEL_VISEMES.has(v) ? ATTACK_VOWEL : ATTACK_CONSONANT
);
const IS_CLOSURE = VISEMES.map((v) => CLOSURES.has(v));

interface Route {
  /** Index du visème source. */
  viseme: number;
  /** Index de l'expression écrite (dans `outputNames`). */
  out: number;
  factor: number;
}

interface MouthLoad {
  expression: VRMExpression;
  involvement: number;
}

/** Poids crête d'une frame, `sil` compris (0). */
function frameShape(frame: VisemeFrame | undefined, out: Float32Array, scale: number): void {
  if (!frame || frame.gap || frame.viseme === "sil") return;
  out[VISEME_INDEX[frame.viseme]] += frame.weight * scale;
}

const smoothstep = (x: number): number => {
  const t = Math.max(0, Math.min(1, x));
  return t * t * (3 - 2 * t);
};

/** Index d'un morph dans un maillage → son nom (dictionnaire inversé, mis
 * en cache par dictionnaire : les primitives d'un mesh le partagent). */
const reverseDictionaries = new WeakMap<object, string[]>();
function morphName(mesh: unknown, index: number): string | undefined {
  const dict = (mesh as { morphTargetDictionary?: Record<string, number> } | null)?.morphTargetDictionary;
  if (!dict) return undefined;
  let names = reverseDictionaries.get(dict);
  if (!names) {
    names = [];
    for (const [name, i] of Object.entries(dict)) names[i] = name;
    reverseDictionaries.set(dict, names);
  }
  return names[index];
}

export class LipSyncController {
  private vrm: VRM | null = null;

  // Estimation texte : la Web Speech API ne donne aucun accès à son flux
  // audio, la bouche est donc pilotée depuis le texte prononcé — recalée
  // par `seekToChar` à chaque frontière de mot que la synthèse annonce.
  private phonemeFrames: VisemeFrame[] = [];
  private frameIndex = 0;
  private frameTimer = 0;
  private isTextDriven = false;
  private speaking = false;

  /** Niveau lissé de chaque visème (ce que la bouche montre). */
  private readonly level = new Float32Array(VISEME_COUNT);
  private readonly target = new Float32Array(VISEME_COUNT);
  private readonly shapeA = new Float32Array(VISEME_COUNT);
  private readonly shapeB = new Float32Array(VISEME_COUNT);

  private routes: Route[] = [];
  private outputNames: string[] = [];
  private outputValues = new Float32Array(0);
  private rawVisemes = 0;
  /** Expressions qui sont à nous : exclues de la charge buccale. */
  private ownNames = new Set<string>();

  private mouthLoads: MouthLoad[] = [];
  private scannedExpressionCount = -1;

  private articulation = 1;

  setVRM(vrm: VRM) {
    this.vrm = vrm;
    const manager = vrm.expressionManager;
    let available = new Set<string>();
    // Un VRM de test (ou un modèle sans scène) n'a rien à enregistrer.
    if (manager && typeof vrm.scene?.traverse === "function") {
      try {
        available = registerRawMorphs(vrm, VRC_VISEME_MORPHS);
      } catch (e) {
        console.warn("LipSync: visèmes VRChat non enregistrés, repli sur les presets", e);
      }
    }
    this.buildRoutes(available);

    // Les visèmes bruts sont des expressions de bouche au sens VRM : un
    // modèle VRM 1.0 dont une expression bloque la bouche (overrideMouth)
    // doit les faire taire comme il fait taire aa/ih/ou/ee/oh. Sans effet
    // sur un VRM 0.x, qui n'a pas d'override.
    const mouthNames = (manager as { mouthExpressionNames?: unknown } | undefined)?.mouthExpressionNames;
    if (Array.isArray(mouthNames)) {
      for (const name of this.outputNames) {
        if (!mouthNames.includes(name)) mouthNames.push(name);
      }
    }
    this.scannedExpressionCount = -1;
  }

  /** "visemes" : les 14 morphs VRChat ; "presets" : les 5 voyelles VRM ;
   * "mixed" : un jeu VRChat incomplet, complété par les presets. */
  get outputMode(): "visemes" | "presets" | "mixed" {
    if (this.rawVisemes === DRIVEN_VISEMES.length) return "visemes";
    return this.rawVisemes === 0 ? "presets" : "mixed";
  }

  /**
   * Amplitude des mouvements de bouche (0,4–1,2 ; 1 = normal). Une voix
   * lasse ou triste articule moins : ~0,6–0,8. Les fermetures n'en subissent
   * qu'une part, pour que les « p » restent des « p ».
   */
  setArticulation(scale: number) {
    this.articulation = Number.isFinite(scale)
      ? Math.max(ARTICULATION_MIN, Math.min(ARTICULATION_MAX, scale))
      : 1;
  }

  /** Start text-driven lip sync (the only path: no audio stream is available) */
  startTextDriven(text: string, durationMs: number) {
    const msPerChar = durationMs / Math.max(1, spokenLength(text));
    this.beginFrames(frenchVisemeFrames(text, msPerChar, -1));
  }

  /**
   * Idem, mais à partir du découpage que le TTS va réellement jouer
   * (TTSService.lipSyncPlan) : chaque silence réservé par un token de
   * prosodie devient une frame bouche fermée de sa durée exacte, et seuls
   * les caractères prononcés se voient attribuer du temps de parole.
   */
  startFromPlan(plan: SpeechPlanSegment[], msPerChar = DEFAULT_MS_PER_CHAR) {
    const frames: VisemeFrame[] = [];
    for (const segment of plan) {
      if (segment.type === "silence") {
        frames.push({ viseme: "sil", weight: 0, duration: segment.ms, charOffset: -1 });
      } else {
        frames.push(...frenchVisemeFrames(segment.text, msPerChar, segment.start ?? -1));
      }
    }
    this.beginFrames(frames);
  }

  /**
   * Recale le curseur sur le caractère que la synthèse est en train de
   * prononcer — `utterance.onstart` (le son commence vraiment, pas la mise
   * en file) et `onboundary` (chaque mot, là où le navigateur le donne).
   * L'estimation continue de courir entre deux recalages ; elle ne peut
   * plus dériver de toute la latence de synthèse ni finir avant la voix.
   * Renvoie false si le plan n'a aucune frame voisée.
   */
  seekToChar(charIndex: number): boolean {
    const frames = this.phonemeFrames;
    if (frames.length === 0) return false;
    let target = -1;
    for (let i = 0; i < frames.length; i++) {
      const offset = frames[i].charOffset;
      if (offset < 0) continue;
      if (offset >= charIndex) {
        target = i;
        break;
      }
    }
    if (target < 0) {
      // Au-delà du dernier caractère voisé (ponctuation finale) : se poser
      // sur la dernière frame voisée plutôt que de ne rien faire.
      for (let i = frames.length - 1; i >= 0; i--) {
        if (frames[i].charOffset >= 0) {
          target = i;
          break;
        }
      }
      if (target < 0) return false;
    }
    this.frameIndex = target;
    this.frameTimer = 0;
    this.isTextDriven = true;
    this.speaking = true;
    return true;
  }

  /** Caractère de la frame courante (−1 hors plan) — tests et debug. */
  get currentCharOffset(): number {
    const frame = this.phonemeFrames[this.frameIndex];
    return frame ? frame.charOffset : -1;
  }

  /** Visème de la frame courante (`sil` hors plan) — tests et debug. */
  get currentViseme(): Viseme {
    return this.phonemeFrames[this.frameIndex]?.viseme ?? "sil";
  }

  private beginFrames(frames: VisemeFrame[]) {
    this.phonemeFrames = frames;
    this.frameIndex = 0;
    this.frameTimer = 0;
    this.isTextDriven = true;
    this.speaking = true;
  }

  stop() {
    this.speaking = false;
    this.isTextDriven = false;
    this.phonemeFrames = [];
  }

  update(delta: number) {
    const manager = this.vrm?.expressionManager;
    if (!manager) return;
    const dt = Number.isFinite(delta) && delta > 0 ? delta : 0;

    const target = this.target;
    target.fill(0);
    if (this.speaking && this.isTextDriven && this.phonemeFrames.length > 0) {
      const frames = this.phonemeFrames;
      this.frameTimer += dt * 1000;
      while (this.frameIndex < frames.length && this.frameTimer >= frames[this.frameIndex].duration) {
        this.frameTimer -= frames[this.frameIndex].duration;
        this.frameIndex++;
      }
      if (this.frameIndex < frames.length) this.coarticulatedTarget(target);
      else this.speaking = false;
    }

    this.follow(target, dt);
    this.write(manager);
  }

  isSpeaking(): boolean {
    return this.speaking;
  }

  // ── Rendu ─────────────────────────────────────────────────────────

  /**
   * Forme visée maintenant : celle de la frame courante, fondue dans la
   * dernière part de la frame (ANTICIPATION, bornée en ms) vers celle de la
   * suivante. Le fondu atteint la suivante pile à la frontière : la cible
   * est continue, et le lissage n'a plus qu'à suivre.
   */
  private coarticulatedTarget(out: Float32Array) {
    const frames = this.phonemeFrames;
    const index = this.frameIndex;
    const frame = frames[index];
    const progress = frame.duration > 0 ? Math.min(1, this.frameTimer / frame.duration) : 1;

    this.shapeAt(index, progress, this.shapeA);
    let blend = 0;
    if (index + 1 < frames.length) {
      const window = Math.min(ANTICIPATION * frame.duration, ANTICIPATION_MAX_MS);
      const remaining = frame.duration - this.frameTimer;
      if (window > 0 && remaining < window) blend = smoothstep(1 - remaining / window);
    }
    if (blend > 0) {
      this.shapeAt(index + 1, 0, this.shapeB);
      for (let c = 0; c < VISEME_COUNT; c++) {
        out[c] = this.shapeA[c] * (1 - blend) + this.shapeB[c] * blend;
      }
    } else {
      out.set(this.shapeA);
    }
  }

  /** Forme d'une frame à un instant donné. Un blanc entre deux mots glisse
   * de la forme précédente à la suivante sans refermer la bouche ; une
   * pause (`sil`) la referme. */
  private shapeAt(index: number, progress: number, out: Float32Array) {
    out.fill(0);
    const frames = this.phonemeFrames;
    const frame = frames[index];
    if (!frame) return;
    if (!frame.gap) {
      frameShape(frame, out, 1);
      return;
    }
    let before = index - 1;
    while (before >= 0 && frames[before].gap) before--;
    let after = index + 1;
    while (after < frames.length && frames[after].gap) after++;
    const t = smoothstep(progress);
    frameShape(frames[before], out, (1 - t) * GAP_OPENNESS);
    frameShape(frames[after], out, t * GAP_OPENNESS);
  }

  /**
   * Poursuite asymétrique : attaque rapide des fermetures, plus lente des
   * voyelles ; une forme qui sort s'efface au rythme de celle qui entre (vite
   * si c'est une fermeture), et lentement seulement quand la bouche retourne
   * au repos.
   */
  private follow(target: Float32Array, dt: number) {
    const art = this.articulation;
    const closureArt = 1 - (1 - art) * CLOSURE_ARTICULATION_SHARE;

    let dominant = SIL;
    let wanted = 0;
    for (let c = 0; c < VISEME_COUNT; c++) {
      wanted += target[c];
      if (target[c] > target[dominant]) dominant = c;
    }
    const closing = IS_CLOSURE[dominant] && target[dominant] > CLOSURE_DOMINANCE;
    const handover = wanted > TRANSITION_MIN;

    for (let c = 0; c < VISEME_COUNT; c++) {
      if (c === SIL) continue;
      const goal = target[c] * (IS_CLOSURE[c] ? closureArt : art);
      const current = this.level[c];
      let rate: number;
      if (goal > current) rate = ATTACK_RATES[c];
      else if (closing && c !== dominant) rate = YIELD;
      else rate = handover ? CROSSFADE : RELEASE;
      this.level[c] = current + (goal - current) * (1 - Math.exp(-rate * dt));
    }
  }

  /** Écrit les niveaux sur le visage, sous le plafond d'ouverture. */
  private write(manager: VRMExpressionManager) {
    const level = this.level;
    let sum = 0;
    for (let c = 0; c < VISEME_COUNT; c++) if (c !== SIL) sum += level[c];
    const allowance = this.visemeAllowance(manager);
    const scale = sum > allowance ? allowance / sum : 1;

    const values = this.outputValues;
    values.fill(0);
    for (const route of this.routes) values[route.out] += level[route.viseme] * route.factor * scale;
    for (let o = 0; o < this.outputNames.length; o++) {
      manager.setValue(this.outputNames[o], Math.min(1, values[o]));
    }
  }

  /**
   * Somme de visèmes permise ce frame : MAX_MOUTH_TOTAL moins ce que les
   * autres expressions font déjà à la bouche, jamais sous
   * MIN_VISEME_ALLOWANCE (on parle encore en riant) ni au-dessus de
   * MAX_VISEME_SUM. Lue après EmotionController et FaceIdleController
   * (ordre de main.ts), donc sur les poids de ce frame.
   */
  private visemeAllowance(manager: VRMExpressionManager): number {
    const load = this.mouthLoad(manager);
    return Math.max(MIN_VISEME_ALLOWANCE, Math.min(MAX_VISEME_SUM, MAX_MOUTH_TOTAL - load));
  }

  /** Charge buccale des autres expressions : « ou » probabiliste de
   * poids × implication, pour que deux demi-sourires ne comptent pas double. */
  private mouthLoad(manager: VRMExpressionManager): number {
    const expressions = (manager as { expressions?: unknown }).expressions;
    if (!Array.isArray(expressions)) return 0;
    // D'autres contrôleurs enregistrent leurs expressions brutes après nous :
    // un nombre qui change suffit à relancer l'inventaire.
    if (expressions.length !== this.scannedExpressionCount) {
      this.scanMouthLoads(expressions as VRMExpression[]);
    }
    let untouched = 1;
    for (const { expression, involvement } of this.mouthLoads) {
      const weight = expression.weight;
      if (weight > 0.001) untouched *= 1 - Math.min(1, weight * involvement);
    }
    return 1 - untouched;
  }

  private scanMouthLoads(expressions: VRMExpression[]) {
    this.mouthLoads = [];
    for (const expression of expressions) {
      if (this.ownNames.has(expression.expressionName)) continue;
      let involvement = 0;
      for (const bind of expression.binds ?? []) {
        const b = bind as { primitives?: unknown[]; index?: unknown; weight?: unknown };
        if (!Array.isArray(b.primitives) || typeof b.index !== "number") continue;
        const name = morphName(b.primitives[0], b.index);
        if (!name || !MOUTH_MORPH_RE.test(name)) continue;
        const factor = OPENING_MORPH_RE.test(name) ? 1 : SHAPE_MORPH_FACTOR;
        const weight = typeof b.weight === "number" ? b.weight : 1;
        involvement = Math.max(involvement, weight * factor);
      }
      if (involvement > 0.01) this.mouthLoads.push({ expression, involvement });
    }
    this.scannedExpressionCount = expressions.length;
  }

  /** Visème par visème : le morph VRChat s'il existe, sinon les presets. */
  private buildRoutes(rawAvailable: ReadonlySet<string>) {
    const names: string[] = [];
    const indexOf = (name: string): number => {
      let i = names.indexOf(name);
      if (i < 0) i = names.push(name) - 1;
      return i;
    };
    const routes: Route[] = [];
    let raw = 0;
    for (const viseme of DRIVEN_VISEMES) {
      const v = VISEME_INDEX[viseme];
      const morph = vrcMorph(viseme);
      if (rawAvailable.has(morph)) {
        routes.push({ viseme: v, out: indexOf(rawName(morph)), factor: 1 });
        raw++;
        continue;
      }
      for (const [preset, factor] of Object.entries(PRESET_FALLBACK[viseme])) {
        routes.push({ viseme: v, out: indexOf(preset), factor: factor as number });
      }
    }
    this.routes = routes;
    this.outputNames = names;
    this.outputValues = new Float32Array(names.length);
    this.rawVisemes = raw;
    this.ownNames = new Set<string>([...names, ...MOUTH_PRESETS, ...VRC_VISEME_MORPHS.map(rawName)]);
  }
}
