import type { CommandDraft, CommandFrame } from "./actionMenu";
import { KernelClock } from "./kernelClock";
import {
  PROTOCOL,
  RATES,
  type ClientFrame,
  type ClientInfo,
  type Failure,
  type Hello,
  type PoseOut,
  type Result,
  type Role,
  type ServerFrame,
  type Welcome,
} from "./protocol.g";
import { readServer, writeClient } from "./wire";
import { WorldMirror, type FrameEffect } from "./WorldMirror";

export type LinkState =
  | "offline"
  | "connecting"
  /** Ouverte, `hello` envoyé, en attente de `welcome`. */
  | "greeting"
  | "online"
  /** Refusée pour de bon (authentification) : on ne réessaie pas tout seul. */
  | "refused";

/** Ce que la session attend d'un WebSocket (celui du navigateur, ou une doublure de test). */
export interface SocketLike {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export interface WorldSessionOptions {
  /** L'adresse du WebSocket du monde (`ws://127.0.0.1:8001/ws/world`). */
  url: string;
  roles?: Role[];
  /** Jeton d'un client natif ; le navigateur s'authentifie par sa session. */
  token?: string | null;
  /** Le modèle du corps de la personne (clé d'asset) ; l'écran web n'en a pas. */
  avatar?: string | null;
  client?: ClientInfo;
  pingIntervalMs?: number;
  /** Sans aucune trame pendant ce temps, la connexion est tenue pour morte et rouverte. */
  silenceTimeoutMs?: number;
  commandTimeoutMs?: number;
  openSocket?: (url: string) => SocketLike;
  /** Millisecondes locales depuis l'epoch. */
  now?: () => number;
  log?: (message: string) => void;
}

export interface SessionEvents {
  state: (state: LinkState) => void;
  welcome: (welcome: Welcome) => void;
  host: (host: boolean) => void;
  error: (failure: Failure) => void;
  pose: (pose: PoseOut) => void;
  /** Chaque trame reçue, après son application au miroir. */
  frame: (frame: ServerFrame, effect: FrameEffect) => void;
}

type Listeners = { [K in keyof SessionEvents]: Set<SessionEvents[K]> };

interface Pending {
  resolve: (result: Result) => void;
  deadline: number;
}

/** Les fermetures qui ne se réessaient pas : identifiant refusé ou révoqué, politique. */
const REFUSED_CODES = new Set([4401, 1008]);

/**
 * Une session du protocole `mika.world/1` : se présenter, tenir le miroir du
 * monde à jour dans l'ordre du journal, envoyer des commandes et recevoir
 * leur accusé, se reconnecter. Le jumeau de `Mika.Net.WorldSession` côté
 * Unity : même cadence de `ping` (5 s), même silence toléré (20 s), même
 * reprise (1 s × 1,5 jusqu'à 30 s), mêmes débits locaux.
 *
 * L'horloge est injectée et `tick()` fait avancer le temps : tout se teste
 * sans minuterie. `start()` branche une minuterie réelle pour le navigateur
 * (un `setInterval` vit aussi dans un onglet en arrière-plan, où
 * `requestAnimationFrame` s'arrête).
 */
export class WorldSession {
  readonly mirror: WorldMirror;
  readonly clock: KernelClock;

  private readonly opts: Required<Omit<WorldSessionOptions, "token" | "avatar" | "openSocket">> &
    Pick<WorldSessionOptions, "token" | "avatar" | "openSocket">;
  private readonly listeners: Listeners = {
    state: new Set(),
    welcome: new Set(),
    host: new Set(),
    error: new Set(),
    pose: new Set(),
    frame: new Set(),
  };
  private readonly pending = new Map<string, Pending>();
  private readonly buckets = new Map<string, { tokens: number; last: number }>();
  private readonly prefix = Math.random().toString(36).slice(2, 8);
  private counter = 0;
  private socket: SocketLike | null = null;
  private lastReceived = 0;
  private lastPing = 0;
  private retryAt = 0;
  private backoffMs = 1000;
  private failures = 0;
  private pingSentLocalUs = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;

  state: LinkState = "offline";
  welcome: Welcome | null = null;
  isHost = false;
  /** Le dernier aller-retour mesuré par `ping`/`pong`, en millisecondes. */
  roundTripMs = 0;

  constructor(options: WorldSessionOptions, mirror: WorldMirror = new WorldMirror()) {
    this.opts = {
      roles: ["viewer"],
      client: { name: "Mika Web", version: "0.1.0", engine: "three" },
      pingIntervalMs: 5000,
      silenceTimeoutMs: 20000,
      commandTimeoutMs: 10000,
      now: Date.now,
      log: (m) => console.info(`[monde] ${m}`),
      ...options,
    };
    this.mirror = mirror;
    this.clock = new KernelClock(this.opts.now);
  }

