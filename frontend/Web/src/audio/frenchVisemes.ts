/**
 * Texte français → visèmes, pour une bouche qui articule.
 *
 * L'ancienne estimation lisait l'orthographe lettre à lettre sur quatre
 * formes : « eau » faisait trois bouches, le « s » muet de « les » était
 * prononcé, « ch », « gn » et « qu » en faisaient deux, et rien ne fermait
 * jamais les lèvres sur un « p ». Ce module fait un passage graphème →
 * phonème raisonnable (digraphes, nasales, lettres muettes, élisions,
 * nombres en toutes lettres), puis projette chaque phonème sur les 15
 * visèmes VRChat/Oculus que porte le modèle.
 *
 * Ce n'est pas un phonétiseur de linguiste : il doit avoir l'air juste sur
 * un visage à vitesse de parole. Les erreurs résiduelles (liaisons non
 * modélisées, « -ent » ambigu, homographes) coûtent une voyelle de travers,
 * jamais une bouche qui part en vrille.
 *
 * Pur : ni three.js ni DOM, pour être testé tel quel.
 *
 * Deux invariants que le lip-sync exige :
 * - chaque frame garde l'index d'ORIGINE du caractère qu'elle articule
 *   (`seekToChar` recale la bouche sur les frontières de mot que la synthèse
 *   annonce, en index du texte complet) ;
 * - la durée totale d'un segment vaut `msPerChar × spokenLength(texte)`,
 *   c'est-à-dire la longueur aux blancs repliés — à une exception près : un
 *   nombre compte pour la longueur de sa forme écrite en toutes lettres,
 *   parce que c'est ce que la voix dit (« 2026 » dure « deux mille
 *   vingt-six », pas quatre caractères).
 */

// ── Visèmes ─────────────────────────────────────────────────────────

/** Les 15 visèmes VRChat/Oculus, dans l'ordre de leurs morphs `vrc.v_*`. */
export const VISEMES = [
  "sil",
  "PP",
  "FF",
  "TH",
  "DD",
  "kk",
  "CH",
  "SS",
  "nn",
  "RR",
  "aa",
  "E",
  "ih",
  "oh",
  "ou",
] as const;
export type Viseme = (typeof VISEMES)[number];

export const VISEME_INDEX: Readonly<Record<Viseme, number>> = Object.fromEntries(
  VISEMES.map((v, i) => [v, i])
) as Record<Viseme, number>;

export interface VisemeFrame {
  viseme: Viseme;
  /** Poids crête du visème (0 pour `sil`). */
  weight: number;
  duration: number; // ms
  /** Index, dans le texte complet de la réponse, du caractère que cette
   * frame articule ; −1 pour un silence ou un plan sans position. */
  charOffset: number;
  /** Blanc entre deux mots : pas de fermeture, la bouche glisse d'une forme
   * à la suivante (on ne referme pas la bouche entre chaque mot en parlant). */
  gap?: boolean;
}

// ── Phonèmes ────────────────────────────────────────────────────────

/**
 * Inventaire réduit, notation proche du X-SAMPA : `@` schwa, `2` « eu »,
 * `E` « è », `~` nasale, `J` « gn », `S`/`Z` « ch »/« j », `H` le « u » de
 * « nuit », `R` le r français.
 */
export type Phoneme =
  | "a" | "a~" | "e" | "E" | "e~" | "@" | "2" | "i" | "o" | "o~" | "u" | "y"
  | "j" | "w" | "H"
  | "p" | "b" | "m" | "f" | "v" | "t" | "d" | "n" | "l" | "J"
  | "k" | "g" | "s" | "z" | "S" | "Z" | "R";

export interface PhonemeToken {
  ph: Phoneme;
  /** Index, dans le texte analysé, du premier caractère de son graphème. */
  at: number;
}

interface PhonemeInfo {
  viseme: Viseme;
  /** Amplitude crête du visème. */
  weight: number;
  /** Durée relative : les voyelles tiennent, les consonnes passent. */
  length: number;
  vowel: boolean;
}

const info = (viseme: Viseme, weight: number, length: number, vowel = false): PhonemeInfo => ({
  viseme,
  weight,
  length,
  vowel,
});

