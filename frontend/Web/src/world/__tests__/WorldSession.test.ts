import { describe, expect, it } from "vitest";
import defaultWorld from "../../../../../backendv2/src/mika/faculties/world/chambre.json?raw";
import type { WorldDef } from "../protocol.g";
import { WorldSession, worldUrl, type SocketLike } from "../WorldSession";

class FakeSocket implements SocketLike {
  sent: Record<string, unknown>[] = [];
  closed: { code?: number; reason?: string } | null = null;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code?: number, reason?: string): void {
    this.closed = { code, reason };
  }

  // côté noyau
  open(): void {
    this.onopen?.({});
  }

  push(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  drop(code: number, reason = ""): void {
    this.onclose?.({ code, reason });
  }

  last(type: string): Record<string, unknown> | undefined {
    return [...this.sent].reverse().find((f) => f.type === type);
  }
}

function setup() {
  let now = 1_790_000_000_000;
  const sockets: FakeSocket[] = [];
  const session = new WorldSession({
    url: "ws://noyau/ws/world",
    openSocket: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    now: () => now,
    log: () => {},
  });
  return {
    session,
    sockets,
    socket: () => sockets[sockets.length - 1],
    advance(ms: number) {
      now += ms;
      session.tick(now);
    },
    now: () => now,
  };
}

const WORLD = JSON.parse(defaultWorld) as WorldDef;

function welcome(socket: FakeSocket, now: number) {
  socket.push({
    type: "welcome",
    protocol: "mika.world/1",
    session: "s-1",
    granted: ["viewer"],
    actor: "player:user_1",
    world: "chambre",
    rev: 0,
    seq: 40,
    now: now * 1000 + 2_000_000,
  });
}

function online() {
  const t = setup();
  t.session.connect();
  t.socket().open();
  welcome(t.socket(), t.now());
  t.socket().push({ type: "definition", world: WORLD });
  t.socket().push({
    type: "snapshot",
    state: { rev: 0, seq: 40, actors: [{ id: "mika", room: "bedroom", place: "center" }], objects: [] },
  });
  return t;
}

describe("la session du monde", () => {
  it("se présente en spectatrice, sans jeton ni corps", () => {
    const t = setup();
    t.session.connect();
    expect(t.session.state).toBe("connecting");
    t.socket().open();
    expect(t.session.state).toBe("greeting");
    expect(t.socket().sent[0]).toEqual({
      type: "hello",
      protocol: "mika.world/1",
      roles: ["viewer"],
      client: { name: "Mika Web", version: "0.1.0", engine: "three" },
      rev: null,
      after: null,
    });
  });

  it("accueillie, elle tient le miroir et l'heure du noyau", () => {
    const t = online();
    expect(t.session.state).toBe("online");
    expect(t.session.actor).toBe("player:user_1");
    expect(t.session.mirror.ready).toBe(true);
    expect(t.session.mirror.actor("mika")!.place).toBe("center");
    expect(t.session.clock.nowUs - t.now() * 1000).toBeCloseTo(2_000_000, -3);
  });

  it("une commande reçoit son accusé", async () => {
    const t = online();
    const done = t.session.command({ type: "address", to: "mika", gesture: "wave" });
    const sent = t.socket().last("address")!;
    expect(sent).toMatchObject({ type: "address", to: "mika", gesture: "wave" });
    expect(sent.cmd).toMatch(/^a-[a-z0-9]+-1$/);
    t.socket().push({ type: "result", cmd: sent.cmd, status: "refused", code: "unknown", message: "Tu n'es pas dans le monde." });
    await expect(done).resolves.toMatchObject({ status: "refused", code: "unknown", message: "Tu n'es pas dans le monde." });
  });

  it("une commande sans réponse finit refusée", async () => {
    const t = online();
    const done = t.session.command({ type: "act", action: "ouvrir", object: "window_pane" });
    t.advance(10_500);
    await expect(done).resolves.toMatchObject({ status: "refused", message: "Pas de réponse du noyau." });
  });

  it("hors débit, une commande est refusée sur place", async () => {
    const t = online();
    // Deux gestes par seconde : le troisième ne part pas.
    void t.session.command({ type: "address", to: "mika", gesture: "wave" });
    void t.session.command({ type: "address", to: "mika", gesture: "nod" });
    await expect(t.session.command({ type: "address", to: "mika", gesture: "clap" })).resolves.toMatchObject({
      status: "refused",
      code: "rate_limited",
    });
    expect(t.socket().sent.filter((f) => f.type === "address")).toHaveLength(2);
  });

  it("hors ligne, une commande est refusée sans partir", async () => {
    const t = setup();
    await expect(t.session.command({ type: "act", action: "sit", place: "bed" })).resolves.toMatchObject({
      status: "refused",
      message: "Pas connectée au monde.",
    });
  });

  it("elle renouvelle par ping, et mesure l'aller-retour", () => {
    const t = online();
    t.advance(5_000);
    const ping = t.socket().last("ping")!;
    expect(typeof ping.t).toBe("number");
    t.advance(40);
    t.socket().push({ type: "pong", t: ping.t });
    expect(t.session.roundTripMs).toBeCloseTo(40, 0);
  });

  it("une connexion tombée revient, et dit où elle en était", () => {
    const t = online();
    t.socket().drop(1006);
    expect(t.session.state).toBe("offline");
    t.advance(500);
    expect(t.sockets).toHaveLength(1);
    t.advance(600);
    expect(t.sockets).toHaveLength(2);
    t.socket().open();
    expect(t.socket().sent[0]).toMatchObject({ type: "hello", rev: 0, after: 40 });
  });

  it("un silence trop long rouvre la connexion", () => {
    const t = online();
    for (let i = 0; i < 21; i++) t.advance(1_000);
    expect(t.session.state).toBe("offline");
    expect(t.sockets[0].closed?.reason).toBe("silence");
  });

  it("refusée (4401), elle ne réessaie pas toute seule", () => {
    const t = online();
    t.socket().drop(4401, "unauthorized");
    expect(t.session.state).toBe("refused");
    t.advance(60_000);
    expect(t.sockets).toHaveLength(1);
  });

  it("une trame inconnue est passée sans rien casser", () => {
    const t = online();
    t.socket().push({ type: "teleport", seq: 41 });
    expect(t.session.state).toBe("online");
    expect(t.session.mirror.seq).toBe(40);
  });

  it("l'adresse du monde suit celle du noyau", () => {
    expect(worldUrl("http://localhost:8001")).toBe("ws://localhost:8001/ws/world");
    expect(worldUrl("https://mika.example/")).toBe("wss://mika.example/ws/world");
  });
});
