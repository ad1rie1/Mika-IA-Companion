import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AckMessage, ConnectionEvent } from "../../types";
import { WS_CLOSE_UNAUTHORIZED, WebSocketClient } from "../WebSocketClient";

/**
 * Reconnexion, keepalive et file d'attente du transport, contre un faux
 * `WebSocket` global. Le faux ne fait rien tout seul : chaque test joue le
 * navigateur — l'ouverture, une trame reçue, la fermeture annoncée (`onclose`)
 * ou, ce qui compte le plus ici, la mort silencieuse (readyState figé, aucun
 * événement), celle d'un portable qui dormait ou d'un proxy qui a coupé.
 */
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  closeCalls = 0;
  /** Après ce nombre de `send`, le socket meurt sans prévenir (0 = jamais). */
  dieAfterSends = 0;
  onopen: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(payload: string) {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error("InvalidStateError");
    this.sent.push(payload);
    if (this.dieAfterSends && this.sent.length >= this.dieAfterSends) {
      this.readyState = FakeWebSocket.CLOSED;
    }
  }

  close() {
    this.closeCalls++;
    this.readyState = FakeWebSocket.CLOSED;
  }

  // ── Le navigateur, joué à la main ──
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }
  receive(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
  /** Fermeture annoncée : `onclose` est déclenché. */
  fail(code = 1006) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }
  /** Mort silencieuse : plus rien ne passe, aucun événement. */
  die() {
    this.readyState = FakeWebSocket.CLOSED;
  }
  frames(): Array<Record<string, unknown>> {
    return this.sent.map((s) => JSON.parse(s));
  }
  types(): string[] {
    return this.frames().map((f) => f.type as string);
  }
}

function installDom() {
  const listeners = new Map<string, Array<() => void>>();
  const add = (type: string, fn: () => void) => {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type)!.push(fn);
  };
  const document = { hidden: false, addEventListener: add };
  // Délégation à l'appel, pas à l'installation : `vi.useFakeTimers()` remplace
  // les timers de `globalThis` après coup.
  const window = {
    addEventListener: add,
    setTimeout: (...a: Parameters<typeof setTimeout>) => globalThis.setTimeout(...a),
    clearTimeout: (...a: Parameters<typeof clearTimeout>) => globalThis.clearTimeout(...a),
    setInterval: (...a: Parameters<typeof setInterval>) => globalThis.setInterval(...a),
    clearInterval: (...a: Parameters<typeof clearInterval>) => globalThis.clearInterval(...a),
  };
  vi.stubGlobal("document", document);
  vi.stubGlobal("window", window);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const fire = (type: string) => {
    for (const fn of listeners.get(type) ?? []) fn();
  };
  return { fire, document };
}

const sockets = () => FakeWebSocket.instances;
const last = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1];

