import { describe, expect, it } from "vitest";
import {
  PHONEMES,
  frenchPhonemes,
  frenchVisemeFrames,
  spellNumber,
  spokenLength,
  type VisemeFrame,
} from "../frenchVisemes";

const phonemes = (text: string) => frenchPhonemes(text).map((t) => t.ph).join(" ");
const visemes = (frames: VisemeFrame[]) => frames.filter((f) => f.viseme !== "sil").map((f) => f.viseme);
const totalMs = (frames: VisemeFrame[]) => frames.reduce((sum, f) => sum + f.duration, 0);
const collapsed = (text: string) => text.replace(/\s+/g, " ").length;

describe("French grapheme → phoneme", () => {
  it.each([
    ["eau", "o"],
    ["oiseau", "w a z o"],
    ["champagne", "S a~ p a J"],
    ["ils mangent", "i l m a~ Z"],
    ["beaucoup", "b o k u"],
    ["qu'est-ce que", "k E s @ k @"],
    ["Mika", "m i k a"],
    ["bonjour tout le monde", "b o~ Z u R t u l @ m o~ d"],
    ["c'est", "s E"],
    ["aujourd'hui", "o Z u R d H i"],
    ["les enfants", "l e a~ f a~"],
    ["fille", "f i j"],
    ["ville", "v i l"],
    ["nation", "n a s j o~"],
    ["question", "k E s t j o~"],
    ["photo", "f o t o"],
    ["garçon", "g a R s o~"],
    ["guitare", "g i t a R"],
    ["taxi", "t a k s i"],
    ["homme", "o m"],
    ["une", "y n"],
    ["bien", "b j e~"],
    ["science", "s j a~ s"],
    ["pain", "p e~"],
    ["loin", "l w e~"],
    ["oui", "w i"],
    ["étaient", "e t E"],
    ["parlent", "p a R l"],
    ["souvent", "s u v a~"],
    ["manger", "m a~ Z e"],
    ["samedi", "s a m d i"],
    ["petit", "p @ t i"],
    ["SMS", "E s E m E s"],
  ])("%s → %s", (text, expected) => {
    expect(phonemes(text)).toBe(expected);
  });

  it("numbers are read in full, as the voice says them", () => {
    expect(spellNumber("42")).toBe("quarante-deux");
    expect(spellNumber("71")).toBe("soixante et onze");
    expect(spellNumber("80")).toBe("quatre-vingts");
    expect(spellNumber("2026")).toBe("deux mille vingt-six");
    expect(spellNumber("0612")).toBe("zéro six un deux");
    expect(phonemes("42")).toBe("k a R a~ t d 2");
    expect(phonemes("2026")).toBe("d 2 m i l v e~ s i s");
    expect(phonemes("21")).toBe("v e~ e e~");
  });

  it("digraphs are one mouth shape, not one per letter", () => {
    // « eau » is one vowel; « qu » never rounds the lips; « gn » is no « g ».
    expect(visemes(frenchVisemeFrames("eau", 60))).toEqual(["oh"]);
    expect(visemes(frenchVisemeFrames("qu'est-ce que", 60))).not.toContain("ou");
    expect(visemes(frenchVisemeFrames("champagne", 60))).toEqual(["CH", "aa", "PP", "aa", "nn"]);
  });

  it("silent letters make no shape", () => {
    // « ils mangent » ends on the « g » ; « les » has no hiss.
    const mangent = visemes(frenchVisemeFrames("ils mangent", 60));
    expect(mangent[mangent.length - 1]).toBe("CH");
    expect(visemes(frenchVisemeFrames("les", 60))).toEqual(["nn", "E"]);
  });
});

