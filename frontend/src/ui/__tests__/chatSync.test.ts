import { describe, it, expect } from "vitest";
import {
  ackReason,
  applyAck,
  bindServerId,
  coerceStatus,
  cursorOf,
  mergeHistory,
  sortMessages,
  stripProsody,
} from "../chatSync";
import type { StoredMessage } from "../chatSync";
import type { HistoryEntry } from "../../types";

const MAX = 50;

function entry(
  id: number,
  role: string,
  text: string,
  ts = id * 1000
): HistoryEntry {
  return { id, role, text, ts };
}

function local(
  text: string,
  sender: "user" | "vtuber",
  extra: Partial<StoredMessage> = {}
): StoredMessage {
  return { text, sender, ts: Date.now(), ...extra };
}

describe("cursorOf", () => {
  it("is the highest server id actually held", () => {
    expect(
      cursorOf([
        local("a", "user", { id: 4 }),
        local("b", "vtuber", { id: 9 }),
        local("c", "user", { id: 7 }),
      ])
    ).toBe(9);
  });

  it("ignores messages that exist only in this browser", () => {
    // An optimistic bubble has no id yet. Counting it would let the cursor
    // claim delivery of a row the server has not written.
    expect(cursorOf([local("pas encore envoye", "user", { cid: "c1" })])).toBe(0);
  });

  it("is zero on an empty thread rather than undefined", () => {
    expect(cursorOf([])).toBe(0);
  });
});

describe("sortMessages", () => {
  it("orders by server id, not by local timestamp", () => {
    // The two clocks disagree by however long a message sat in the outbox:
    // the bubble is stamped by the browser, its row by the database.
    const history = [
      local("deuxieme", "user", { id: 2, ts: 1_000 }),
      local("premier", "user", { id: 1, ts: 9_999 }),
    ];
    expect(sortMessages(history).map((m) => m.text)).toEqual([
      "premier",
      "deuxieme",
    ]);
  });

  it("puts un-persisted messages last", () => {
    // They have not been written, so by construction they are the newest.
    const history = [
      local("en attente", "user", { cid: "c1", ts: 1 }),
      local("ecrit", "user", { id: 5, ts: 99_999 }),
    ];
    expect(sortMessages(history).map((m) => m.text)).toEqual([
      "ecrit",
      "en attente",
    ]);
  });

  it("places a message that will never have an id where it arrived", () => {
    // A project report is shown in the thread but is not a `Message` row.
    // Treated as un-persisted it meant "newest", so it stayed pinned to the
    // bottom below every reply that came after it, for the whole session.
    const history = [
      local("question", "user", { id: 10 }),
      local("[Projet] fini", "vtuber", { after: 10, ts: 5 }),
      local("reponse plus tard", "vtuber", { id: 11 }),
    ];
    expect(sortMessages(history).map((m) => m.text)).toEqual([
      "question",
      "[Projet] fini",
      "reponse plus tard",
    ]);
  });

  it("still sorts a queued message last, after a local-only one", () => {
    const history = [
      local("pas encore envoye", "user", { cid: "c1", ts: 1 }),
      local("[Projet] fini", "vtuber", { after: 3, ts: 999 }),
    ];
    expect(sortMessages(history).map((m) => m.text)).toEqual([
      "[Projet] fini",
      "pas encore envoye",
    ]);
  });

  it("orders un-persisted messages among themselves by local time", () => {
    const history = [
      local("b", "user", { cid: "c2", ts: 200 }),
      local("a", "user", { cid: "c1", ts: 100 }),
    ];
    expect(sortMessages(history).map((m) => m.text)).toEqual(["a", "b"]);
  });
});

