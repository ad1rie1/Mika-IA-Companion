import { describe, expect, it, vi } from "vitest";
import { Freshness, KEYS, Live, names, OneAtATime, parseChanged, TOPICS, type Changed, type Socket } from "./live";

/** Un client de la connexion, joué : ce que `WebSocketClient` diffuse par `on`. */
class FakeSocket implements Socket {
  private readonly handlers = new Map<string, Array<(data: any) => void>>();

  on(type: string, handler: (data: any) => void): void {
    this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler]);
  }

  emit(type: string, data: unknown): void {
    for (const h of this.handlers.get(type) ?? []) h(data);
  }

  open(): void {
    this.emit("connection", { status: "connected" });
  }
}

const frame = (...changes: unknown[]) => ({ type: "changed", changes });
const keys = (c: Changed) => (c === null ? null : [...c].sort());

describe("la trame `changed` (protocole-moi.md § 2 bis)", () => {
  it("les sujets et leurs clés sont ceux du contrat", () => {
    expect(TOPICS).toContain("mail.work");
    expect(KEYS.mail).toBe("boxes");
    expect(KEYS["teams.work"]).toBe("conversations");
    expect(KEYS.me).toBeUndefined();
  });

  it("chaque sujet avec ce qu'il nomme ; sans clé, tout le domaine", () => {
    const got = parseChanged(frame({ topic: "mail", boxes: ["pro"] }, { topic: "mail.drafts" }, { topic: "me" }));
    expect(keys(got.get("mail")!)).toEqual(["pro"]);
    expect(got.get("mail.drafts")).toBeNull();
    expect(got.get("me")).toBeNull();
    expect(got.size).toBe(3);
  });

  it("un projet se nomme par son numéro : il se lit comme sa clé", () => {
    expect(keys(parseChanged(frame({ topic: "projects", projects: [3, 12] })).get("projects")!)).toEqual(["12", "3"]);
  });

  it("l'agenda nomme ses agendas (ADR 0309) : sans clé, tout l'agenda", () => {
    expect(keys(parseChanged(frame({ topic: "agenda", calendars: ["moi:user_1~mon-agenda"] })).get("agenda")!)).toEqual(["moi:user_1~mon-agenda"]);
    expect(parseChanged(frame({ topic: "agenda" })).get("agenda")).toBeNull();
  });

  it("un sujet inconnu se tait ; une clé inconnue, une liste vide ou illisible : tout le domaine", () => {
    const got = parseChanged(frame(
      { topic: "meteo", days: ["lundi"] },
      { topic: "mail", boxes: ["pro"], folders: ["INBOX"] },
      { topic: "teams", conversations: [] },
      { topic: "phone", conversations: [{ id: 1 }] },
      { topic: "contacts", boxes: ["pro"] },
      { boxes: ["pro"] },
      "mail",
    ));
    expect(got.has("meteo" as never)).toBe(false);
    expect(got.get("mail")).toBeNull();
    expect(got.get("teams")).toBeNull();
    expect(got.get("phone")).toBeNull();
    expect(got.get("contacts")).toBeNull();
    expect(got.size).toBe(4);
    expect(parseChanged({ type: "changed" }).size).toBe(0);
    expect(parseChanged(null).size).toBe(0);
  });

  it("deux entrées du même sujet se réunissent ; tout le domaine l'emporte", () => {
    expect(keys(parseChanged(frame({ topic: "mail", boxes: ["pro"] }, { topic: "mail", boxes: ["perso"] })).get("mail")!)).toEqual(["perso", "pro"]);
    expect(parseChanged(frame({ topic: "mail", boxes: ["pro"] }, { topic: "mail" })).get("mail")).toBeNull();
  });

  it("names : la clé nommée, ou tout le domaine ; rien d'ouvert ne l'est jamais par une clé", () => {
    expect(names(new Set(["pro"]), "pro")).toBe(true);
    expect(names(new Set(["pro"]), "perso")).toBe(false);
    expect(names(new Set(["3"]), 3)).toBe(true);
    expect(names(null, "perso")).toBe(true);
    expect(names(new Set(["pro"]), "")).toBe(false);
    expect(names(new Set(["pro"]), null)).toBe(false);
    expect(names(null, null)).toBe(true);
  });
});

