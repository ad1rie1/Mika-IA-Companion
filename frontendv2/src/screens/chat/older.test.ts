import { describe, expect, it } from "vitest";
import type { HistoryEntry } from "@web/types";
import { mergeHistory, trimThreads, userAttachments, withAttachments, type StoredMessage } from "@web/ui/chatSync";
import { mergeOlder, oldestLoaded, touchesLoaded, UNBOUNDED } from "./older";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();

const row = (id: number, text = `m${id}`, role = "assistant"): HistoryEntry => ({ id, role, text, ts: NOW + id });
const message = (id: number | undefined, extra: Partial<StoredMessage> = {}): StoredMessage => ({
  text: `m${id}`,
  sender: "vtuber",
  ts: NOW + (id ?? 999),
  id,
  ...extra,
});

describe("la remontée du fil avec elle (ADR 0215)", () => {
  it("repart du plus ancien message du fil avec elle, jamais d'un fil de travail ni d'une bulle sans identifiant", () => {
    expect(oldestLoaded([])).toBeUndefined();
    const history = [message(90, { strand: "devis" }), message(120), message(100), message(undefined)];
    expect(oldestLoaded(history)).toBe(100);
  });

  it("une trame touche ce qu'on a si l'une de ses lignes y est déjà", () => {
    const history = [message(10), message(11)];
    expect(touchesLoaded(history, [row(11), row(12)])).toBe(true);
    expect(touchesLoaded(history, [row(50), row(51)])).toBe(false);
    expect(touchesLoaded([], [])).toBe(false);
  });

  it("une page ancienne se range au-dessus, et une bulle en attente au même texte reste à elle", () => {
    const pending: StoredMessage = { text: "ok", sender: "user", ts: NOW, status: "failed", cid: "c1" };
    const merged = mergeOlder([message(100), pending], [{ id: 40, role: "user", text: "ok", ts: NOW - 5000 }]);
    expect(merged.map((m) => m.id)).toEqual([40, 100, undefined]);
    expect(merged[2].status).toBe("failed");
  });

  it("en mémoire, le fil chargé dépasse ce que garde le cache ; le cache, lui, se limite aux derniers", () => {
    const entries = Array.from({ length: 120 }, (_, i) => row(i + 1));
    const { history } = mergeHistory([], entries, UNBOUNDED);
    expect(history).toHaveLength(120);
    expect(trimThreads(history, 50, 12)).toHaveLength(50);
    const { history: capped } = mergeHistory([], entries, 50);
    expect(capped).toHaveLength(50);
  });
});

describe("les pièces d'un message de la personne (ADR 0215)", () => {
  const ID = "c".repeat(32);

  it("userAttachments garde le nom, la sorte, et une adresse seulement si elle est exactement /files/<id>", () => {
    expect(userAttachments([{ name: "a.png", kind: "image", id: ID, url: `/files/${ID}`, mime: "image/png", size: 8, available: true }])).toEqual([
      { name: "a.png", kind: "image", id: ID, url: `/files/${ID}`, mime: "image/png", size: 8, available: true },
    ]);
    expect(userAttachments([{ name: "a.png", kind: "image", id: ID, url: "https://ailleurs.fr/x" }])).toEqual([{ name: "a.png", kind: "image" }]);
    expect(userAttachments([{ name: "a.png", id: "pas-un-id", url: "/files/pas-un-id" }])).toEqual([{ name: "a.png", kind: "file" }]);
    expect(userAttachments("pas un tableau")).toEqual([]);
    expect(userAttachments([null, { kind: "image" }])).toEqual([]);
    expect(userAttachments([{ name: "a.png", id: ID, url: `/files/${ID}` }])[0].available).toBe(true);
    expect(userAttachments([{ name: "a.png", id: ID, url: `/files/${ID}`, available: false }])[0].available).toBe(false);
  });

  it("le fil relu garde les pièces à part, et leur adresse arrive quand la pièce a été gardée", () => {
    const first: HistoryEntry[] = [{ ...row(7, "regarde", "user"), attachments: [{ name: "note.txt", kind: "file" }] }];
    const { history } = mergeHistory([], first, 50);
    expect(history[0].attachments).toEqual([{ name: "note.txt", kind: "file" }]);
    expect(history[0].text).toBe(withAttachments("regarde", ["note.txt"])); // l'ancien client web s'en sert toujours

    const kept: HistoryEntry[] = [{
      ...row(7, "regarde", "user"),
      attachments: [{ name: "note.txt", kind: "file", id: ID, url: `/files/${ID}`, available: true }],
    }];
    const again = mergeHistory(history, kept, 50);
    expect(again.enriched).toBe(1);
    expect(again.history[0].attachments?.[0].url).toBe(`/files/${ID}`);
    expect(again.history[0].text).toBe("regarde [note.txt]");
    expect(mergeHistory(again.history, kept, 50).enriched).toBe(0);
  });

  it("un message sans pièce n'en gagne pas, et une bulle adoptée reçoit les siennes", () => {
    const { history } = mergeHistory([], [{ ...row(1, "bonjour", "user"), attachments: [] }], 50);
    expect(history[0].attachments).toBeUndefined();
    const bubble: StoredMessage = { text: "regarde [a.png]", sender: "user", ts: NOW, matchText: "regarde", attachments: [{ name: "a.png", kind: "image" }] };
    const adopted = mergeHistory([bubble], [{ ...row(9, "regarde", "user"), attachments: [{ name: "a.png", kind: "image" }] }], 50);
    expect(adopted.adopted).toBe(1);
    expect(adopted.history[0].attachments).toEqual([{ name: "a.png", kind: "image" }]);
  });
});
