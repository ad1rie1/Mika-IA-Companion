import type { ServerMessageMap } from "../types";

export type MessageHandler = (data: any) => void;

/**
 * Close code the consumer uses when CONSUMER_REQUIRE_AUTH refuses an
 * unauthenticated socket (see communication/channels/web_frontend.py).
 * Permanent by nature — the session has to change before a retry can differ.
 */
export const WS_CLOSE_UNAUTHORIZED = 4401;

/** How often the client proves the socket is still carrying traffic. */
const HEARTBEAT_INTERVAL_MS = 20000;

/**
 * Silence after which the socket is presumed dead. Must clear the heartbeat
 * interval by a comfortable margin — a pong is due every 20s, so 50s means
 * two consecutive misses, not one slow round-trip on a bad connection.
 */
const HEARTBEAT_TIMEOUT_MS = 50000;

/**
 * Taille sérialisée maximale d'un frame sortant.
 *
 * Au-delà, c'est le *transport* qui refuse : uvicorn ferme la connexion en
 * 1009 avant que le frame n'atteigne le consumer, donc sans `ack`, sans trace
 * applicative, et la bulle reste « en attente d'envoi » pour toujours. Le
 * seuil doit donc rester sous le `ws_max_size` déclaré dans run.py, lui-même
 * aligné sur MAX_ATTACHMENTS × MAX_FILE_SIZE (5 × 5 Mo, soit ~34,95 Mio une
 * fois encodés en base64) : un envoi légitime passe, un envoi impossible est
 * refusé ici, à voix haute.
 *
 * Compté en unités UTF-16 et non en octets : le terme dominant est du base64,
 * donc de l'ASCII, et la marge laissée par le seuil couvre largement l'écart
 * sur les 2000 caractères de légende que le consumer accepte.
 */
