import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { MODEL_URLS, VTuberModel } from "../VTuberModel";

const OWN = { tag: "own" } as unknown as VRM;
const FREE = { tag: "free" } as unknown as VRM;

function modelWith(present: ReadonlySet<string>) {
  const model = new VTuberModel(new THREE.Scene());
  const load = vi.spyOn(model, "load").mockImplementation(async (url: string) => {
    if (!present.has(url)) throw new Error(`404 ${url}`);
    return url === MODEL_URLS[0] ? OWN : FREE;
  });
  return { model, load };
}

describe("which model she wears (ADR 0252)", () => {
  it("her own model first, when it is there", async () => {
    const { model, load } = modelWith(new Set(MODEL_URLS));
    await expect(model.loadFirst(MODEL_URLS)).resolves.toBe(OWN);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("the free model the repository ships, when hers is missing", async () => {
    const { model, load } = modelWith(new Set([MODEL_URLS[1]]));
    await expect(model.loadFirst(MODEL_URLS)).resolves.toBe(FREE);
    expect(load.mock.calls.map((c) => c[0])).toEqual([...MODEL_URLS]);
  });

  it("no model at all: the last error, so the page can run without one", async () => {
    const { model } = modelWith(new Set());
    await expect(model.loadFirst(MODEL_URLS)).rejects.toThrow(MODEL_URLS[1]);
  });
});
