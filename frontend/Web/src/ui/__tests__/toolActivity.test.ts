import { describe, expect, it } from "vitest";
import {
  argsPreview,
  cardKey,
  cardSummary,
  durationLabel,
  isRunning,
  MAX_CARDS,
  MAX_DETAIL_CHARS,
  outcomeLabel,
  placeCards,
  runningLabel,
  toolFrame,
  toolsLine,
  toolSteps,
  toolUses,
  withAnswer,
  withToolFrame,
} from "../toolActivity";
import type { Placeable, ToolFrame, WorkCard } from "../toolActivity";

const EP = "01JBEPISODE";

/** Une trame telle que le serveur l'envoie (`docs/protocole-chat.md`, ADR 0116). */
function raw(phase: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  const base: Record<string, unknown> = { type: "tool", episode: EP, reply_to: 811, phase, at: 1_000 };
  if (phase === "start") Object.assign(base, { call_id: "c1", name: "memory_search", args: '{"query": "Léa"}' });
  if (phase === "end") {
    Object.assign(base, {
      call_id: "c1", name: "memory_search", args: '{"query": "Léa"}', ok: true, result: "3 souvenirs", duration_ms: 182,
    });
  }
  if (phase === "note") base.text = "Je regarde dans ta boîte…";
  if (phase === "done") base.outcome = "done";
  return { ...base, ...over };
}

function frame(phase: string, over: Record<string, unknown> = {}): ToolFrame {
  const f = toolFrame(raw(phase, over));
  if (!f) throw new Error(`trame refusée : ${phase}`);
  return f;
}

/** Les cartes après une suite de trames. */
function play(...frames: ToolFrame[]): WorkCard[] {
  return frames.reduce<WorkCard[]>((cards, f) => withToolFrame(cards, f), []);
}

describe("toolFrame — validation", () => {
  it("lit les quatre phases", () => {
    expect(frame("start")).toMatchObject({ phase: "start", callId: "c1", name: "memory_search", replyTo: 811, at: 1_000 });
    expect(frame("end")).toMatchObject({ phase: "end", ok: true, result: "3 souvenirs", durationMs: 182 });
    expect(frame("note")).toMatchObject({ phase: "note", text: "Je regarde dans ta boîte…" });
    expect(frame("done")).toMatchObject({ phase: "done", outcome: "done" });
  });

  it("refuse ce qui ne vaut rien", () => {
    expect(toolFrame(null)).toBeNull();
    expect(toolFrame([])).toBeNull();
    expect(toolFrame(raw("start", { type: "speech" }))).toBeNull();
    expect(toolFrame(raw("explode"))).toBeNull();
    expect(toolFrame(raw("start", { episode: "" }))).toBeNull();
    expect(toolFrame(raw("start", { call_id: undefined }))).toBeNull();
    expect(toolFrame(raw("note", { text: "   " }))).toBeNull();
    for (const bad of [0, -3, 1.5, "811", Number.NaN]) {
      expect(toolFrame(raw("start", { reply_to: bad }))).toBeNull();
    }
  });

  it("prend des défauts sûrs pour ce qui manque", () => {
    expect(frame("start", { reply_to: null }).replyTo).toBeNull();
    expect(frame("start", { reply_to: undefined }).replyTo).toBeNull();
    expect(frame("start", { name: "" })).toMatchObject({ name: "outil" });
    expect(frame("end", { ok: "yes" })).toMatchObject({ ok: false });
    expect(frame("end", { duration_ms: -1 })).toMatchObject({ durationMs: null });
    expect(frame("done", { outcome: undefined })).toMatchObject({ outcome: "done" });
    expect(frame("start", { at: "hier" }).at).toBeNull();
  });

  it("borne arguments et résultats", () => {
    const long = "x".repeat(MAX_DETAIL_CHARS + 500);
    const f = frame("end", { args: long, result: long });
    expect(f.phase === "end" && f.args.length).toBe(MAX_DETAIL_CHARS);
    expect(f.phase === "end" && f.result.length).toBe(MAX_DETAIL_CHARS);
  });
});