  /** L'acteur de la personne connectée (`player:…`), `null` pour un écran sans corps. */
  get actor(): string | null {
    return this.welcome?.actor ?? null;
  }

  get granted(): readonly Role[] {
    return this.welcome?.granted ?? [];
  }

  on<K extends keyof SessionEvents>(event: K, fn: SessionEvents[K]): () => void {
    const set = this.listeners[event] as Set<SessionEvents[K]>;
    set.add(fn);
    return () => set.delete(fn);
  }

  private emit<K extends keyof SessionEvents>(event: K, ...args: Parameters<SessionEvents[K]>): void {
    for (const fn of this.listeners[event] as Set<(...a: Parameters<SessionEvents[K]>) => void>) {
      try {
        fn(...args);
      } catch (err) {
        console.warn(`[monde] un abonné à « ${event} » a levé :`, err);
      }
    }
  }

  // ── cycle de vie ──────────────────────────────────────────────────

  /** Se connecte et fait tourner la minuterie (navigateur). */
  start(intervalMs = 500): void {
    this.connect();
    if (this.timer === null && typeof setInterval === "function") {
      this.timer = setInterval(() => this.tick(), intervalMs);
    }
  }

  connect(): void {
    if (this.disposed) return;
    if (this.state === "connecting" || this.state === "greeting" || this.state === "online") return;
    this.open();
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.failPending("fermé");
    const s = this.socket;
    this.socket = null;
    if (s) {
      s.onopen = s.onmessage = s.onclose = s.onerror = null;
      try {
        s.close(1000, "fermé");
      } catch {
        /* déjà fermée */
      }
    }
    this.setHost(false);
    this.setState("offline");
  }

  private open(): void {
    this.setState("connecting");
    this.lastReceived = this.opts.now();
    let socket: SocketLike;
    try {
      socket = this.opts.openSocket ? this.opts.openSocket(this.opts.url) : (new WebSocket(this.opts.url) as unknown as SocketLike);
    } catch (err) {
      this.opts.log(`ouverture impossible (${String(err)})`);
      this.onClosed(0, "ouverture impossible");
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      if (this.socket === socket) this.onOpened();
    };
    socket.onmessage = (ev) => {
      if (this.socket !== socket) return;
      this.lastReceived = this.opts.now();
      if (typeof ev.data === "string") this.onMessage(ev.data);
    };
    socket.onclose = (ev) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.onClosed(ev.code, ev.reason);
    };
    socket.onerror = () => {
      /* la fermeture suit, c'est elle qui décide */
    };
  }

  /** Fait avancer la session : ping, silence, reprise, accusés en retard. */
  tick(now: number = this.opts.now()): void {
    if (this.disposed) return;
    if (this.state === "offline" && this.retryAt > 0 && now >= this.retryAt) {
      this.retryAt = 0;
      this.open();
    }
    if (this.state === "greeting" || this.state === "online") {
      if (now - this.lastPing >= this.opts.pingIntervalMs) {
        this.lastPing = now;
        this.pingSentLocalUs = this.clock.localNowUs();
        this.send({ type: "ping", t: this.pingSentLocalUs });
      }
      if (now - this.lastReceived > this.opts.silenceTimeoutMs) {
        this.opts.log("plus de nouvelles du noyau, reconnexion");
        const s = this.socket;
        this.socket = null;
        if (s) {
          s.onopen = s.onmessage = s.onclose = s.onerror = null;
          try {
            s.close(4000, "silence");
          } catch {
            /* déjà fermée */
          }
        }
        this.onClosed(0, "silence");
      }
    }
    for (const [cmd, p] of [...this.pending]) {
      if (now > p.deadline) {
        this.pending.delete(cmd);
        p.resolve({ type: "result", cmd, status: "refused", message: "Pas de réponse du noyau." });
      }
    }
  }

  private onOpened(): void {
    this.setState("greeting");
    this.backoffMs = 1000;
    this.failures = 0;
    const m = this.mirror;
    const hello: Hello = {
      type: "hello",
      protocol: PROTOCOL as Hello["protocol"],
      roles: [...new Set(this.opts.roles)],
      client: this.opts.client,
      rev: m.world ? m.world.rev : null,
      after: m.ready ? m.seq : null,
    };
    if (this.opts.token) hello.token = this.opts.token;
    if (this.opts.avatar) hello.avatar = this.opts.avatar;
    this.lastPing = this.opts.now();
    this.send(hello);
  }