function client(cursor = 0) {
  const ws = new WebSocketClient("ws://test/ws");
  ws.setCursorProvider(() => cursor);
  const statuses: ConnectionEvent[] = [];
  ws.on("connection", (d) => statuses.push(d));
  const acks: AckMessage[] = [];
  ws.on("ack", (d) => acks.push(d));
  return { ws, statuses, acks };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.instances = [];
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WebSocketClient — reconnexion", () => {
  it("backoff exponentiel ×1,5 depuis 1 s, borné à 30 s, remis à 1 s par une ouverture", () => {
    installDom();
    const { ws, statuses } = client();
    ws.connect();
    const announced: number[] = [];
    for (let i = 0; i < 12; i++) {
      last().fail();
      const s = statuses[statuses.length - 1];
      expect(s.status).toBe("disconnected");
      announced.push(s.retryInMs as number);
      // Le socket suivant n'existe qu'à l'échéance du délai annoncé (±1 ms :
      // les délais ×1,5 deviennent fractionnaires, et les timers factices
      // les arrondissent).
      const before = sockets().length;
      vi.advanceTimersByTime((s.retryInMs as number) - 2);
      expect(sockets()).toHaveLength(before);
      vi.advanceTimersByTime(2);
      expect(sockets()).toHaveLength(before + 1);
      expect(statuses[statuses.length - 1].status).toBe("reconnecting");
    }
    expect(announced.slice(0, 4)).toEqual([1000, 1500, 2250, 3375]);
    expect(Math.max(...announced)).toBe(30000);
    expect(announced.slice(-2)).toEqual([30000, 30000]);

    // Une ouverture réussie repart du délai initial.
    last().open();
    expect(statuses[statuses.length - 1].status).toBe("connected");
    last().fail();
    expect(statuses[statuses.length - 1]).toMatchObject({ status: "disconnected", retryInMs: 1000 });
  });

  it("une fermeture n'arme qu'un seul timer, même annoncée deux fois", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    const first = last();
    first.fail();
    first.fail();
    vi.advanceTimersByTime(60000);
    expect(sockets()).toHaveLength(2);
  });

  it("reconnectNow (focus sur un socket mort) : un seul nouveau socket, l'ancien fermé et détaché", () => {
    const { fire } = installDom();
    const { ws, statuses } = client();
    ws.connect();
    const first = last();
    first.open();
    first.die();

    fire("focus");
    expect(sockets()).toHaveLength(2);
    expect(first.closeCalls).toBe(1);
    // Détaché avant fermeture : notre propre close() ne doit pas relancer.
    expect(first.onclose).toBeNull();
    expect(first.onmessage).toBeNull();
    // « reconnecting » suit l'ouverture du nouveau socket, « connected » vient après.
    expect(statuses[statuses.length - 1].status).toBe("reconnecting");
    last().open();
    expect(statuses[statuses.length - 1].status).toBe("connected");
    // Rien d'autre ne se déclenche derrière (sous les 50 s du chien de garde,
    // qui reconnecterait légitimement un socket resté silencieux).
    vi.advanceTimersByTime(45000);
    expect(sockets()).toHaveLength(2);
  });

  it("reconnectNow annule le backoff en cours : pas de troisième socket à son échéance", () => {
    const { fire } = installDom();
    const { ws } = client();
    ws.connect();
    last().fail(); // timer de 1 s armé
    fire("online"); // reconnexion immédiate
    expect(sockets()).toHaveLength(2);
    vi.advanceTimersByTime(60000);
    expect(sockets()).toHaveLength(2);
  });

  it("un socket encore en CONNECTING n'est pas remplacé", () => {
    const { fire } = installDom();
    const { ws } = client();
    ws.connect();
    fire("focus");
    fire("online");
    expect(sockets()).toHaveLength(1);
  });

  it("visibilitychange ne vérifie qu'au retour au premier plan", () => {
    const { fire, document } = installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    last().die();
    document.hidden = true;
    fire("visibilitychange");
    expect(sockets()).toHaveLength(1);
    document.hidden = false;
    fire("visibilitychange");
    expect(sockets()).toHaveLength(2);
  });

  it("sur un socket OPEN, un réveil envoie un ping et laisse le chien de garde juger", () => {
    const { fire } = installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    const before = last().sent.length;
    fire("focus");
    expect(sockets()).toHaveLength(1);
    expect(last().types().slice(before)).toEqual(["ping"]);
  });

  it("silence passé 50 s SANS trame en vol : un réveil pingue seulement", () => {
    const { fire } = installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    vi.setSystemTime(Date.now() + 60000);
    fire("focus");
    expect(sockets()).toHaveLength(1);
    expect(last().types()[last().types().length - 1]).toBe("ping");
  });

  it("silence passé 50 s AVEC un message sans ack : un réveil reconnecte tout de suite", () => {
    const { fire } = installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    expect(ws.sendChat("t'es là ?", "c1")).toBe(true);
    vi.setSystemTime(Date.now() + 60000);
    fire("focus");
    expect(sockets()).toHaveLength(2);
    // Et le message reparti sur le nouveau socket, après identify + sync.
    last().open();
    expect(last().types()).toEqual(["sync", "chat"]);
  });
});