describe("withToolFrame — fusion par reply_to et épisode", () => {
  it("la première trame d'un reply_to ouvre sa carte ; un outil parti tourne", () => {
    const [card] = play(frame("start"));
    expect(card.key).toBe("r:811");
    expect(isRunning(card)).toBe(true);
    expect(toolSteps(card)).toMatchObject([{ name: "memory_search", status: "running", args: '{"query": "Léa"}' }]);
  });

  it("le end du même appel le termine : ✓, résultat, durée", () => {
    const [card] = play(frame("start"), frame("end", { at: 1_182 }));
    expect(card.steps).toHaveLength(1);
    expect(toolSteps(card)[0]).toMatchObject({ status: "ok", result: "3 souvenirs", durationMs: 182 });
  });

  it("un end sans start crée sa ligne (un appel refusé avant de partir)", () => {
    const [card] = play(frame("end", { call_id: "refus", ok: false, result: "refusé", args: "{}" }));
    expect(toolSteps(card)).toMatchObject([{ status: "failed", result: "refusé" }]);
  });

  it("sans duration_ms, la durée se mesure entre les deux trames", () => {
    const [card] = play(frame("start", { at: 1_000 }), frame("end", { at: 1_450, duration_ms: undefined }));
    expect(toolSteps(card)[0].durationMs).toBe(450);
  });

  it("outils et notes dans l'ordre d'arrivée", () => {
    const [card] = play(
      frame("start"),
      frame("note", { text: "je regarde…" }),
      frame("start", { call_id: "c2", name: "email_read" }),
      frame("end"),
      frame("end", { call_id: "c2", name: "email_read", ok: false })
    );
    expect(card.steps.map((s) => (s.kind === "note" ? s.text : s.kind === "tool" ? `${s.name}:${s.status}` : s.kind)))
      .toEqual(["memory_search:ok", "je regarde…", "email_read:failed"]);
  });

  it("au done, plus rien ne tourne ; une issue autre que done se dit", () => {
    const [card] = play(frame("start"), frame("done", { outcome: "timeout", at: 4_200 }));
    expect(isRunning(card)).toBe(false);
    expect(toolSteps(card)[0].status).toBe("stopped");
    expect(card.steps[card.steps.length - 1]).toMatchObject({ kind: "end", outcome: "timeout" });
    expect(card.endedAt).toBe(4_200);
  });

  it("un done ordinaire n'ajoute pas de ligne", () => {
    const [card] = play(frame("start"), frame("end"), frame("done"));
    expect(card.steps.map((s) => s.kind)).toEqual(["tool"]);
  });

  it("une réponse supplantée puis reprise par un nouvel épisode : la même carte, qui retravaille", () => {
    const cards = play(
      frame("start"),
      frame("done", { outcome: "superseded" }),
      frame("start", { episode: "01JBSECOND", call_id: "c1" })
    );
    expect(cards).toHaveLength(1);
    const [card] = cards;
    expect(isRunning(card)).toBe(true);
    // le même call_id dans un autre épisode est un autre appel
    expect(toolSteps(card).map((t) => t.status)).toEqual(["stopped", "running"]);
  });

  it("sans reply_to, la carte se range par épisode", () => {
    const f = frame("start", { reply_to: null });
    expect(cardKey(f)).toBe(`e:${EP}`);
    expect(play(f)[0].replyTo).toBeNull();
  });

  it("ne mute rien : les cartes d'avant restent telles quelles", () => {
    const before = play(frame("start"));
    const snapshot = JSON.stringify(before);
    withToolFrame(before, frame("end"));
    withToolFrame(before, frame("done"));
    expect(JSON.stringify(before)).toBe(snapshot);
  });

  it(`au-delà de ${MAX_CARDS} cartes, la plus ancienne est oubliée`, () => {
    let cards: WorkCard[] = [];
    for (let i = 1; i <= MAX_CARDS + 3; i++) cards = withToolFrame(cards, frame("start", { reply_to: i }));
    expect(cards).toHaveLength(MAX_CARDS);
    expect(cards[0].replyTo).toBe(4);
  });
});

describe("withAnswer", () => {
  it("replie la carte du message auquel la réponse répond", () => {
    const cards = play(frame("start"), frame("start", { reply_to: 900 }));
    const next = withAnswer(cards, 811, 812);
    expect(next[0]).toMatchObject({ answered: true, answerId: 812 });
    expect(next[1].answered).toBe(false);
    expect(cards[0].answered).toBe(false);
  });

  it("sans user_message_id : la dernière carte sans reply_to encore sans réponse", () => {
    const cards = play(frame("start", { reply_to: null, episode: "A" }), frame("start", { reply_to: null, episode: "B" }));
    const next = withAnswer(cards, null, null);
    expect(next.map((c) => c.answered)).toEqual([false, true]);
  });

  it("rien à replier : les mêmes cartes", () => {
    const cards = play(frame("start"));
    expect(withAnswer(cards, 5, 6)).toBe(cards);
  });
});

