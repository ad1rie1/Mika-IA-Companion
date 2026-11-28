import { describe, expect, it } from "vitest";
import { FileBlobs, FileLoadError } from "./blobs";

const blob = (n: number): Blob => new Blob([new Uint8Array(n)]);

describe("les octets des fichiers du chat, lus une fois (ADR 0312)", () => {
  it("un fichier demandé plusieurs fois à la fois ne se lit qu'une fois, puis reste", async () => {
    let reads = 0;
    const blobs = new FileBlobs(1000, async () => {
      reads += 1;
      return blob(10);
    });
    const [a, b] = await Promise.all([blobs.load("/files/x"), blobs.load("/files/x")]);
    expect(a).toBe(b);
    await blobs.load("/files/x");
    expect(reads).toBe(1);
    expect(blobs.cached("/files/x")).toMatch(/^blob:/);
  });

  it("borné : les plus anciennement vus partent d'abord", async () => {
    const blobs = new FileBlobs(25, async () => blob(10));
    await blobs.load("/files/a");
    await blobs.load("/files/b");
    blobs.cached("/files/a"); // revu : il devient le plus récent
    await blobs.load("/files/c");
    expect(blobs.has("/files/a")).toBe(true);
    expect(blobs.has("/files/b")).toBe(false);
    expect(blobs.has("/files/c")).toBe(true);
  });

  it("une copie locale se lit sans le serveur ; absente, elle ne se demande jamais au serveur", async () => {
    let reads = 0;
    const blobs = new FileBlobs(1000, async () => {
      reads += 1;
      return blob(1);
    });
    blobs.putLocal("local:c1:0", blob(3));
    expect((await blobs.load("local:c1:0")).size).toBe(3);
    await expect(blobs.load("local:c2:0")).rejects.toBeInstanceOf(FileLoadError);
    expect(reads).toBe(0);
  });

  it("un échec se retient : trop de téléchargements, une minute ; le réseau, un instant ; retiré, toute la session", async () => {
    let now = 0;
    let reads = 0;
    let answer: number | "ok" = 429;
    const blobs = new FileBlobs(1000, async () => {
      reads += 1;
      if (answer !== "ok") throw new FileLoadError(answer);
      return blob(2);
    }, () => now);
    await expect(blobs.load("/files/x")).rejects.toThrow("Trop de téléchargements");
    await expect(blobs.load("/files/x")).rejects.toThrow("Trop de téléchargements");
    expect(reads).toBe(1); // le fil redessiné ne relance pas la lecture
    now = 61_000;
    answer = 0;
    await expect(blobs.load("/files/x")).rejects.toThrow("injoignable");
    now = 62_000;
    await expect(blobs.load("/files/x")).rejects.toThrow("injoignable");
    expect(reads).toBe(2);
    now = 67_000;
    answer = 410;
    await expect(blobs.load("/files/x")).rejects.toThrow("retiré");
    now = 10_000_000;
    answer = "ok";
    await expect(blobs.load("/files/x")).rejects.toThrow("retiré");
    expect(reads).toBe(3);
    expect((await blobs.load("/files/y")).size).toBe(2); // un autre fichier, lui, se lit
  });
});