describe("WebSocketClient — keepalive", () => {
  it("un ping toutes les 20 s, portant l'heure d'envoi", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    const base = last().sent.length;
    vi.advanceTimersByTime(19999);
    expect(last().sent.length).toBe(base);
    vi.advanceTimersByTime(1);
    expect(last().types().slice(base)).toEqual(["ping"]);
    expect(last().frames()[last().frames().length - 1]).toMatchObject({ type: "ping", t: Date.now() });
    vi.advanceTimersByTime(20000);
    expect(last().types().slice(base)).toEqual(["ping", "ping"]);
  });

  it("50 s sans aucune trame reçue : reconnexion forcée au tick suivant", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    const first = last();
    first.open();
    vi.advanceTimersByTime(40000);
    expect(sockets()).toHaveLength(1);
    expect(first.types().filter((t) => t === "ping")).toHaveLength(2);
    vi.advanceTimersByTime(20000); // 60 s de silence au tick
    expect(sockets()).toHaveLength(2);
    expect(first.closeCalls).toBe(1);
    // Le nouveau socket repart avec son propre keepalive.
    last().open();
    vi.advanceTimersByTime(20000);
    expect(last().types()).toContain("ping");
  });

  it("n'importe quelle trame reçue — même un pong — remet le compteur de silence à zéro", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    const first = last();
    first.open();
    vi.advanceTimersByTime(40000);
    first.receive({ type: "pong", t: 0 });
    vi.advanceTimersByTime(40000); // 80 s après l'ouverture, 40 s après le pong
    expect(sockets()).toHaveLength(1);
    vi.advanceTimersByTime(20000); // 60 s après le pong
    expect(sockets()).toHaveLength(2);
  });

  it("le keepalive s'arrête avec le socket", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    const first = last();
    first.open();
    first.fail();
    const sentAtClose = first.sent.length;
    vi.advanceTimersByTime(500); // avant la reconnexion (1 s)
    expect(first.sent.length).toBe(sentAtClose);
    expect(vi.getTimerCount()).toBe(1); // le seul timer restant est le backoff
  });
});

describe("WebSocketClient — file d'attente (outbox) et accusés", () => {
  it("à l'ouverture : identify, puis sync sur le curseur, puis la file dans l'ordre, puis « connected »", () => {
    installDom();
    const { ws, statuses } = client(42);
    ws.setIdentity("user_7", "Adrien");
    expect(ws.sendChat("un", "c1")).toBe(false);
    expect(ws.sendChat("deux", "c2")).toBe(false);
    ws.connect();
    expect(last().sent).toEqual([]);
    last().open();
    expect(last().frames()).toEqual([
      { type: "identify", person_id: "user_7", display_name: "Adrien" },
      { type: "sync", after_id: 42 },
      { type: "chat", message: "un", client_msg_id: "c1", person_id: "user_7" },
      { type: "chat", message: "deux", client_msg_id: "c2", person_id: "user_7" },
    ]);
    expect(statuses.map((s) => s.status)).toEqual(["connected"]);
  });

  it("socket ouvert : envoi immédiat ; l'ack purge le suivi, rien n'est rejoué ensuite", () => {
    installDom();
    const { ws, acks } = client();
    ws.connect();
    last().open();
    expect(ws.sendChat("salut", "c1")).toBe(true);
    expect(last().types()[last().types().length - 1]).toBe("chat");
    last().receive({ type: "ack", client_msg_id: "c1", status: "accepted" });
    expect(acks).toEqual([{ type: "ack", client_msg_id: "c1", status: "accepted" }]);
    last().fail();
    vi.advanceTimersByTime(1000);
    last().open();
    expect(last().types()).toEqual(["sync"]);
  });

  it("un message parti sans ack revient en tête, devant ce qui a été tapé pendant la coupure", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    ws.sendChat("A", "a");
    last().fail();
    expect(ws.sendChat("B", "b")).toBe(false);
    vi.advanceTimersByTime(1000);
    last().open();
    expect(last().frames().filter((f) => f.type === "chat").map((f) => f.message)).toEqual(["A", "B"]);
  });

  it("les trames de contrôle ne sont jamais mises en file", () => {
    installDom();
    const { ws } = client(5);
    ws.requestSync();
    ws.connect();
    last().open();
    expect(last().types()).toEqual(["sync"]);
  });

  it("MAX_OUTBOX = 20 : la 21e évince la plus ancienne, refusée à voix haute", () => {
    installDom();
    const { ws, acks } = client();
    for (let i = 1; i <= 21; i++) ws.sendChat(`m${i}`, `c${i}`);
    expect(acks).toEqual([{ type: "ack", client_msg_id: "c1", status: "send_abandoned" }]);
    ws.connect();
    last().open();
    // Quatre en vol au plus : chaque accusé fait partir le suivant.
    const chats = () => last().frames().filter((f) => f.type === "chat").map((f) => f.client_msg_id);
    for (let i = 0; i < chats().length; i++) {
      last().receive({ type: "ack", client_msg_id: chats()[i], status: "accepted" });
    }
    const sent = chats();
    expect(sent).toHaveLength(20);
    expect(sent[0]).toBe("c2");
    expect(sent[sent.length - 1]).toBe("c21");
  });

  it("une trame au-delà de la taille du transport est refusée, jamais mise en file", () => {
    installDom();
    const { ws, acks } = client();
    const huge = "x".repeat(34 * 1024 * 1024 + 1);
    expect(ws.sendChat(huge, "big")).toBe(false);
    expect(acks).toEqual([{ type: "ack", client_msg_id: "big", status: "frame_too_large" }]);
    ws.connect();
    last().open();
    expect(last().types()).toEqual(["sync"]);
  });

  it("une trame que 5 réouvertures n'ont pas réussi à faire partir est abandonnée", () => {
    installDom();
    const { ws, acks } = client();
    ws.sendChat("tenace", "t");
    ws.sendChat("suivante", "s");
    ws.connect();
    // Chaque socket meurt sur le `sync` (son premier envoi, sans identité) :
    // la file est retrouvée non-OPEN au moment de la rejouer, et chaque
    // réouverture compte une tentative.
    for (let attempt = 1; attempt <= 6; attempt++) {
      const s = last();
      s.dieAfterSends = 1;
      s.open();
      expect(s.types()).toEqual(["sync"]);
      if (attempt < 6) {
        expect(acks).toEqual([]);
        s.fail();
        vi.advanceTimersByTime(30000);
      }
    }
    expect(acks).toEqual([
      { type: "ack", client_msg_id: "t", status: "send_abandoned" },
      { type: "ack", client_msg_id: "s", status: "send_abandoned" },
    ]);
  });
});