describe("mergeHistory", () => {
  it("inserts what the client missed", () => {
    const history: StoredMessage[] = [local("ma question", "user", { id: 1 })];
    const { history: out, added } = mergeHistory(
      history,
      [entry(2, "assistant", "la reponse ratee")],
      MAX
    );
    expect(added).toBe(1);
    expect(out.map((m) => m.text)).toEqual(["ma question", "la reponse ratee"]);
  });

  it("does not duplicate a message it already holds", () => {
    const history: StoredMessage[] = [local("deja la", "vtuber", { id: 7 })];
    const { added } = mergeHistory(history, [entry(7, "assistant", "deja la")], MAX);
    expect(added).toBe(0);
    expect(history).toHaveLength(1);
  });

  it("adopts the id of a bubble it painted itself", () => {
    // The reconnect case: a message flushed from the outbox has no id until
    // the server answers, so without adoption every reconnect would paint it
    // a second time.
    const mine = local("envoye pendant la coupure", "user", { cid: "c1" });
    const history = [mine];
    const { added } = mergeHistory(
      history,
      [entry(12, "user", "envoye pendant la coupure")],
      MAX
    );
    expect(added).toBe(0);
    expect(history).toHaveLength(1);
    expect(mine.id).toBe(12);
    expect(mine.status).toBe("sent");
  });

  it("strips prosodic tokens from a replayed reply", () => {
    // They are TTS stage directions. A catch-up must not show what a live
    // frame would have hidden — the same message would read differently
    // depending on whether you were connected when she said it.
    const history: StoredMessage[] = [];
    const { history: out } = mergeHistory(
      history,
      [entry(3, "assistant", "Encore une danse ! [LAUGH] Bravo.")],
      MAX
    );
    expect(out[0].text).toBe("Encore une danse! Bravo.");
  });

  it("leaves a user message untouched", () => {
    // Only Mika emits prosody; mangling what the user typed would be a lie
    // about their own words.
    const history: StoredMessage[] = [];
    const { history: out } = mergeHistory(
      history,
      [entry(3, "user", "regarde [PAUSE:200] ca")],
      MAX
    );
    expect(out[0].text).toBe("regarde [PAUSE:200] ca");
  });

  it("reports whether a reply arrived", () => {
    // The caller uses it to stop the typing indicator: something answered.
    const a = mergeHistory([], [entry(1, "user", "moi")], MAX);
    expect(a.sawReply).toBe(false);
    const b = mergeHistory([], [entry(2, "assistant", "elle")], MAX);
    expect(b.sawReply).toBe(true);
  });

  it("interleaves a missed reply before what was typed after it", () => {
    // Append-only rendering cannot express this: the reply that arrived
    // while the tab was away belongs *before* the messages typed since.
    const history: StoredMessage[] = [
      local("question", "user", { id: 1 }),
      local("tape depuis", "user", { cid: "c9" }),
    ];
    const { history: out } = mergeHistory(
      history,
      [entry(2, "assistant", "la reponse manquee")],
      MAX
    );
    expect(out.map((m) => m.text)).toEqual([
      "question",
      "la reponse manquee",
      "tape depuis",
    ]);
  });

  it("keeps the newest when the thread exceeds the ceiling", () => {
    const history: StoredMessage[] = [];
    const entries = Array.from({ length: 6 }, (_, i) =>
      entry(i + 1, "user", `m${i}`)
    );
    const { history: out } = mergeHistory(history, entries, 3);
    expect(out.map((m) => m.text)).toEqual(["m3", "m4", "m5"]);
  });

  it("ignores rows with no id and empty text", () => {
    const history: StoredMessage[] = [];
    const { added } = mergeHistory(
      history,
      [
        { id: undefined as unknown as number, role: "user", text: "x", ts: 1 },
        entry(4, "assistant", "   "),
      ],
      MAX
    );
    expect(added).toBe(0);
  });

  it("reports an adoption as a change even though nothing appears", () => {
    // The caller persists on `changed`. Counting only `added` left the
    // freshly-attached server ids unsaved — and those ids *are* the cursor,
    // so the next reload asked the server again for what was already shown.
    const mine = local("envoye pendant la coupure", "user", { cid: "c1" });
    const { added, adopted } = mergeHistory(
      [mine],
      [entry(12, "user", "envoye pendant la coupure")],
      MAX
    );
    expect(added).toBe(0);
    expect(adopted).toBe(1);
  });

  it("adopts a message whose bubble shows more than the server stores", () => {
    // A message with files is painted `texte [photo.png]` while the row
    // holds the caption alone, so matching on the bubble's text could never
    // adopt it and a reconnect drew the same message twice.
    const mine = local("regarde ça [photo.png]", "user", {
      cid: "c1",
      matchText: "regarde ça",
    });
    const { added, adopted } = mergeHistory(
      [mine],
      [entry(5, "user", "regarde ça")],
      MAX
    );
    expect(added).toBe(0);
    expect(adopted).toBe(1);
    expect(mine.id).toBe(5);
    // What is displayed is untouched: the files are still part of what was
    // sent, even though they live in another store.
    expect(mine.text).toBe("regarde ça [photo.png]");
  });

  it("adopts when the server text is the caption plus what the files became", () => {
    // The real shape. Preprocessing replaces the image part with its
    // caption *before* the message is persisted, so the row holds neither
    // what was typed nor what was displayed — it holds what was typed,
    // extended. Exact matching on `matchText` alone still failed here.
    const mine = local("regarde ça [chat.png]", "user", {
      cid: "c1",
      matchText: "regarde ça",
    });
    const { adopted } = mergeHistory(
      [mine],
      [entry(5, "user", "regarde ça [image: un chat roux dort sur un canapé]")],
      MAX
    );
    expect(adopted).toBe(1);
    expect(mine.id).toBe(5);
  });

  it("never lets an attachment-only bubble match any user row", () => {
    // With no caption there is nothing to anchor on, and an empty prefix
    // matches everything. Such a message stays recognisable through its
    // client_msg_id instead; adopting the wrong row is far worse than
    // drawing this one twice.
    const mine = local("[chat.png]", "user", { cid: "c1", matchText: "" });
    const { adopted, added } = mergeHistory(
      [mine],
      [entry(5, "user", "un message sans aucun rapport")],
      MAX
    );
    expect(adopted).toBe(0);
    expect(added).toBe(1);
    expect(mine.id).toBeUndefined();
  });

  it("clears a stale failure when the message turns out to have landed", () => {
    const mine = local("parti quand meme", "user", {
      cid: "c1",
      status: "failed",
      reason: "trop de messages d'affilée",
    });
    mergeHistory([mine], [entry(3, "user", "parti quand meme")], MAX);
    expect(mine.status).toBe("sent");
    expect(mine.reason).toBeUndefined();
  });

  it("tolerates a missing message list", () => {
    // A malformed frame must not take the thread down.
    const history: StoredMessage[] = [local("a", "user", { id: 1 })];
    expect(() =>
      mergeHistory(history, undefined as unknown as HistoryEntry[], MAX)
    ).not.toThrow();
  });
});