const MAX_FRAME_CHARS = 34 * 1024 * 1024;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Map<string, MessageHandler[]> = new Map();
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private currentDelay: number;
  private personId: string | null = null;
  private displayName: string | null = null;
  // Frames typed while the socket is down. The chat UI paints the user's
  // bubble before send() is called, so dropping them made messages look
  // delivered when they never left the browser. Bounded so a long outage
  // can't grow unbounded with 5MB attachment payloads.
  private outbox: Array<{ frame: object; attempts: number }> = [];
  private static readonly MAX_OUTBOX = 20;
  /**
   * Réouvertures qu'un frame en file peut traverser sans réussir à partir.
   * Au-delà il est abandonné et signalé : le remettre en file indéfiniment
   * garde une bulle « en attente d'envoi » que plus rien ne fera avancer.
   */
  private static readonly MAX_OUTBOX_ATTEMPTS = 5;

  // Keepalive state.
  private heartbeatTimer: number | null = null;
  private lastFrameAt = 0;
  private reconnectTimer: number | null = null;
  /** Terminal refusal (4401) — retrying cannot change the answer. */
  private stopped = false;
  /**
   * Highest server `Message.pk` the application has taken delivery of.
   * Supplied by the owner (ChatOverlay) because *it* knows what was
   * actually rendered; the transport must not guess, or a frame dropped by
   * a throwing handler would still advance the cursor and be lost forever.
   */
  private cursorProvider: (() => number) | null = null;

  constructor(url: string = "ws://localhost:8000/ws") {
    this.url = url;
    this.currentDelay = this.reconnectDelay;
    this.installWakeListeners();
  }

  /**
   * Register the source of truth for "what have I already got?".
   * Called on every open, so a reconnect asks for exactly the gap.
   */
  setCursorProvider(fn: () => number) {
    this.cursorProvider = fn;
  }

  /** Ask the server for everything after the cursor, now. */
  requestSync() {
    const after = this.cursorProvider ? this.cursorProvider() : 0;
    this.sendNow({ type: "sync", after_id: after });
  }

  /**
   * Reconnect on the events that mean "the socket you think you have is
   * probably a corpse": the tab coming back to the foreground (background
   * timers are throttled to the point where the heartbeat stops firing) and
   * the network coming back. Both are cases where `readyState` still reads
   * OPEN and every send vanishes.
   */
  private installWakeListeners() {
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) this.ensureAlive();
      });
    }
    if (typeof window !== "undefined") {
      window.addEventListener("online", () => this.ensureAlive());
      window.addEventListener("focus", () => this.ensureAlive());
    }
  }

  /** Reconnect immediately if the socket isn't demonstrably usable. */
  private ensureAlive() {
    if (this.stopped) return;
    if (this.ws?.readyState === WebSocket.OPEN) {
      // Open is not the same as alive. Poke it and let the watchdog judge.
      this.ping();
      return;
    }
    if (this.ws?.readyState === WebSocket.CONNECTING) return;
    this.reconnectNow();
  }

  /**
   * Set the persistent identity used by all outgoing chat messages.
   * Must be called before `connect()` so the opening handshake carries it.
   */
  setIdentity(personId: string, displayName: string | null = null) {
    this.personId = personId;
    this.displayName = displayName;
  }

  connect() {
    if (this.stopped) return;
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log("WebSocket connected");
        this.currentDelay = this.reconnectDelay;
        this.lastFrameAt = Date.now();

        // Handshake: tell the backend who we are so the greeting and every
        // subsequent turn can be attached to a stable person_id.
        if (this.personId) {
          this.sendNow({
            type: "identify",
            person_id: this.personId,
            display_name: this.displayName,
          });
        }

        // Ask for the gap BEFORE replaying the outbox. The server answers a
        // sync with what it already holds; a queued message flushed first
        // would be persisted, come back in the same catch-up, and have to be
        // de-duplicated against a bubble the user is already looking at.
        this.requestSync();

        // After identify, so queued chat frames carry the bound identity.
        this.flushOutbox();

        this.startHeartbeat();
        this.emit("connection", { status: "connected" });
      };

      this.ws.onmessage = (event) => {
        // Any frame is proof of life, including one we fail to parse.
        this.lastFrameAt = Date.now();
        // Le `try` ne couvre que le décodage : une exception applicative n'a
        // rien d'un défaut de transport, et la journaliser comme tel désigne
        // le mauvais coupable. La diffusion, elle, ne lève pas (cf. `emit`).
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch (e) {
          console.error("Failed to parse WebSocket message:", e);
          return;
        }
        if (!data || typeof data.type !== "string") return;
        this.emit(data.type, data);
      };

      this.ws.onclose = (event) => {
        this.stopHeartbeat();
        // A closure the server will make again on every attempt is not a
        // network blip: retrying just produces a silent loop where the user
        // watches "reconnecting…" forever without being told the one thing
        // they could act on — that they need to sign in.
        if (event.code === WS_CLOSE_UNAUTHORIZED) {
          console.warn("WebSocket refused: authentication required");
          this.stopped = true;
          // Nothing will ever flush these — there is no next open. Held
          // frames would otherwise keep their bubbles looking queued, and
          // silently ride a *future* session if the page ever reconnects.
          this.outbox = [];
          this.emit("connection", { status: "unauthorized" });
          return;
        }
        console.log("WebSocket disconnected, reconnecting...");
        // Armer le timer AVANT de prévenir : la relance ne doit dépendre
        // d'aucun abonné. `scheduleReconnect` ne touche pas à `currentDelay`
        // (l'incrément se fait dans son callback), donc le délai annoncé
        // reste bien celui du timer qui vient d'être armé.
        this.scheduleReconnect();
        this.emit("connection", {
          status: "disconnected",
          retryInMs: this.currentDelay,
        });
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);
      };
    } catch (e) {
      console.error("Failed to connect:", e);
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer !== null) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.currentDelay = Math.min(
        this.currentDelay * 1.5,
        this.maxReconnectDelay
      );
      // Rouvrir d'abord, annoncer ensuite : même règle qu'à la fermeture.
      this.connect();
      this.emit("connection", { status: "reconnecting" });
    }, this.currentDelay);
  }

  /** Tear the socket down and reconnect without waiting out the backoff. */
  private reconnectNow() {
    if (this.stopped) return;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
    const dying = this.ws;
    this.ws = null;
    if (dying) {
      // Detach before closing: otherwise our own close() fires onclose,
      // which schedules a reconnect, and we connect twice — two sockets for
      // one client, two greetings, two of every frame.
      dying.onopen = null;
      dying.onmessage = null;
      dying.onclose = null;
      dying.onerror = null;
      try {
        dying.close();
      } catch {
        // Already closed / never opened — nothing to salvage.
      }
    }
    this.currentDelay = this.reconnectDelay;
    // Idem : l'ouverture du nouveau socket passe avant la notification. Elle
    // reste synchrone vis-à-vis de l'annonce, `onopen` ne pouvant se déclencher
    // que sur un tour de boucle ultérieur — « connected » suit donc toujours.
    this.connect();
    this.emit("connection", { status: "reconnecting" });
  }

  // ── Keepalive ─────────────────────────────────────────────────────
  //
  // A browser cannot send protocol-level ping frames, nor observe the ones
  // the server sends, so the only way to tell a live socket from a dead one
  // is to exchange application frames. This matters more than it sounds: a
  // socket killed by a sleeping laptop or a proxy reaping an idle connection
  // often never fires `onclose`. It sits at readyState OPEN and swallows
  // everything written to it — the client believes it is connected, the
  // server has long forgotten it, and every reply goes to a group with no
  // member. That is silent, and it lasts until the page is reloaded.

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return;
      if (Date.now() - this.lastFrameAt > HEARTBEAT_TIMEOUT_MS) {
        console.warn("WebSocket silent past timeout — forcing reconnect");
        this.reconnectNow();
        return;
      }
      this.ping();
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private ping() {
    this.sendNow({ type: "ping", t: Date.now() });
  }

  /** Returns false when the frame was queued instead of sent. */
  send(data: object): boolean {
    const payload = JSON.stringify(data);
    // Un frame que le transport refusera n'est pas un frame à mettre en file :
    // le mettre en attente le fait rejouer à chaque réouverture, et chaque
    // rejeu referme la connexion sans que rien ne le dise.
    if (payload.length > MAX_FRAME_CHARS) {
      this.refuseFrame(data, "frame_too_large");
      return false;
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(payload);
      return true;
    }
    if (this.outbox.length >= WebSocketClient.MAX_OUTBOX) {
      const evicted = this.outbox.shift();
      if (evicted) this.refuseFrame(evicted.frame, "send_abandoned");
    }
    this.outbox.push({ frame: data, attempts: 0 });
    return false;
  }

  /**
   * Refuser un frame à voix haute plutôt que de le laisser disparaître.
   *
   * Passe par le même `ack` que le serveur : c'est déjà ce que le chat écoute
   * pour faire passer une bulle de « en attente » à « refusé », avec sa
   * raison. Un frame sans `client_msg_id` n'a rien à corréler côté UI (les
   * frames de contrôle ne passent pas par la file), donc rien à annoncer.
   */
  private refuseFrame(frame: object, status: string) {
    const cid = (frame as { client_msg_id?: string }).client_msg_id;
    if (!cid) return;
    this.emit("ack", { type: "ack", client_msg_id: cid, status });
  }

  /**
   * Send if the socket is open, drop otherwise — never queue.
   *
   * For control frames (identify, sync, ping) whose value is entirely in
   * being current. Replaying a stale `sync` after a reconnect would ask for
   * a gap that the fresh `sync` has already closed, and a queued `ping`
   * would answer a liveness question about a socket that no longer exists.
   */
  private sendNow(data: object): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify(data));
      return true;
    } catch {
      return false;
    }
  }

  /** Flush queued frames after the identify handshake. */
  private flushOutbox() {
    if (!this.outbox.length) return;
    const pending = this.outbox;
    this.outbox = [];
    for (const entry of pending) {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        // Socket died again mid-flush — keep what's left for the next open,
        // mais pas éternellement : un frame que MAX_OUTBOX_ATTEMPTS
        // réouvertures n'ont pas réussi à faire partir ne partira pas, et le
        // garder en file laisse sa bulle « en attente » sans issue.
        entry.attempts += 1;
        if (entry.attempts > WebSocketClient.MAX_OUTBOX_ATTEMPTS) {
          this.refuseFrame(entry.frame, "send_abandoned");
          continue;
        }
        this.outbox.push(entry);
        continue;
      }
      this.ws.send(JSON.stringify(entry.frame));
    }
  }

  private withIdentity(payload: Record<string, any>): Record<string, any> {
    return this.personId
      ? { ...payload, person_id: this.personId }
      : payload;
  }

  /**
   * Send a chat turn. `clientMsgId` is echoed back on the `ack` and on the
   * resulting `speech`, which is what lets the UI move a bubble from
   * "queued" to "sent" and recognise its own message when the history
   * comes back — instead of painting it a second time.
   *
   * Returns false when the frame was queued because the socket is down.
   */
  sendChat(message: string, clientMsgId?: string): boolean {
    return this.send(
      this.withIdentity({ type: "chat", message, client_msg_id: clientMsgId })
    );
  }

  sendChatWithAttachments(
    message: string,
    attachments: Array<{ name: string; type: string; data: string }>,
    clientMsgId?: string
  ): boolean {
    return this.send(
      this.withIdentity({
        type: "chat",
        message,
        attachments,
        client_msg_id: clientMsgId,
      })
    );
  }

  on<K extends keyof ServerMessageMap>(
    type: K,
    handler: (msg: ServerMessageMap[K]) => void
  ): void;
  on(type: string, handler: MessageHandler): void;
  on(type: string, handler: MessageHandler) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, []);
    }
    this.handlers.get(type)!.push(handler);
  }

  /**
   * Diffuser un frame à ses abonnés, chacun isolé du suivant.
   *
   * `emit` ne lève pas, par construction. C'est ce qui le rend appelable
   * depuis les chemins qui maintiennent la connexion en vie : un handler qui
   * touche au DOM ou au localStorage (ChatOverlay purge sa file d'attente sur
   * « disconnected ») transformait sinon une coupure réseau banale en état
   * hors-ligne définitif, aucun timer n'étant plus armé derrière lui.
   *
   * Et sur une réponse, un abonné qui lève ne doit pas emporter les suivants :
   * l'ordre d'inscription n'est qu'un détail de câblage de main.ts, il ne dit
   * rien sur qui a le droit de faire taire qui.
   */
  private emit(type: string, data: any) {
    const handlers = this.handlers.get(type);
    if (!handlers) return;
    for (const handler of handlers) {
      try {
        handler(data);
      } catch (e) {
        console.error(`WebSocket handler failed on "${type}":`, e);
      }
    }
  }
}