describe("WebSocketClient — refus terminal (4401)", () => {
  it("ne réessaie plus, purge la file, annonce « unauthorized », ignore les réveils", () => {
    const { fire } = installDom();
    const { ws, statuses } = client();
    ws.sendChat("avant", "c0");
    ws.connect();
    last().fail(WS_CLOSE_UNAUTHORIZED);
    expect(statuses.map((s) => s.status)).toEqual(["unauthorized"]);
    vi.advanceTimersByTime(120000);
    fire("focus");
    fire("online");
    expect(sockets()).toHaveLength(1);
    ws.connect();
    expect(sockets()).toHaveLength(1);
  });

  it("un envoi APRÈS le 4401 est refusé à voix haute, pas mis en file pour toujours", () => {
    // Le défaut corrigé : la purge du 4401 ne couvrait que ce qui attendait
    // déjà ; un message tapé ensuite partait en file, sans ack, sans issue.
    installDom();
    const { ws, acks } = client();
    ws.connect();
    last().fail(WS_CLOSE_UNAUTHORIZED);
    expect(ws.sendChat("après", "c1")).toBe(false);
    expect(acks).toEqual([{ type: "ack", client_msg_id: "c1", status: "unauthorized" }]);
  });
});

describe("WebSocketClient — diffusion", () => {
  it("un abonné qui lève n'empêche ni les suivants ni la relance", () => {
    installDom();
    const { ws } = client();
    const seen: string[] = [];
    ws.on("speech", () => {
      throw new Error("boom");
    });
    ws.on("speech", (m) => seen.push((m as { text: string }).text));
    ws.on("connection", () => {
      throw new Error("boom");
    });
    ws.connect();
    last().open();
    last().receive({ type: "speech", text: "coucou" });
    expect(seen).toEqual(["coucou"]);
    last().fail();
    vi.advanceTimersByTime(1000);
    expect(sockets()).toHaveLength(2);
  });

  it("une trame illisible ou sans type est ignorée mais compte comme signe de vie", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    vi.advanceTimersByTime(40000);
    last().onmessage?.({ data: "{pas du json" });
    vi.advanceTimersByTime(40000);
    expect(sockets()).toHaveLength(1);
  });
});

describe("WebSocketClient — décisions d'accord (ADR 0064)", () => {
  const frame = { type: "approval" as const, id: 905, decision: "accept" as const, digest: "3f9c" };

  it("connexion ouverte : la décision part telle quelle", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    last().open();
    expect(ws.sendApproval(frame)).toBe(true);
    const sent = last().frames();
    expect(sent[sent.length - 1]).toEqual(frame);
  });

  it("connexion fermée : rien ne part, et rien n'est rejoué à la reconnexion", () => {
    installDom();
    const { ws } = client();
    ws.connect();
    expect(ws.sendApproval(frame)).toBe(false);
    last().open();
    expect(last().types()).not.toContain("approval");
    last().fail();
    expect(ws.sendApproval(frame)).toBe(false);
    vi.advanceTimersByTime(1000);
    last().open();
    expect(last().types()).not.toContain("approval");
  });
});
