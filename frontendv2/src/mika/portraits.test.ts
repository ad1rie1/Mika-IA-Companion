import { describe, expect, it } from "vitest";
import { avatarFrame, framePortrait, parseManifest, portraitOf } from "./portraits";

const raw = {
  version: 1,
  width: 1080,
  height: 1440,
  portraits: {
    neutral: { file: "neutral.webp", face: [0.5413, 0.2531], blink: { file: "neutral.blink.webp", x: 474, y: 302, w: 217, h: 103 } },
    curious: { file: "curious.webp", face: [0.5211, 0.223], blink: { file: "curious.blink.webp", x: 453, y: 237, w: 218, h: 126 } },
    sleep: { file: "sleep.webp", face: [0.5251, 0.2601] },
    broken: { file: "../secret.webp", face: [0.5, 0.5] },
    blinkless: { file: "x.webp", face: [0.5, 0.25], blink: { file: "y.webp", x: "?", y: 1, w: 1, h: 1 } },
    "Bad-Key": { file: "z.webp", face: [0.5, 0.5] },
    out: { file: "o.webp", face: [1.5, 0.5] },
  },
};

describe("parseManifest", () => {
  it("garde les entrées lisibles, écarte le reste une à une", () => {
    const m = parseManifest(raw)!;
    expect(m.width).toBe(1080);
    expect(Object.keys(m.portraits).sort()).toEqual(["blinkless", "curious", "neutral", "sleep"]);
    expect(m.portraits.sleep.blink).toBeNull();
    expect(m.portraits.blinkless.blink).toBeNull();
    expect(m.portraits.curious.blink).toEqual({ file: "curious.blink.webp", x: 453, y: 237, w: 218, h: 126 });
  });

  it("rien de lisible : null", () => {
    expect(parseManifest(null)).toBeNull();
    expect(parseManifest({ width: 1080, height: 1440, portraits: {} })).toBeNull();
    expect(parseManifest({ portraits: raw.portraits })).toBeNull();
  });

  it("un portrait absent retombe sur le neutre", () => {
    const m = parseManifest(raw)!;
    expect(portraitOf(m, "jealous")?.file).toBe("neutral.webp");
    expect(portraitOf(m, "curious")?.file).toBe("curious.webp");
    expect(portraitOf(null, "curious")).toBeNull();
  });
});

describe("framePortrait", () => {
  const m = parseManifest(raw)!;

  it("en grand : l'image à 2,05 fois la hauteur, le visage à 36 % et au centre", () => {
    const { image, blink } = framePortrait({ width: 370, height: 440 }, false, m.portraits.curious, m);
    expect(image.height).toBeCloseTo(440 * 2.05);
    const faceX = image.left + 0.5211 * image.width;
    const faceY = image.top + 0.223 * image.height;
    expect(faceX).toBeCloseTo(185);
    expect(faceY).toBeCloseTo(440 * 0.36);
    // le clignement posé à l'échelle de l'image, au bon endroit
    const s = image.height / 1440;
    expect(blink).toEqual({ left: image.left + 453 * s, top: image.top + 237 * s, width: 218 * s, height: 126 * s });
  });

  it("dans le rond : l'image à 5,4 fois la hauteur, le visage au centre", () => {
    const { image, blink } = framePortrait({ width: 34, height: 34 }, true, m.portraits.sleep, m);
    expect(image.height).toBeCloseTo(34 * 5.4);
    expect(image.left + 0.5251 * image.width).toBeCloseTo(17);
    expect(image.top + 0.2601 * image.height).toBeCloseTo(17);
    expect(blink).toBeNull();
  });
});

describe("avatarFrame", () => {
  it("centre le visage dans le rond, comme M.av de la maquette", () => {
    const m = parseManifest(raw)!;
    expect(avatarFrame(m.portraits.neutral, m)).toBe(
      `width:330%;left:${(50 - 0.5413 * 330).toFixed(1)}%;top:${(50 - 0.2531 * 330 * (1440 / 1080)).toFixed(1)}%`,
    );
  });
});