export const PHONEMES: Readonly<Record<Phoneme, PhonemeInfo>> = {
  a: info("aa", 1.0, 1.0, true),
  "a~": info("aa", 0.75, 1.15, true),
  e: info("E", 0.8, 0.95, true),
  E: info("E", 0.85, 1.0, true),
  "e~": info("E", 0.7, 1.15, true),
  // Le schwa français est arrondi et bref (« le » ≈ [lø]).
  "@": info("oh", 0.4, 0.6, true),
  "2": info("oh", 0.6, 1.0, true),
  i: info("ih", 0.8, 0.9, true),
  o: info("oh", 0.9, 1.0, true),
  "o~": info("oh", 0.8, 1.15, true),
  u: info("ou", 0.9, 0.95, true),
  // [y] : lèvres arrondies et serrées, la même bouche que « ou » vue de face.
  y: info("ou", 0.85, 0.9, true),
  j: info("ih", 0.5, 0.4),
  w: info("ou", 0.7, 0.45),
  H: info("ou", 0.6, 0.4),
  // Bilabiales : les lèvres se ferment, poids plein.
  p: info("PP", 1.0, 0.55),
  b: info("PP", 1.0, 0.55),
  m: info("PP", 1.0, 0.6),
  // Labiodentales : lèvre inférieure sous les incisives.
  f: info("FF", 1.0, 0.65),
  v: info("FF", 0.95, 0.6),
  t: info("DD", 0.85, 0.5),
  d: info("DD", 0.85, 0.5),
  n: info("nn", 0.85, 0.55),
  l: info("nn", 0.75, 0.5),
  J: info("nn", 0.9, 0.6),
  k: info("kk", 0.85, 0.55),
  g: info("kk", 0.8, 0.55),
  s: info("SS", 0.95, 0.65),
  z: info("SS", 0.9, 0.6),
  S: info("CH", 1.0, 0.65),
  Z: info("CH", 0.95, 0.6),
  // Le r uvulaire ne se voit presque pas sur les lèvres.
  R: info("RR", 0.7, 0.5),
};

// ── Timing ──────────────────────────────────────────────────────────

/** Part d'un caractère qu'un blanc garde pour lui (le reste nourrit les
 * phonèmes) : assez pour une détente, trop peu pour une fermeture. */
const SPACE_GAP_SHARE = 0.5;
/** Allongement de la dernière voyelle avant une pause : l'accent français
 * tombe en fin de groupe. Redistribué, il ne change pas la durée totale. */
const FINAL_LENGTHENING = 1.35;
/** Variation d'amplitude déterministe d'une voyelle à l'autre (±4 %) : sans
 * elle, deux « a » successifs sont deux copies — c'est ce qui fait robot. */
const WEIGHT_JITTER = 0.08;

// ── Classes de lettres ──────────────────────────────────────────────