  private onClosed(code: number, reason: string | undefined): void {
    const wasHost = this.isHost;
    this.setHost(false);
    this.failPending("connexion perdue");
    if (this.disposed) return;
    if (REFUSED_CODES.has(code)) {
      this.opts.log(`connexion refusée (${code}${reason ? `, ${reason}` : ""})`);
      this.setState("refused");
      return;
    }
    // Une connexion qui tombe se dit ; les essais qui suivent, une fois sur dix seulement.
    if (this.state === "online" || this.state === "greeting" || this.failures % 10 === 0) {
      this.opts.log(
        `connexion fermée (${reason || code}), nouvel essai dans ${(this.backoffMs / 1000).toFixed(1)} s` +
          (wasHost ? " — bail d'hôte perdu" : "")
      );
    }
    this.failures = this.state === "online" ? 0 : this.failures + 1;
    this.setState("offline");
    this.retryAt = this.opts.now() + this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 1.5, 30000);
  }

  private onMessage(text: string): void {
    const read = readServer(text);
    if (!read.frame) {
      // Une trame plus récente que ce client : on la passe (« ignorer sans planter »).
      this.opts.log(`trame ignorée (${read.error})`);
      return;
    }
    const frame = read.frame;
    let effect: FrameEffect = "not_state";
    switch (frame.type) {
      case "welcome":
        this.welcome = frame;
        this.clock.sync(frame.now, this.clock.localNowUs());
        this.setState("online");
        this.emit("welcome", frame);
        break;
      case "result": {
        const p = this.pending.get(frame.cmd);
        if (p) {
          this.pending.delete(frame.cmd);
          p.resolve(frame);
        }
        break;
      }
      case "host":
        this.setHost(frame.granted);
        break;
      case "pong":
        // Le pong renvoie notre instant : il mesure l'aller-retour, pas l'heure du noyau.
        if (frame.t === this.pingSentLocalUs && this.pingSentLocalUs > 0) {
          this.roundTripMs = (this.clock.localNowUs() - this.pingSentLocalUs) / 1000;
        }
        break;
      case "error":
        this.opts.log(`erreur du noyau ${frame.code} — ${frame.message ?? ""}`);
        this.emit("error", frame);
        // Une erreur fatale : le noyau ferme ; la fermeture dira s'il faut réessayer.
        break;
      case "pose":
        this.emit("pose", frame);
        break;
      default:
        effect = this.mirror.apply(frame);
        break;
    }
    this.emit("frame", frame, effect);
  }

  // ── commandes ─────────────────────────────────────────────────────

  /**
   * Envoie une commande et rend son accusé (`result`). L'identifiant `cmd`
   * est fixé ici. Une commande hors débit est refusée sur place
   * (`rate_limited`) plutôt que d'aller se faire refuser.
   */
  command(draft: CommandDraft): Promise<Result> {
    const cmd = `${draft.type[0]}-${this.prefix}-${++this.counter}`;
    const frame = { ...draft, cmd } as CommandFrame;
    const now = this.opts.now();
    if (!this.allow(frame.type, now)) {
      return Promise.resolve({ type: "result", cmd, status: "refused", code: "rate_limited", message: "Trop de commandes." });
    }
    if (this.state !== "online") {
      return Promise.resolve({ type: "result", cmd, status: "refused", message: "Pas connectée au monde." });
    }
    return new Promise<Result>((resolve) => {
      this.pending.set(cmd, { resolve, deadline: now + this.opts.commandTimeoutMs });
      this.send(frame);
    });
  }

  /** Redemande ce qui a suivi le dernier `seq` appliqué. */
  requestSync(): void {
    if (this.state === "online" && this.mirror.ready && this.allow("sync", this.opts.now())) {
      this.send({ type: "sync", after: this.mirror.seq });
    }
  }

  private send(frame: ClientFrame): void {
    try {
      this.socket?.send(writeClient(frame));
    } catch (err) {
      this.opts.log(`envoi impossible (${String(err)})`);
    }
  }

  private allow(type: string, now: number): boolean {
    const rate = RATES[type];
    if (rate === undefined) return true;
    let b = this.buckets.get(type);
    if (!b) {
      b = { tokens: rate, last: now };
      this.buckets.set(type, b);
    }
    b.tokens = Math.min(rate, b.tokens + ((now - b.last) / 1000) * rate);
    b.last = now;
    if (b.tokens < 1) return false;
    b.tokens -= 1;
    return true;
  }

  private failPending(why: string): void {
    for (const [cmd, p] of this.pending) p.resolve({ type: "result", cmd, status: "refused", message: why });
    this.pending.clear();
  }

  private setState(state: LinkState): void {
    if (this.state === state) return;
    this.state = state;
    this.emit("state", state);
  }

  private setHost(host: boolean): void {
    if (this.isHost === host) return;
    this.isHost = host;
    this.emit("host", host);
  }
}

/** L'adresse du WebSocket du monde à partir de celle du noyau (`http://…:8001`). */
export function worldUrl(backendOrigin: string): string {
  return backendOrigin.replace(/\/+$/, "").replace(/^http/, "ws") + "/ws/world";
}