describe("libellés", () => {
  it("durationLabel", () => {
    expect(durationLabel(182)).toBe("182 ms");
    expect(durationLabel(3_240)).toBe("3,2 s");
    expect(durationLabel(42_400)).toBe("42 s");
    expect(durationLabel(125_000)).toBe("2 min 05 s");
    expect(durationLabel(-1)).toBe("");
  });

  it("cardSummary : « 4 outils · 3,2 s », les échecs dits", () => {
    const four = play(
      frame("start", { at: 1_000 }),
      frame("end", { at: 1_100 }),
      ...["c2", "c3", "c4"].map((id) => frame("end", { call_id: id, at: 2_000 })),
      frame("done", { at: 4_200 })
    );
    expect(cardSummary(four[0])).toBe("4 outils · 3,2 s");
    const failed = play(frame("end", { ok: false, at: 1_000 }), frame("done", { at: 1_500 }));
    expect(cardSummary(failed[0])).toBe("1 outil · 1 échec · 500 ms");
    const none = play(frame("note", { at: 1_000 }), frame("done", { at: 2_000 }));
    expect(cardSummary(none[0])).toBe("aucun outil · 1 s");
  });

  it("runningLabel", () => {
    expect(runningLabel(play(frame("note"))[0])).toBe("Au travail…");
    expect(runningLabel(play(frame("start"))[0])).toBe("Au travail… · 1 outil");
  });

  it("outcomeLabel", () => {
    expect(outcomeLabel("done")).toBe("");
    expect(outcomeLabel("superseded")).toBe("remplacé par une nouvelle réponse");
    expect(outcomeLabel("bizarre")).toBe("fini : bizarre");
  });

  it("argsPreview : les valeurs d'un objet JSON, sur une ligne, coupées", () => {
    expect(argsPreview('{"query": "anniversaire de Léa"}')).toBe("anniversaire de Léa");
    expect(argsPreview('{"q": "x", "limit": 5}')).toBe("q=x, limit=5");
    expect(argsPreview("pas du\n  json")).toBe("pas du json");
    expect(argsPreview('{"q": "' + "a".repeat(100) + '"}', 20)).toBe(`${"a".repeat(19)}…`);
    expect(argsPreview("")).toBe("");
  });
});

describe("toolUses et toolsLine (l'historique)", () => {
  it("valide les outils d'une ligne d'historique", () => {
    expect(toolUses([{ name: "email_search", ok: true }, { name: "email_read", ok: "oui" }, { ok: true }, null, "x"]))
      .toEqual([{ name: "email_search", ok: true }, { name: "email_read", ok: false }]);
    expect(toolUses("nope")).toEqual([]);
  });

  it("« outils : email_search ✓ · email_read ✗ » ; rien sans outil", () => {
    expect(toolsLine([{ name: "email_search", ok: true }, { name: "email_read", ok: false }]))
      .toBe("outils : email_search ✓ · email_read ✗");
    expect(toolsLine([])).toBe("");
    expect(toolsLine(undefined)).toBe("");
  });
});

describe("placeCards — où peindre chaque carte", () => {
  const user = (id?: number, mode?: "pro"): Placeable => ({ id, sender: "user", mode });
  const reply = (id?: number, mode?: "pro", inner?: boolean): Placeable => ({ id, sender: "vtuber", mode, inner });

  it("le message de la personne n'a pas encore son id : en bas, ouverte", () => {
    const cards = play(frame("start"));
    expect(placeCards([user(10), reply(11), user(undefined, "pro")], cards)).toEqual([
      { key: "r:811", where: "end", index: -1, collapsed: false },
    ]);
  });

  it("sa réponse est là : juste au-dessus d'elle, repliée", () => {
    const cards = withAnswer(play(frame("start"), frame("done")), 811, 812);
    expect(placeCards([user(811, "pro"), reply(812, "pro")], cards)).toEqual([
      { key: "r:811", where: "before", index: 1, collapsed: true },
    ]);
  });

  it("le message lié, pas de réponse : juste après lui", () => {
    const cards = play(frame("start"), frame("done", { outcome: "abstained" }));
    expect(placeCards([user(811, "pro"), user(813)], cards)).toEqual([
      { key: "r:811", where: "after", index: 0, collapsed: false },
    ]);
  });

  it("une réponse pro arrivée par un rattrapage replie la carte au-dessus d'elle ; un murmure ne compte pas", () => {
    const cards = play(frame("start"));
    expect(placeCards([user(811, "pro"), reply(undefined, undefined, true), reply(812, "pro")], cards)).toEqual([
      { key: "r:811", where: "before", index: 2, collapsed: true },
    ]);
  });

  it("une parole ordinaire qui suit n'est pas sa réponse", () => {
    const cards = play(frame("start"));
    expect(placeCards([user(811, "pro"), reply(812)], cards)).toEqual([
      { key: "r:811", where: "after", index: 0, collapsed: false },
    ]);
  });
});
