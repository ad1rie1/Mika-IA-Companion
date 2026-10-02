/**
 * Where the body punctuates a sentence — pure text analysis, no three.js.
 *
 * People do not talk with a still head over a looping clip: the head dips
 * on the words they stress, the brows flash on emphasis, a question ends
 * with the chin up and the head tilted, a statement lands with a small
 * nod, and every clause starts on a quick breath. These beats are what a
 * listener reads as "she means what she says" (McNeill's beat gestures;
 * Graf et al. 2002 on head motion and prosody).
 *
 * The voice gives no prosody to read (Web Speech exposes no audio), so the
 * beats are placed on the TEXT and fired when the speech cursor — the
 * character the voice is at, kept in sync by the lip-sync — reaches them.
 * Indices are positions in the full reply text, the same contract as the
 * lip-sync frames.
 *
 * French specifics: stress falls at the END of a rhythmic group (the last
 * content word before a pause carries the beat), and emphasis ("accent
 * d'insistance") goes to intensifiers and words written in capitals.
 */

export type BeatKind =
  /** First word of a clause: a quick breath, the head lifts a little. */
  | "phraseStart"
  /** A stressed content word: a small nod. */
  | "stress"
  /** Insistence — intensifier, CAPS, *word*, an exclamation: a bigger nod
   * and a brow flash. */
  | "emphasis"
  /** Comma, colon, semicolon: the head reorients, a quick breath. */
  | "pause"
  /** "…" — trailing off: a soft tilt, eyes may wander. */
  | "trail"
  /** Last word of a question: chin up, head tilted, brows held up. */
  | "question"
  /** Last word of a statement: the nod that closes it. */
  | "final";

export interface SpeechBeat {
  /** Character index in the full reply text. */
  at: number;
  kind: BeatKind;
  /** 0…1 — scales the motion. */
  strength: number;
}

const STOPWORDS = new Set([
  "le", "la", "les", "un", "une", "des", "de", "du", "d", "l", "et", "ou", "mais",
  "donc", "or", "ni", "car", "que", "qu", "qui", "quoi", "je", "j", "tu", "il",
  "elle", "on", "nous", "vous", "ils", "elles", "me", "m", "te", "t", "se", "s",
  "ma", "ta", "sa", "mon", "ton", "son", "mes", "tes", "ses", "notre", "votre",
  "nos", "vos", "leur", "leurs", "ce", "cet", "cette", "ces", "c", "ça", "ca",
  "en", "y", "à", "a", "au", "aux", "dans", "par", "pour", "sur", "avec", "sans",
  "sous", "chez", "ne", "n", "pas", "plus", "est", "es", "suis", "sont", "ai",
  "as", "avait", "était", "être", "avoir", "fait", "faire", "dit", "lui", "moi",
  "toi", "si", "comme", "quand", "alors", "aussi", "bien", "oui", "non", "là",
  "the", "a", "an", "and", "or", "to", "of", "in", "is", "it", "you", "i",
]);

const INTENSIFIERS = new Set([
  "très", "vraiment", "trop", "tellement", "super", "jamais", "absolument",
  "carrément", "grave", "hyper", "énormément", "toujours", "rien", "tout",
  "totalement", "complètement", "franchement", "adore", "déteste", "génial",
  "incroyable", "magnifique", "horrible", "énorme",
]);

/** Minimum characters between two stress beats, and the gap past which a
 * content word gets one regardless (a long clause still moves). */
const STRESS_GAP = 10;
const FORCE_GAP = 30;

interface Word {
  text: string;
  start: number;
  /** Written in capitals (≥ 2 letters) or wrapped in *asterisks*. */
  shouted: boolean;
}

/** Prosody / control tokens the voice never says: [SIGH], [PAUSE:300]… */
const TOKEN = /\[[A-Z_]+(?::[^\]]*)?\]/g;

function maskTokens(text: string): string {
  return text.replace(TOKEN, (m) => " ".repeat(m.length));
}

