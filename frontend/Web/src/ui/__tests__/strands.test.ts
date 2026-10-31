import { describe, expect, it } from "vitest";
import {
  localStrand,
  newStrandId,
  parseCommand,
  parseStrands,
  strandLabel,
  strandOf,
  suggestCommands,
  unescapeSlash,
  withLocal,
} from "../strands";
import { mergeHistory, threadOf, trimThreads } from "../chatSync";
import type { StoredMessage } from "../chatSync";
import { toolFrame, withToolFrame } from "../toolActivity";

describe("les fils de travail (ADR 0164)", () => {
  it("un identifiant neuf est valide pour le serveur, et deux ne se ressemblent pas", () => {
    const a = newStrandId(1790601612771, () => 0.1);
    const b = newStrandId(1790601612771, () => 0.2);
    expect(strandOf(a)).toBe(a);
    expect(a).not.toBe(b);
    expect(strandOf("pas un id !")).toBeUndefined();
    expect(strandOf("x".repeat(41))).toBeUndefined();
    expect(strandOf(12)).toBeUndefined();
  });

  it("la liste du serveur, validée ; un fil sans titre se nomme par son premier message", () => {
    const list = parseStrands({
      items: [
        { id: "devis", title: "Devis IN", description: "HT", archived: false, count: 4, last_at: 9, opener: "liste" },
        { id: "code", title: "", description: "", archived: true, count: 2, last_at: 5, opener: "corrige ma fonction" },
        { id: "pas valide !", title: "x" },
        "rien",
      ],
    });
    expect(list.map((s) => s.id)).toEqual(["devis", "code"]);
    expect(strandLabel(list[0])).toBe("Devis IN");
    expect(strandLabel(list[1])).toBe("corrige ma fonction");
    expect(strandLabel(localStrand("neuf"))).toBe("Nouveau fil");
    expect(strandLabel({ title: "", opener: "a".repeat(80) })).toHaveLength(48);
    expect(parseStrands(null)).toEqual([]);
  });

  it("un fil ouvert ici et pas encore connu du serveur reste en tête ; connu, il prend sa ligne", () => {
    const server = parseStrands({ items: [{ id: "devis", title: "Devis", count: 2, last_at: 9 }] });
    const local = [localStrand("neuf", 1), localStrand("devis", 1)];
    expect(withLocal(server, local).map((s) => [s.id, s.title])).toEqual([
      ["neuf", ""],
      ["devis", "Devis"],
    ]);
  });

  it("les commandes : /clear ouvre un fil neuf, les autres règlent le fil ; // échappe", () => {
    expect(parseCommand("/clear")).toEqual({ name: "clear" });
    expect(parseCommand("  /nouveau ")).toEqual({ name: "clear" });
    expect(parseCommand("/renommer Devis   IN")).toEqual({ name: "rename", arg: "Devis   IN" });
    expect(parseCommand("/description Le commercial\nd'IN")).toEqual({
      name: "describe",
      arg: "Le commercial\nd'IN",
    });
    expect(parseCommand("/Archiver")).toEqual({ name: "archive" });
    expect(parseCommand("/désarchiver")).toEqual({ name: "unarchive" });
    expect(parseCommand("/aide")).toEqual({ name: "help" });
    expect(parseCommand("/xyz truc")).toEqual({ name: "unknown", typed: "/xyz" });
    // un message ordinaire, et l'échappement
    expect(parseCommand("liste les devis /clear")).toBeNull();
    expect(parseCommand("//clear n'est pas une commande")).toBeNull();
    expect(unescapeSlash("//clear n'est pas une commande")).toBe("/clear n'est pas une commande");
    expect(unescapeSlash("rien à faire")).toBe("rien à faire");
  });

  it("les suggestions suivent le début tapé, jusqu'au premier espace", () => {
    expect(suggestCommands("/re").map((c) => c.usage)).toEqual(["/renommer <titre>"]);
    expect(suggestCommands("/").length).toBeGreaterThan(4);
    expect(suggestCommands("/renommer Devis")).toEqual([]);
    expect(suggestCommands("bonjour")).toEqual([]);
    expect(suggestCommands("//")).toEqual([]);
  });
});

describe("le fil de chaque message (ADR 0164)", () => {
  const msg = (id: number, strand?: string): StoredMessage => ({
    text: `m${id}`,
    sender: id % 2 ? "user" : "vtuber",
    ts: id,
    id,
    ...(strand ? { strand } : {}),
  });

  it("une ligne de l'historique garde son fil ; une bulle d'un autre fil n'est jamais adoptée", () => {
    const history: StoredMessage[] = [
      { text: "ok", sender: "user", ts: 1, cid: "a", status: "pending", strand: "devis" },
    ];
    const result = mergeHistory(
      history,
      [
        { id: 10, role: "user", text: "ok", ts: 2 },
        { id: 11, role: "user", text: "ok", ts: 3, strand: "devis" },
      ],
      50,
    );
    const byId = new Map(result.history.map((m) => [m.id, m]));
    expect(byId.get(10)?.strand).toBeUndefined();
    expect(byId.get(11)?.strand).toBe("devis");
    expect(byId.get(11)?.cid).toBe("a"); // la sienne, dans le même fil
    expect(result.adopted).toBe(1);
    expect(result.added).toBe(1);
  });

  it("le cache garde les derniers messages de chaque fil, et les fils les plus récents", () => {
    const history = [
      ...Array.from({ length: 6 }, (_, i) => msg(i + 1)),
      msg(10, "a"),
      msg(11, "b"),
      msg(12, "c"),
      msg(13, "a"),
    ];
    const kept = trimThreads(history, 3, 2);
    expect(kept.map((m) => m.id)).toEqual([4, 5, 6, 12, 10, 13].sort((x, y) => x - y));
    expect(kept.filter((m) => threadOf(m) === "").length).toBe(3);
    expect(kept.some((m) => m.strand === "b")).toBe(false); // le moins récent des fils s'en va
  });

  it("une carte de travail sait son fil", () => {
    const frame = toolFrame({ type: "tool", episode: "e1", reply_to: 5, phase: "note", text: "Je cherche", at: 1,
                              strand: "devis" });
    expect(frame?.strand).toBe("devis");
    const [card] = withToolFrame([], frame!);
    expect(card.strand).toBe("devis");
    const plain = toolFrame({ type: "tool", episode: "e2", reply_to: 6, phase: "note", text: "x", at: 1 });
    expect(withToolFrame([], plain!)[0].strand).toBeUndefined();
  });
});
