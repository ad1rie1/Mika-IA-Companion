import { describe, expect, it } from "vitest";
import { contentType, extRoots, resolveExt } from "./extAssets";

const roots = extRoots("/depot/");

describe("resolveExt", () => {
  it("sert un nom attendu sous son préfixe", () => {
    expect(resolveExt("/ext/fonts/Inter-Regular.woff2", roots)).toBe("/depot/backendv2/src/mika/inspector/static/fonts/Inter-Regular.woff2");
    expect(resolveExt("/ext/avatar/manifest.json?v=2", roots)).toBe("/depot/frontend/Android/app/src/main/assets/avatar/manifest.json");
    expect(resolveExt("/ext/avatar/curious.blink.webp", roots)).toBe("/depot/frontend/Android/app/src/main/assets/avatar/curious.blink.webp");
    expect(resolveExt("/ext/models/default.vrm", roots)).toBe("/depot/frontend/Web/public/models/default.vrm");
  });

  it("ne laisse rien sortir d'autre du disque", () => {
    for (const url of [
      "/ext/fonts/../../../../etc/passwd",
      "/ext/fonts/..%2F..%2Fsecret.woff2",
      "/ext/avatar/%2e%2e/manifest.json",
      "/ext/avatar/sub/happy.webp",
      "/ext/avatar/.hidden.webp",
      "/ext/models/room.glb",
      "/ext/models/default.vrm%00.txt",
      "/ext/fonts/x%ZZ.woff2",
      "/ext/fonts/",
      "/ext/other/a.webp",
      "/src/main.ts",
      undefined,
    ]) {
      expect(resolveExt(url, roots), String(url)).toBeNull();
    }
  });

  it("donne le bon type", () => {
    expect(contentType("a/b.woff2")).toBe("font/woff2");
    expect(contentType("a/manifest.json")).toBe("application/json; charset=utf-8");
    expect(contentType("a/default.vrm")).toBe("model/gltf-binary");
    expect(contentType("a/x.bin")).toBe("application/octet-stream");
  });
});