export function planSpeechBeats(text: string): SpeechBeat[] {
  const masked = maskTokens(text);
  const beats: SpeechBeat[] = [];

  // Sentences end on . ! ? … (runs collapsed); the terminator decides the
  // closing beat. Text after the last terminator is a sentence too.
  const sentence = /[^.!?…]+(?:[.!?…]+|$)/g;
  let m: RegExpExecArray | null;
  while ((m = sentence.exec(masked)) !== null) {
    if (m[0].trim().length === 0) {
      if (m.index === sentence.lastIndex) sentence.lastIndex++;
      continue;
    }
    planSentence(masked, m.index, m[0], beats);
  }
  beats.sort((a, b) => a.at - b.at || rank(b.kind) - rank(a.kind));
  // One beat per character position — the strongest kind wins.
  return beats.filter((b, i) => i === 0 || beats[i - 1].at !== b.at);
}

function rank(kind: BeatKind): number {
  return { question: 6, emphasis: 5, final: 4, trail: 3, stress: 2, pause: 1, phraseStart: 0 }[kind];
}

function planSentence(text: string, offset: number, sentence: string, out: SpeechBeat[]): void {
  const words: Word[] = [];
  const wordRe = /\*?[\p{L}\p{N}][\p{L}\p{N}'’-]*\*?/gu;
  let w: RegExpExecArray | null;
  while ((w = wordRe.exec(sentence)) !== null) {
    const raw = w[0];
    const starred = raw.length > 2 && raw.startsWith("*") && raw.endsWith("*");
    const clean = raw.replace(/\*/g, "");
    const letters = clean.replace(/[^\p{L}]/gu, "");
    const shouted =
      starred || (letters.length >= 2 && letters === letters.toUpperCase() && letters !== letters.toLowerCase());
    words.push({ text: clean, start: offset + w.index + (raw.startsWith("*") ? 1 : 0), shouted });
  }
  if (words.length === 0) return;

  const terminator = sentence.trimEnd().match(/[.!?…]+$/)?.[0] ?? "";
  const exclaim = terminator.includes("!");

  out.push({ at: words[0].start, kind: "phraseStart", strength: 0.6 });

  let lastBeat = words[0].start;
  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    const lower = word.text.toLowerCase().replace(/^[dlmtsjcnq][’']/, "");
    const content = !STOPWORDS.has(lower) && lower.length >= 4;
    const gap = word.start - lastBeat;

    if (word.shouted || INTENSIFIERS.has(lower)) {
      if (gap >= 6 || i === 0) {
        out.push({ at: word.start, kind: "emphasis", strength: word.shouted ? 1 : 0.8 });
        lastBeat = word.start;
      }
      continue;
    }

    // Clause punctuation right after this word: the word closes a rhythmic
    // group — French puts the stress there.
    const end = word.start - offset + word.text.length;
    const after = sentence.slice(end).match(/^\s*([,;:]|\.\.\.|…)?/)?.[1];
    if (after === "," || after === ";" || after === ":") {
      if (content && gap >= 6) {
        out.push({ at: word.start, kind: "stress", strength: 0.75 });
        lastBeat = word.start;
      }
      const at = offset + end + sentence.slice(end).indexOf(after);
      out.push({ at, kind: "pause", strength: 0.6 });
      continue;
    }

    if (content && (gap >= STRESS_GAP || (gap >= FORCE_GAP && lower.length >= 3))) {
      out.push({ at: word.start, kind: "stress", strength: Math.min(1, 0.45 + lower.length * 0.05) });
      lastBeat = word.start;
    }
  }

  // The closing beat sits on the last word: the head moves WITH it, not
  // after the voice has stopped.
  const last = words[words.length - 1];
  const kind: BeatKind = terminator.includes("?")
    ? "question"
    : terminator.includes("…") || terminator.startsWith("...")
      ? "trail"
      : exclaim
        ? "emphasis"
        : "final";
  // Anything already placed within a few characters of the closing beat
  // would only blur it.
  for (let i = out.length - 1; i >= 0; i--) {
    const b = out[i];
    if (b.at >= last.start - 5 && b.at <= last.start + last.text.length && b.kind !== "phraseStart") {
      out.splice(i, 1);
    }
  }
  out.push({ at: last.start, kind, strength: kind === "emphasis" ? 0.9 : 0.8 });
}