describe("le service", () => {
  it("aiguille chaque sujet vers ses abonnés, avec ses clés", () => {
    const live = new Live();
    const ws = new FakeSocket();
    live.bind(ws);
    const mail = vi.fn();
    const teams = vi.fn();
    live.onChange("mail", mail);
    live.onChange("teams", teams);
    ws.emit("changed", frame({ topic: "mail", boxes: ["pro", "perso"] }));
    expect(mail).toHaveBeenCalledTimes(1);
    expect(keys(mail.mock.calls[0][0])).toEqual(["perso", "pro"]);
    expect(teams).not.toHaveBeenCalled();
    ws.emit("changed", frame({ topic: "teams" }, { topic: "inconnu" }));
    expect(teams).toHaveBeenCalledWith(null);
  });

  it("se désabonner : plus rien n'arrive", () => {
    const live = new Live();
    const ws = new FakeSocket();
    live.bind(ws);
    const seen = vi.fn();
    const off = live.onChange("me", seen);
    live.receive(frame({ topic: "me" }));
    off();
    live.receive(frame({ topic: "me" }));
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it("un abonné qui lève ne fait pas taire les suivants", () => {
    const live = new Live();
    const after = vi.fn();
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    live.onChange("me", () => {
      throw new Error("en panne");
    });
    live.onChange("me", after);
    live.receive(frame({ topic: "me" }));
    expect(after).toHaveBeenCalled();
    error.mockRestore();
  });

  it("relis tout : à chaque ouverture, la première comprise (l'écran lu au démarrage l'a été avant qu'elle écoute)", () => {
    const live = new Live();
    const ws = new FakeSocket();
    const resync = vi.fn();
    live.onResync(resync);
    live.bind(ws);
    ws.open();
    expect(resync).toHaveBeenCalledTimes(1);
    ws.emit("connection", { status: "disconnected" });
    ws.emit("connection", { status: "reconnecting" });
    expect(resync).toHaveBeenCalledTimes(1);
    ws.open();
    expect(resync).toHaveBeenCalledTimes(2);
    ws.open();
    expect(resync).toHaveBeenCalledTimes(3);
  });

  it("plusieurs sujets suivis ensemble : une trame qui en nomme trois, un seul appel, avec ceux qu'il suit", () => {
    const live = new Live();
    const ws = new FakeSocket();
    live.bind(ws);
    const all = vi.fn();
    const off = live.onAny(["settings", "me", "mail"], all);
    ws.emit("changed", frame({ topic: "mail", boxes: ["pro"] }, { topic: "settings" }, { topic: "me" }, { topic: "teams" }));
    expect(all).toHaveBeenCalledTimes(1);
    const got = all.mock.calls[0][0] as ReadonlyMap<string, Changed>;
    expect([...got.keys()].sort()).toEqual(["mail", "me", "settings"]);
    expect(keys(got.get("mail")!)).toEqual(["pro"]);
    // une trame qui n'en nomme aucun : rien
    ws.emit("changed", frame({ topic: "teams" }));
    expect(all).toHaveBeenCalledTimes(1);
    off();
    ws.emit("changed", frame({ topic: "me" }));
    expect(all).toHaveBeenCalledTimes(1);
  });

  it("un nouveau client (après 4401) : le service s'y rebranche, l'ancien se tait, sa première ouverture fait tout relire", () => {
    const live = new Live();
    const first = new FakeSocket();
    const resync = vi.fn();
    const me = vi.fn();
    live.onResync(resync);
    live.onChange("me", me);
    live.bind(first);
    first.open();
    expect(resync).toHaveBeenCalledTimes(1);
    first.emit("connection", { status: "unauthorized" });
    const second = new FakeSocket();
    live.bind(second);
    first.emit("changed", frame({ topic: "me" }));
    first.open();
    expect(me).not.toHaveBeenCalled();
    expect(resync).toHaveBeenCalledTimes(1);
    second.open();
    expect(resync).toHaveBeenCalledTimes(2);
    second.emit("changed", frame({ topic: "me" }));
    expect(me).toHaveBeenCalledTimes(1);
  });

  it("l'onglet revient au premier plan : ceux qui l'attendaient le savent", () => {
    const live = new Live();
    const back = vi.fn();
    const off = live.onVisible(back);
    live.shown();
    off();
    live.shown();
    expect(back).toHaveBeenCalledTimes(1);
  });
});

describe("un écran face au direct (Freshness)", () => {
  function screen(shown: boolean) {
    const live = new Live();
    const state = { shown };
    const whole = vi.fn();
    const f = new Freshness(() => state.shown, whole, live);
    return { live, state, whole, f };
  }

  it("montré, il relit aussitôt ce qui le concerne", () => {
    const { f, whole } = screen(true);
    const now = vi.fn();
    f.touch(now);
    expect(now).toHaveBeenCalled();
    expect(f.pending).toBe(false);
    expect(f.back()).toBe(false);
    expect(whole).not.toHaveBeenCalled();
  });

  it("au second plan, il ne relit rien : il se marque périmé et se relit tout entier à son retour, une fois", () => {
    const { f, whole, state } = screen(false);
    const now = vi.fn();
    f.touch(now);
    f.touch(now);
    expect(now).not.toHaveBeenCalled();
    expect(f.pending).toBe(true);
    expect(f.back()).toBe(false); // toujours caché : rien
    state.shown = true;
    expect(f.back()).toBe(true);
    expect(f.back()).toBe(false);
    expect(whole).toHaveBeenCalledTimes(1);
  });

  it("chaque ouverture, la première comprise : montré, il relit tout ; caché, à son retour", () => {
    const shown = screen(true);
    const ws = new FakeSocket();
    shown.live.bind(ws);
    ws.open();
    expect(shown.whole).toHaveBeenCalledTimes(1);
    ws.open();
    expect(shown.whole).toHaveBeenCalledTimes(2);

    const hidden = screen(false);
    const ws2 = new FakeSocket();
    hidden.live.bind(ws2);
    ws2.open();
    ws2.open();
    expect(hidden.whole).not.toHaveBeenCalled();
    hidden.state.shown = true;
    hidden.live.shown(); // l'onglet revient
    expect(hidden.whole).toHaveBeenCalledTimes(1);
  });

  it("un écran pas encore ouvert que la première ouverture marque périmé n'en lit pas deux fois : sa première lecture l'efface", () => {
    const { live, f, whole, state } = screen(false);
    const ws = new FakeSocket();
    live.bind(ws);
    ws.open();
    expect(f.pending).toBe(true);
    // son premier dessin : il lit tout de lui-même et le dit
    state.shown = true;
    f.fresh();
    expect(f.back()).toBe(false);
    expect(whole).not.toHaveBeenCalled();
  });

  it("sa première lecture le dit à jour", () => {
    const { f, whole, state } = screen(false);
    f.touch(() => undefined);
    f.fresh();
    state.shown = true;
    expect(f.back()).toBe(false);
    expect(whole).not.toHaveBeenCalled();
  });
});

describe("une lecture à la fois (OneAtATime)", () => {
  it("une rafale ne lance pas dix lectures : une en vol, puis une seule après", async () => {
    let calls = 0;
    const gates: Array<() => void> = [];
    const once = new OneAtATime(() => {
      calls += 1;
      return new Promise<void>((resolve) => gates.push(resolve));
    });
    const runs = Array.from({ length: 10 }, () => once.run());
    expect(calls).toBe(1);
    expect(once.busy).toBe(true);
    gates.shift()!();
    await Promise.resolve();
    await Promise.resolve();
    expect(calls).toBe(2); // ce qui a changé pendant la première a pu partir après elle
    gates.shift()!();
    await Promise.all(runs);
    expect(calls).toBe(2);
    expect(once.busy).toBe(false);
    // la rafale passée, une demande repart aussitôt
    const later = once.run();
    expect(calls).toBe(3);
    gates.shift()!();
    await later;
  });

  it("une lecture en échec ne bloque pas la suivante", async () => {
    let calls = 0;
    const once = new OneAtATime(async () => {
      calls += 1;
      if (calls === 1) throw new Error("en panne");
    });
    await once.run();
    await once.run();
    expect(calls).toBe(2);
  });
});
