import { afterEach, describe, expect, it, vi } from "vitest";
import { vrmUrls } from "./vrm";

describe("où chercher sa VRM (ADR 0252)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("la sienne d'abord, puis le modèle libre du dépôt", () => {
    vi.stubEnv("VITE_MIKA_VRM_URL", "");
    expect(vrmUrls()).toEqual(["/ext/models/default.vrm", "/ext/models/mika-libre.vrm"]);
  });

  it("une adresse donnée remplace les deux", () => {
    vi.stubEnv("VITE_MIKA_VRM_URL", " https://exemple.fr/mika.vrm ");
    expect(vrmUrls()).toEqual(["https://exemple.fr/mika.vrm"]);
  });
});