describe("French viseme frames", () => {
  it("bilabials close the lips, labiodentals bite", () => {
    for (const word of ["papa", "beaucoup", "maman", "bonjour"]) {
      expect(visemes(frenchVisemeFrames(word, 60))[0]).toBe("PP");
    }
    expect(visemes(frenchVisemeFrames("photo", 60))[0]).toBe("FF");
    expect(visemes(frenchVisemeFrames("vous", 60))[0]).toBe("FF");
    const closure = frenchVisemeFrames("papa", 60).find((f) => f.viseme === "PP")!;
    expect(closure.weight).toBe(1);
  });

  it("vowels last longer than consonants", () => {
    const frames = frenchVisemeFrames("papa", 60);
    const pp = frames.filter((f) => f.viseme === "PP").map((f) => f.duration);
    const aa = frames.filter((f) => f.viseme === "aa").map((f) => f.duration);
    expect(Math.min(...aa)).toBeGreaterThan(Math.max(...pp) * 1.5);
    for (const [ph, p] of Object.entries(PHONEMES)) {
      if (p.vowel && ph !== "@") expect(p.length).toBeGreaterThan(0.85);
      if (!p.vowel) expect(p.length).toBeLessThan(0.7);
    }
  });

  it("every frame keeps the ORIGINAL index of what it articulates, in order", () => {
    const text = "Mika,  tu as vu l'oiseau ? Beaucoup d'eau — vraiment !";
    const start = 120;
    const frames = frenchVisemeFrames(text, 60, start);
    let last = -1;
    for (const f of frames) {
      expect(f.charOffset).toBeGreaterThanOrEqual(start);
      expect(f.charOffset).toBeLessThan(start + text.length);
      expect(f.charOffset).toBeGreaterThanOrEqual(last);
      last = f.charOffset;
      const ch = text[f.charOffset - start];
      // A shape sits on a letter; a pause on punctuation; a gap on a blank.
      if (f.viseme !== "sil") expect(ch).toMatch(/\p{L}/u);
      else if (f.gap) expect(ch).toMatch(/\s|[«»"()]/);
      else expect(ch).toMatch(/[.,;:!?…—–]/);
    }
    // « eau » of « oiseau » is one frame, anchored on its « e ».
    const oiseau = text.indexOf("oiseau");
    expect(frames.find((f) => f.charOffset === start + oiseau + 3)?.viseme).toBe("oh");
    expect(frames.some((f) => f.charOffset === start + oiseau + 4)).toBe(false);
    // Without a position, every frame says so.
    expect(frenchVisemeFrames(text, 60).every((f) => f.charOffset === -1)).toBe(true);
  });

  it("a segment lasts msPerChar × its length, whitespace collapsed", () => {
    const texts = [
      "bonjour tout le monde",
      "Mika,  tu es là ?",
      "qu'est-ce que tu fais ce soir",
      "  ils mangent des pommes… ",
      "« Hmm » (pff) !",
      "eau",
      "...",
    ];
    for (const text of texts) {
      for (const msPerChar of [30, 60, 75]) {
        expect(totalMs(frenchVisemeFrames(text, msPerChar, 0))).toBeCloseTo(msPerChar * collapsed(text), 6);
      }
      expect(spokenLength(text)).toBe(collapsed(text));
    }
  });

  it("a number lasts as long as its spoken form", () => {
    // « 2026 » is read « deux mille vingt-six » : 20 characters of voice.
    expect(spokenLength("en 2026")).toBe(3 + "deux mille vingt-six".length);
    expect(totalMs(frenchVisemeFrames("en 2026", 60, 0))).toBeCloseTo(60 * spokenLength("en 2026"), 6);
    const frames = frenchVisemeFrames("en 2026", 60, 10);
    const digits = frames.filter((f) => f.charOffset >= 13);
    expect(digits.length).toBeGreaterThan(6);
    expect(digits.every((f) => f.charOffset < 17)).toBe(true);
  });

  it("punctuation pauses close the mouth, blanks only glide", () => {
    const frames = frenchVisemeFrames("Mika, tu es là ?", 60, 0);
    const comma = frames.find((f) => f.charOffset === 4)!;
    expect(comma.viseme).toBe("sil");
    expect(comma.gap).toBeUndefined();
    const blank = frames.find((f) => f.charOffset === 5)!;
    expect(blank.gap).toBe(true);
    expect(blank.duration).toBeLessThan(60);
  });
});