describe("applyAck", () => {
  it("marks an accepted message as sent", () => {
    const history = [local("coucou", "user", { cid: "c1", status: "pending" })];
    expect(applyAck(history, "c1", "accepted")).toEqual({
      changed: true,
      failed: false,
    });
    expect(history[0].status).toBe("sent");
  });

  it("marks a refusal as failed rather than leaving it pending", () => {
    // Pending reads as "on its way". A rate-limited message is not on its
    // way; no reply is ever coming.
    const history = [local("spam", "user", { cid: "c1", status: "pending" })];
    expect(applyAck(history, "c1", "rate_limited").failed).toBe(true);
    expect(history[0].status).toBe("failed");
  });

  it("ignores an ack for a message it does not know", () => {
    const history = [local("coucou", "user", { cid: "c1" })];
    expect(applyAck(history, "inconnu", "accepted").changed).toBe(false);
  });

  it("records why it failed, not just that it did", () => {
    // "Too many messages" and "your files were rejected" are different
    // problems with different fixes; one shrug made them look identical.
    const history = [local("x", "user", { cid: "c1", status: "pending" })];
    applyAck(history, "c1", "attachments_rejected");
    expect(history[0].reason).toContain("pièces jointes");
  });

  it("treats a status it has never heard of as a refusal", () => {
    // A backend that grows a new refusal must not silently read as success
    // on an older client.
    const history = [local("x", "user", { cid: "c1", status: "pending" })];
    expect(applyAck(history, "c1", "quelque_chose_de_neuf").failed).toBe(true);
    expect(history[0].reason).toBe("refusé par le serveur");
  });
});

describe("ackReason", () => {
  it("names the refusals the consumer can actually send", () => {
    expect(ackReason("overloaded")).toContain("saturée");
    expect(ackReason("too_long")).toContain("trop long");
    expect(ackReason("rate_limited")).toContain("messages");
  });
});

describe("bindServerId", () => {
  it("binds the id the reply reports for the question", () => {
    const history = [local("question", "user", { cid: "c1", status: "pending" })];
    expect(bindServerId(history, "c1", 42)).toBe(true);
    expect(history[0].id).toBe(42);
    expect(history[0].status).toBe("sent");
  });

  it("still confirms delivery when the server sent no id", () => {
    // persist=False turns exist; the message was received either way.
    const history = [local("question", "user", { cid: "c1", status: "pending" })];
    expect(bindServerId(history, "c1", undefined)).toBe(true);
    expect(history[0].id).toBeUndefined();
    expect(history[0].status).toBe("sent");
  });
});

describe("coerceStatus", () => {
  it("keeps the three known states", () => {
    expect(coerceStatus("sent")).toBe("sent");
    expect(coerceStatus("pending")).toBe("pending");
    expect(coerceStatus("failed")).toBe("failed");
  });

  it("drops anything else", () => {
    // A stale cache from an older build would otherwise render a CSS class
    // that does not exist — invisible, and indistinguishable from delivered.
    expect(coerceStatus("delivered")).toBeUndefined();
    expect(coerceStatus(undefined)).toBeUndefined();
    expect(coerceStatus(7)).toBeUndefined();
  });
});

describe("stripProsody", () => {
  it("removes stage directions and emotion tags", () => {
    expect(stripProsody("Salut [SIGH] ca va ? [EMOTION:happy:0.8]")).toBe(
      "Salut ca va?"
    );
  });

  it("closes the gap a removed token leaves before punctuation", () => {
    // Note this also eats a *legitimate* French space before ! ? ; :
    // — pre-existing behaviour, asserted here as it is rather than
    // quietly changed: it decides how every bubble reads.
    expect(stripProsody("Ah [PAUSE:400] !")).toBe("Ah!");
  });
});