const VOWEL_LETTERS = "aàâäeéèêëiîïoôöuùûüyÿœæ";
const FRONT_LETTERS = "eéèêëiîïyÿ"; // c et g doux devant elles
const SILENT_FINALS = "stdxzp";
const LETTER = /\p{L}/u;
const MARK = /\p{M}/u;
const SPACE = /\s/;
const DIGIT = /[0-9]/;
const JOINER = /['’ʼ\-‐‑]/;
const APOSTROPHE = /['’ʼ]/;
/** Ponctuation qui pose une vraie pause (fermeture). Les guillemets,
 * parenthèses ou émojis ne se disent pas : ils glissent, comme un blanc. */
const PAUSE_PUNCT = /[.,;:!?…—–]/;

const inSet = (c: string, set: string): boolean => c !== "" && set.includes(c);
const isVowelLetter = (c: string): boolean => inSet(c, VOWEL_LETTERS);

// ── Lexique : ce que les règles ne savent pas deviner ───────────────

/** Mots entiers irréguliers (phonèmes séparés par des espaces). */
const EXCEPTIONS: Readonly<Record<string, string>> = {
  est: "E",
  et: "e",
  es: "E",
  ok: "o k e",
  vingt: "v e~",
  vingts: "v e~",
  sept: "s E t",
  huit: "H i t",
  six: "s i s",
  dix: "d i s",
  soixante: "s w a s a~ t",
  fils: "f i s",
  femme: "f a m",
  femmes: "f a m",
  monsieur: "m @ s j 2",
  messieurs: "m e s j 2",
  oignon: "o J o~",
  second: "s @ g o~",
  seconde: "s @ g o~ d",
  eu: "y",
  eus: "y",
  eut: "y",
  pays: "p E i",
  août: "u t",
  ouest: "w E s t",
  œil: "2 j",
  yeux: "j 2",
  gens: "Z a~",
  chez: "S e",
  clef: "k l e",
  doigt: "d w a",
  doigts: "d w a",
  corps: "k o R",
  blanc: "b l a~",
  franc: "f R a~",
  tabac: "t a b a",
  estomac: "E s t o m a",
  porc: "p o R",
  hier: "j E R",
  fier: "f j E R",
  cher: "S E R",
  hiver: "i v E R",
  super: "s y p E R",
  enfer: "a~ f E R",
  amer: "a m E R",
};

/** Mots dont la consonne finale se prononce malgré la règle des muettes. */
const FINAL_KEPT = new Set([
  "bus", "os", "ours", "mars", "sens", "virus", "bonus", "tennis", "hélas", "maïs",
  "jadis", "oasis", "iris", "atlas", "cactus", "campus", "lys", "autobus",
  "net", "but", "test", "brut", "chut", "dot", "kit", "mat", "sud",
  "stop", "top", "cap", "slip", "clip", "hip",
  "gaz", "fax", "box", "max", "relax", "lynx", "index", "linux", "sphinx",
]);

/** « -er » final prononcé [ɛʁ] (le cas général est l'infinitif muet). */
const ER_KEPT = new Set(["laser", "cancer", "hamster", "poster", "master", "starter", "leader"]);

/** « -ent » final qui n'est pas une terminaison verbale. */
const ENT_PRONOUNCED = new Set([
  "parent", "souvent", "absent", "présent", "argent", "agent", "urgent", "client",
  "patient", "impatient", "talent", "accent", "content", "serpent", "évident",
  "différent", "intelligent", "prudent", "récent", "fréquent", "excellent",
  "innocent", "adolescent", "accident", "incident", "président", "résident",
  "équivalent", "violent", "ardent", "torrent", "orient", "occident", "quotient",
  "permanent", "compétent", "décent", "indécent", "pertinent", "continent",
]);

/** Sujets qui rendent un « -ent » final muet à coup sûr (« ils mangent »). */
const PLURAL_SUBJECTS = new Set(["ils", "elles"]);

/** Monosyllabes où le « e » final se dit (schwa). */
const SCHWA_WORDS = new Set(["que"]);

/** « ill » qui se dit [il] et non [ij]. */
const LL_PRONOUNCED = /^(vill|mill|tranquill|lill|distill|oscill|pupill|bacill)/;

/** Consonne élidée devant une apostrophe (« l'ami », « c'est », « j'ai »). */
const ELIDED_LETTER: Readonly<Record<string, Phoneme>> = {
  l: "l", d: "d", j: "Z", m: "m", n: "n", s: "s", t: "t", c: "s", ç: "s",
};

/** Une lettre isolée se dit par son nom (« le point b ») ; « y » et « a »
 * sont des mots. */
const LETTER_NAMES: Readonly<Record<string, string>> = {
  a: "a", à: "a", â: "a", e: "@", é: "e", è: "E", ê: "E", i: "i", î: "i",
  o: "o", ô: "o", u: "y", y: "i",
  b: "b e", c: "s e", ç: "s e", d: "d e", f: "E f", g: "Z e", h: "a S", j: "Z i",
  k: "k a", l: "E l", m: "E m", n: "E n", p: "p e", q: "k y", r: "E R", s: "E s",
  t: "t e", v: "v e", w: "d u b l @ v e", x: "i k s", z: "z E d",
};

// ── Mots ────────────────────────────────────────────────────────────

/** Répartit une chaîne de phonèmes sur les lettres d'un mot, en ordre. */
function spread(phonemes: string, pos: readonly number[], out: PhonemeToken[]): void {
  const parts = phonemes.split(" ") as Phoneme[];
  const L = pos.length;
  parts.forEach((ph, k) => {
    out.push({ ph, at: pos[Math.min(L - 1, Math.floor((k * L) / parts.length))] });
  });
}

/**
 * Longueur prononcée d'un mot : ce qui suit est muet (e muet, « -es »,
 * « -ent » verbal, consonnes finales, r de l'infinitif). Les lettres muettes
 * restent lisibles par les règles comme contexte (« mangent » : le « e » muet
 * adoucit quand même le « g »).
 */
function pronouncedEnd(s: string, prev: string): number {
  const L = s.length;
  if (L <= 1) return L;
  if (s.endsWith("aient")) return L - 3; // imparfait : « étaient »
  if (s.endsWith("ent") && L >= 4) {
    if (PLURAL_SUBJECTS.has(prev)) return L - 3;
    if (L >= 5 && !s.endsWith("ment") && !ENT_PRONOUNCED.has(s) && !/[tv]ient$/.test(s)) {
      return L - 3;
    }
  }
  let end = L;
  if (s.endsWith("es") && L > 3 && !FINAL_KEPT.has(s)) {
    end = L - 2; // pluriel ou 2e personne d'un mot en e muet
  } else if (s.endsWith("e")) {
    if (L > 2 && !SCHWA_WORDS.has(s)) end = L - 1; // e muet
  } else if (!FINAL_KEPT.has(s) && !s.endsWith("ss") && inSet(s[L - 1], SILENT_FINALS)) {
    const first = s[L - 1];
    end = L - 1;
    // « grands », « temps », « petits » : le pluriel découvre une autre muette.
    if ((first === "s" || first === "x") && end > 1 && inSet(s[end - 1], "tdp")) end -= 1;
  }
  const base = s.slice(0, end);
  if (base.endsWith("er") && end >= 4 && !ER_KEPT.has(base)) end -= 1; // infinitif, -ier
  else if (base.endsWith("ng")) end -= 1; // « long », « sang »
  return end;
}

/**
 * Phonétise un mot sans apostrophe ni trait d'union. `s` est en minuscules
 * composées, `pos[i]` l'index source de la lettre `s[i]`.
 */
function pronounceWord(
  s: string,
  orig: string,
  pos: readonly number[],
  prev: string,
  elided: boolean,
  out: PhonemeToken[]
): void {
  const L = s.length;
  if (L === 0) return;

  if (elided && L === 1) {
    const ph = ELIDED_LETTER[s];
    if (ph) out.push({ ph, at: pos[0] });
    else spread(LETTER_NAMES[s] ?? "@", pos, out);
    return;
  }
  if (!elided) {
    const exception = EXCEPTIONS[s];
    if (exception) return spread(exception, pos, out);
    if (L === 1) return spread(LETTER_NAMES[s] ?? "@", pos, out);
    // Sigle sans voyelle (« SMS ») : la voix l'épelle.
    if (orig === orig.toUpperCase() && orig !== orig.toLowerCase() && ![...s].some(isVowelLetter)) {
      for (let k = 0; k < L; k++) spread(LETTER_NAMES[s[k]] ?? "@", [pos[k]], out);
      return;
    }
  }

  const end = elided ? L : pronouncedEnd(s, prev);
  const base = out.length;
  const ch = (k: number): string => (k >= 0 && k < L ? s[k] : "");
  const V = (k: number): boolean => isVowelLetter(ch(k));
  const C = (k: number): boolean => ch(k) !== "" && !isVowelLetter(ch(k));
  const emit = (ph: Phoneme, k: number): void => {
    out.push({ ph, at: pos[Math.min(k, L - 1)] });
  };
  // Un n/m nasalise la voyelle qui le précède s'il n'est suivi ni d'une
  // voyelle — même muette : « une », « bonne » — ni d'un n/m/h.
  const nasal = (k: number): boolean =>
    inSet(ch(k), "nm") && k < end && !V(k + 1) && !inSet(ch(k + 1), "nmh");

  let i = 0;
  while (i < end) {
    const c = s[i];
    switch (c) {
      case "a":
      case "à":
      case "â":
      case "ä": {
        if (c === "a" && ch(i + 1) === "i" && ch(i + 2) === "l" && (i + 3 >= end || ch(i + 3) === "l")) {
          emit("a", i); // « travail », « paille »
          emit("j", i + 1);
          i += ch(i + 3) === "l" ? 4 : 3;
        } else if (c === "a" && inSet(ch(i + 1), "iî")) {
          if (nasal(i + 2)) {
            emit("e~", i); // « pain », « faim »
            i += 3;
          } else {
            emit("E", i);
            i += 2;
          }
        } else if (c === "a" && inSet(ch(i + 1), "uû")) {
          emit("o", i);
          i += 2;
        } else if (c === "a" && ch(i + 1) === "y") {
          emit("E", i); // « crayon » : le y suit en [j]
          i += 1;
        } else if (nasal(i + 1)) {
          emit("a~", i);
          i += 2;
        } else {
          emit("a", i);
          i += 1;
        }
        break;
      }
      case "e": {
        if (ch(i + 1) === "a" && ch(i + 2) === "u") {
          emit("o", i); // « eau », « oiseau »
          i += 3;
        } else if (ch(i + 1) === "u" && ch(i + 2) === "i" && ch(i + 3) === "l") {
          emit("2", i); // « feuille », « fauteuil »
          emit("j", i + 2);
          i += ch(i + 4) === "l" ? 5 : 4;
        } else if (inSet(ch(i + 1), "uû")) {
          emit("2", i);
          i += 2;
        } else if (ch(i + 1) === "i" && ch(i + 2) === "l" && (i + 3 >= end || ch(i + 3) === "l")) {
          emit("E", i); // « soleil », « abeille »
          emit("j", i + 1);
          i += ch(i + 3) === "l" ? 4 : 3;
        } else if (inSet(ch(i + 1), "iî")) {
          if (nasal(i + 2)) {
            emit("e~", i); // « plein »
            i += 3;
          } else {
            emit("E", i);
            i += 2;
          }
        } else if (ch(i + 1) === "y") {
          emit("E", i);
          i += 1;
        } else if (nasal(i + 1)) {
          // « bien », « européen », « viendra » : [ɛ̃] après i/é/y en fin de
          // mot ou devant d ; « science », « patience », et partout ailleurs : [ɑ̃].
          const ien = inSet(ch(i - 1), "iéy") && (i + 2 >= end || ch(i + 2) === "d");
          emit(ien ? "e~" : "a~", i);
          i += 2;
        } else {
          plainE(i);
          i += 1;
        }
        break;
      }
      case "é":
      case "æ":
        emit("e", i);
        i += 1;
        break;
      case "è":
      case "ê":
      case "ë":
        emit("E", i);
        i += 1;
        break;
      case "i":
      case "î":
      case "ï":
      case "y":
      case "ÿ": {
        const isY = c === "y" || c === "ÿ";
        if (isY && ((i === 0 && V(i + 1)) || (V(i - 1) && V(i + 1)))) {
          emit("j", i); // « yaourt », « crayon », « voyage »
          i += 1;
        } else if (c === "i" && i > 0 && ch(i + 1) === "l" && ch(i + 2) === "l") {
          if (LL_PRONOUNCED.test(s)) {
            emit("i", i); // « ville », « million » : le « ll » suit en [l]
            i += 1;
          } else {
            emit("i", i); // « fille », « famille »
            emit("j", i + 1);
            i += 3;
          }
        } else if ((c === "i" || isY) && nasal(i + 1)) {
          emit("e~", i);
          i += 2;
        } else if (c === "i" && i > 0 && C(i - 1) && V(i + 1) && i + 1 < end) {
          emit("j", i); // « pied », « bien », « nation »
          i += 1;
        } else {
          emit("i", i);
          i += 1;
        }
        break;
      }
      case "o":
      case "ô":
      case "ö": {
        if (c === "o" && ch(i + 1) === "i" && nasal(i + 2)) {
          emit("w", i); // « loin », « point »
          emit("e~", i + 1);
          i += 3;
        } else if (c === "o" && inSet(ch(i + 1), "iî")) {
          emit("w", i); // « moi », « oiseau »
          emit("a", i + 1);
          i += 2;
        } else if (c === "o" && ch(i + 1) === "y") {
          emit("w", i); // « voyage » : le y suit en [j]
          emit("a", i);
          i += 1;
        } else if (c === "o" && inSet(ch(i + 1), "uùû")) {
          if (ch(i + 2) === "i" && ch(i + 3) === "l" && ch(i + 4) === "l") {
            emit("u", i); // « grenouille »
            emit("j", i + 2);
            i += 5;
          } else if (V(i + 2) && i + 2 < end) {
            emit("w", i); // « oui », « jouer »
            i += 2;
          } else {
            emit("u", i);
            i += 2;
          }
        } else if (nasal(i + 1)) {
          emit("o~", i);
          i += 2;
        } else {
          emit("o", i);
          i += 1;
        }
        break;
      }
      case "œ":
        emit("2", i); // « cœur », « œuvre »
        i += ch(i + 1) === "u" ? 2 : 1;
        break;
      case "u":
      case "ù":
      case "û":
      case "ü": {
        if (c === "u" && ch(i + 1) === "e" && ch(i + 2) === "i" && ch(i + 3) === "l") {
          emit("2", i); // « accueil », « cueillir »
          emit("j", i + 2);
          i += ch(i + 4) === "l" ? 5 : 4;
        } else if (c === "u" && ch(i + 1) === "m" && i + 2 >= L) {
          emit("o", i); // « album », « maximum »
          emit("m", i + 1);
          i += 2;
        } else if (c === "u" && nasal(i + 1)) {
          emit("e~", i); // « un », « lundi »
          i += 2;
        } else if (i > 0 && V(i + 1) && i + 1 < end) {
          emit("H", i); // « nuit », « lui »
          i += 1;
        } else {
          emit("y", i);
          i += 1;
        }
        break;
      }
      case "c": {
        if (ch(i + 1) === "h") {
          emit(inSet(ch(i + 2), "rl") ? "k" : "S", i); // « chat » / « chrome »
          i += 2;
        } else if (ch(i + 1) === "c") {
          emit("k", i);
          if (inSet(ch(i + 2), FRONT_LETTERS)) emit("s", i + 1); // « accent »
          i += 2;
        } else if (ch(i + 1) === "k") {
          emit("k", i);
          i += 2;
        } else {
          emit(inSet(ch(i + 1), FRONT_LETTERS) ? "s" : "k", i);
          i += 1;
        }
        break;
      }
      case "ç":
        emit("s", i);
        i += 1;
        break;
      case "g": {
        if (ch(i + 1) === "n") {
          emit("J", i); // « champagne »
          i += 2;
        } else if (ch(i + 1) === "u" && inSet(ch(i + 2), FRONT_LETTERS)) {
          emit("g", i); // « guitare »
          i += 2;
        } else if (ch(i + 1) === "e" && inSet(ch(i + 2), "aâoôu")) {
          emit("Z", i); // « mangeons », « geai »
          i += 2;
        } else if (ch(i + 1) === "g") {
          emit("g", i);
          if (inSet(ch(i + 2), FRONT_LETTERS)) emit("Z", i + 1); // « suggérer »
          i += 2;
        } else {
          emit(inSet(ch(i + 1), FRONT_LETTERS) ? "Z" : "g", i);
          i += 1;
        }
        break;
      }
      case "h":
        i += 1; // muet hors digraphes
        break;
      case "j":
        emit("Z", i);
        i += 1;
        break;
      case "p":
        if (ch(i + 1) === "h") {
          emit("f", i); // « photo »
          i += 2;
        } else {
          i += doubled(i, "p");
        }
        break;
      case "q":
        emit("k", i); // « qu » : le u ne se dit pas
        i += ch(i + 1) === "u" ? 2 : 1;
        break;
      case "s": {
        if (ch(i + 1) === "c" && ch(i + 2) === "h") {
          emit("S", i);
          i += 3;
        } else if (ch(i + 1) === "h") {
          emit("S", i);
          i += 2;
        } else if (ch(i + 1) === "s") {
          emit("s", i);
          i += 2;
        } else if (ch(i + 1) === "c" && inSet(ch(i + 2), FRONT_LETTERS)) {
          emit("s", i); // « science »
          i += 2;
        } else {
          emit(V(i - 1) && V(i + 1) ? "z" : "s", i); // « oiseau », « chose »
          i += 1;
        }
        break;
      }
      case "t": {
        if (ch(i + 1) === "h" || ch(i + 1) === "t") {
          emit("t", i);
          i += 2;
        } else if (
          ch(i + 1) === "i" && ch(i + 2) === "o" && ch(i + 3) === "n" && i > 0 && !inSet(ch(i - 1), "sx")
        ) {
          emit("s", i); // « nation », mais « question »
          i += 1;
        } else {
          emit("t", i);
          i += 1;
        }
        break;
      }
      case "x": {
        if (i === 1 && ch(0) === "e" && (V(2) || ch(2) === "h")) {
          emit("g", i); // « exemple »
          emit("z", i);
        } else if (s.includes("xième")) {
          emit("z", i); // « deuxième »
        } else {
          emit("k", i); // « taxi »
          emit("s", i);
        }
        i += 1;
        break;
      }
      case "w":
        emit("w", i);
        i += 1;
        break;
      case "ñ":
        emit("J", i);
        i += 1;
        break;
      case "ß":
        emit("s", i);
        i += 1;
        break;
      case "b":
      case "d":
      case "f":
      case "k":
      case "l":
      case "m":
      case "n":
      case "r":
      case "v":
      case "z":
        i += doubled(i, c === "r" ? "R" : (c as Phoneme));
        break;
      default:
        // Lettre hors du français (autre écriture) : une ouverture neutre,
        // pour que la bouche bouge quand la voix parle.
        emit("@", i);
        i += 1;
    }
  }

  /** Consonne simple ; une consonne doublée ne se dit qu'une fois. */
  function doubled(k: number, ph: Phoneme): number {
    emit(ph, k);
    return ch(k + 1) === s[k] ? 2 : 1;
  }

  /** Le « e » sans accent ni digraphe : [e], [ɛ], schwa, ou rien. */
  function plainE(k: number): void {
    if (k === end - 1) {
      if (end < L) {
        // Suivi de muettes : « manger », « chez », « pied », « les » / « poulet ».
        emit(inSet(ch(k + 1), "rzds") ? "e" : "E", k);
      } else {
        emit("@", k); // « le », « que »
      }
      return;
    }
    if (k === 0) {
      emit("E", k); // « elle », « Eric »
      return;
    }
    if (!C(k + 1)) {
      emit("E", k);
      return;
    }
    // Une consonne (un digraphe compte pour une) puis une voyelle : syllabe
    // ouverte, schwa ; deux consonnes ou une finale : syllabe fermée, [ɛ].
    const pair = ch(k + 1) + ch(k + 2);
    const after = k + (pair === "ch" || pair === "ph" || pair === "th" || pair === "gn" ? 3 : 2);
    const cluster = inSet(ch(k + 1), "bcdfgkptv") && inSet(ch(k + 2), "lr") && V(k + 3);
    const closed = !cluster && (C(after) || after >= end);
    if (closed) {
      emit("E", k);
      return;
    }
    // Schwa entre une seule consonne et une consonne + voyelle : il tombe
    // (« samedi » [samdi], « maintenant » [mɛ̃tnɑ̃]).
    const n = out.length - base;
    const last = out[out.length - 1];
    const beforeLast = out[out.length - 2];
    const elidable =
      n >= 2 && !PHONEMES[last.ph].vowel && PHONEMES[beforeLast.ph].vowel && C(k + 1) && V(k + 2);
    if (!elidable) emit("@", k);
  }
}

// ── Nombres ─────────────────────────────────────────────────────────

const UNITS = [
  "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
  "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
];
const TENS: Readonly<Record<number, string>> = {
  2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante",
};

function below100(n: number): string {
  if (n < 17) return UNITS[n];
  if (n < 20) return `dix-${UNITS[n - 10]}`;
  const tens = Math.floor(n / 10);
  const unit = n % 10;
  if (tens === 7) return unit === 1 ? "soixante et onze" : `soixante-${below100(10 + unit)}`;
  if (tens === 8) return unit === 0 ? "quatre-vingts" : `quatre-vingt-${UNITS[unit]}`;
  if (tens === 9) return `quatre-vingt-${below100(10 + unit)}`;
  const name = TENS[tens];
  if (unit === 0) return name;
  return unit === 1 ? `${name} et un` : `${name}-${UNITS[unit]}`;
}

function below1000(n: number): string {
  const hundreds = Math.floor(n / 100);
  const rest = n % 100;
  const head =
    hundreds === 0 ? "" : hundreds === 1 ? "cent" : `${UNITS[hundreds]} cent${rest === 0 ? "s" : ""}`;
  return [head, rest ? below100(rest) : ""].filter(Boolean).join(" ");
}

/** Écrit un entier en toutes lettres, comme la synthèse le lit. Au-delà de
 * neuf chiffres, ou avec un zéro de tête (« 06… »), chiffre par chiffre. */
export function spellNumber(digits: string): string {
  if (digits.length > 9 || (digits.length > 1 && digits[0] === "0")) {
    return [...digits].map((d) => UNITS[Number(d)]).join(" ");
  }
  const n = Number(digits);
  if (n === 0) return UNITS[0];
  const millions = Math.floor(n / 1_000_000);
  const thousands = Math.floor(n / 1000) % 1000;
  const rest = n % 1000;
  const parts: string[] = [];
  if (millions) parts.push(millions === 1 ? "un million" : `${below1000(millions)} millions`);
  if (thousands) parts.push(thousands === 1 ? "mille" : `${below1000(thousands)} mille`);
  if (rest) parts.push(below1000(rest));
  return parts.join(" ");
}

// ── Analyse ─────────────────────────────────────────────────────────

type UnitKind = "word" | "number" | "space" | "pause" | "symbol";

interface Unit {
  kind: UnitKind;
  from: number;
  /** Poids temporel en caractères (la longueur aux blancs repliés). */
  chars: number;
  phonemes: PhonemeToken[];
}

/** Lettres d'un fragment, diacritiques combinants recomposés sur leur base
 * (un « é » décomposé reste une lettre, à l'index de sa base). */
function composeLetters(text: string, from: number, to: number) {
  let orig = "";
  let lower = "";
  const pos: number[] = [];
  for (let k = from; k < to; k++) {
    const c = text[k];
    if (MARK.test(c)) {
      if (pos.length === 0) continue;
      const composed = (orig[orig.length - 1] + c).normalize("NFC");
      if (composed.length === 1) {
        orig = orig.slice(0, -1) + composed;
        lower = lower.slice(0, -1) + composed.toLowerCase().charAt(0);
      }
      continue;
    }
    orig += c;
    lower += c.toLowerCase().normalize("NFC").charAt(0);
    pos.push(k);
  }
  return { orig, lower, pos };
}

/** Un mot, apostrophes et traits d'union compris : chaque fragment est
 * phonétisé à part (« qu'est-ce », « peut-être »). Renvoie le dernier
 * fragment, contexte du mot suivant. */
function pronounceWordUnit(text: string, from: number, to: number, prev: string, out: PhonemeToken[]): string {
  let k = from;
  while (k < to) {
    let e = k;
    while (e < to && !JOINER.test(text[e])) e++;
    const { orig, lower, pos } = composeLetters(text, k, e);
    const elided = e < to && APOSTROPHE.test(text[e]);
    pronounceWord(lower, orig, pos, prev, elided, out);
    prev = lower;
    k = e + 1;
  }
  return prev;
}

/** Phonèmes d'un nombre écrit en toutes lettres, ramenés sur ses chiffres :
 * l'index est interpolé le long de « 2026 » pour rester monotone. */
function numberPhonemes(spelled: string, from: number, to: number): PhonemeToken[] {
  const local: PhonemeToken[] = [];
  let prev = "";
  for (const match of spelled.matchAll(/[^\s-]+/g)) {
    const at = match.index ?? 0;
    const { orig, lower, pos } = composeLetters(spelled, at, at + match[0].length);
    pronounceWord(lower, orig, pos, prev, false, local);
    prev = lower;
  }
  const width = to - from;
  return local.map((t) => ({ ph: t.ph, at: from + Math.floor((t.at * width) / spelled.length) }));
}

function analyze(text: string): Unit[] {
  const units: Unit[] = [];
  const n = text.length;
  let prevWord = "";
  let i = 0;
  while (i < n) {
    const c = text[i];
    let j = i + 1;
    if (SPACE.test(c)) {
      while (j < n && SPACE.test(text[j])) j++;
      units.push({ kind: "space", from: i, chars: 1, phonemes: [] });
    } else if (DIGIT.test(c)) {
      while (j < n && DIGIT.test(text[j])) j++;
      const spelled = spellNumber(text.slice(i, j));
      units.push({ kind: "number", from: i, chars: spelled.length, phonemes: numberPhonemes(spelled, i, j) });
      prevWord = "";
    } else if (LETTER.test(c)) {
      while (j < n) {
        if (LETTER.test(text[j]) || MARK.test(text[j])) j++;
        else if (JOINER.test(text[j]) && j + 1 < n && LETTER.test(text[j + 1])) j++;
        else break;
      }
      const phonemes: PhonemeToken[] = [];
      prevWord = pronounceWordUnit(text, i, j, prevWord, phonemes);
      units.push({ kind: "word", from: i, chars: j - i, phonemes });
    } else {
      while (j < n && !SPACE.test(text[j]) && !DIGIT.test(text[j]) && !LETTER.test(text[j])) j++;
      const pause = PAUSE_PUNCT.test(text.slice(i, j));
      if (pause) prevWord = "";
      units.push({ kind: pause ? "pause" : "symbol", from: i, chars: j - i, phonemes: [] });
    }
    i = j;
  }
  return units;
}

/** Phonèmes du texte, dans l'ordre (tests et debug). */
export function frenchPhonemes(text: string): PhonemeToken[] {
  return analyze(text).flatMap((u) => u.phonemes);
}

/** Longueur temporelle d'un texte en caractères : blancs repliés, nombres
 * comptés en toutes lettres. `durée = msPerChar × spokenLength`. */
export function spokenLength(text: string): number {
  return analyze(text).reduce((sum, u) => sum + u.chars, 0);
}

/** Variation déterministe dans [0, 1) — même texte, même bouche. */
function hash01(x: number): number {
  const v = Math.sin(x * 12.9898 + 78.233) * 43758.5453;
  return v - Math.floor(v);
}

/**
 * Frames de visèmes d'un segment prononcé. `start` est l'index du segment
 * dans la réponse complète (−1 : pas de position, les frames portent −1).
 *
 * Les blancs et la ponctuation ont une durée fixe ; le reste du budget du
 * segment se répartit sur les phonèmes au prorata de leur durée relative —
 * un mot dure donc ce qu'il se prononce (« eaux » est une voyelle, pas
 * quatre lettres), et le total reste `msPerChar × spokenLength(text)`.
 */
export function frenchVisemeFrames(text: string, msPerChar: number, start = -1): VisemeFrame[] {
  const ms = Number.isFinite(msPerChar) && msPerChar > 0 ? msPerChar : 0;
  const units = analyze(text);
  const total = ms * units.reduce((sum, u) => sum + u.chars, 0);

  interface Draft {
    viseme: Viseme;
    weight: number;
    length: number;
    at: number;
    fixed: boolean;
    gap?: boolean;
  }
  const drafts: Draft[] = [];
  let lastVowel = -1;
  const lengthen = () => {
    if (lastVowel >= 0) drafts[lastVowel].length *= FINAL_LENGTHENING;
    lastVowel = -1;
  };

  for (const unit of units) {
    switch (unit.kind) {
      case "space":
        drafts.push({ viseme: "sil", weight: 0, length: ms * SPACE_GAP_SHARE, at: unit.from, fixed: true, gap: true });
        break;
      case "symbol":
        drafts.push({ viseme: "sil", weight: 0, length: ms * unit.chars, at: unit.from, fixed: true, gap: true });
        break;
      case "pause":
        lengthen();
        drafts.push({ viseme: "sil", weight: 0, length: ms * unit.chars, at: unit.from, fixed: true });
        break;
      case "word":
      case "number":
        for (const token of unit.phonemes) {
          const p = PHONEMES[token.ph];
          if (p.vowel) lastVowel = drafts.length;
          const jitter = 1 - WEIGHT_JITTER / 2 + WEIGHT_JITTER * hash01(token.at + drafts.length);
          drafts.push({
            viseme: p.viseme,
            weight: Math.min(1, p.weight * (p.vowel ? jitter : 1)),
            length: p.length,
            at: token.at,
            fixed: false,
          });
        }
        break;
    }
  }
  lengthen();

  let fixed = 0;
  let relative = 0;
  for (const d of drafts) {
    if (d.fixed) fixed += d.length;
    else relative += d.length;
  }
  const free = Math.max(0, total - fixed);

  const frames: VisemeFrame[] = drafts.map((d) => {
    const frame: VisemeFrame = {
      viseme: d.viseme,
      weight: d.weight,
      duration: d.fixed ? d.length : relative > 0 ? (free * d.length) / relative : 0,
      charOffset: start >= 0 ? start + d.at : -1,
    };
    if (d.gap) frame.gap = true;
    return frame;
  });
  // Rien d'articulé (« … ») : le temps restant tient sur la dernière frame
  // plutôt que de disparaître du budget.
  if (relative === 0 && free > 0 && frames.length > 0) frames[frames.length - 1].duration += free;
  return frames;
}
