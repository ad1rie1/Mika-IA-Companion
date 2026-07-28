import type { ServerMessageMap } from "../types";

export type MessageHandler = (data: any) => void;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Map<string, MessageHandler[]> = new Map();
  private reconnectDelay = 2000;
  private maxReconnectDelay = 30000;
  private currentDelay: number;
  private personId: string | null = null;
  private displayName: string | null = null;
  // Frames typed while the socket is down. The chat UI paints the user's
  // bubble before send() is called, so dropping them made messages look
  // delivered when they never left the browser. Bounded so a long outage
  // can't grow unbounded with 5MB attachment payloads.
  private outbox: object[] = [];
  private static readonly MAX_OUTBOX = 20;

  constructor(url: string = "ws://localhost:8000/ws") {
    this.url = url;
    this.currentDelay = this.reconnectDelay;
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
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log("WebSocket connected");
        this.currentDelay = this.reconnectDelay;

        // Handshake: tell the backend who we are so the greeting and every
        // subsequent turn can be attached to a stable person_id.
        if (this.personId) {
          this.send({
            type: "identify",
            person_id: this.personId,
            display_name: this.displayName,
          });
        }

        // After identify, so queued chat frames carry the bound identity.
        this.flushOutbox();

        this.emit("connection", { status: "connected" });
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.emit(data.type, data);
        } catch (e) {
          console.error("Failed to parse WebSocket message:", e);
        }
      };

      this.ws.onclose = () => {
        console.log("WebSocket disconnected, reconnecting...");
        this.emit("connection", {
          status: "disconnected",
          retryInMs: this.currentDelay,
        });
        this.scheduleReconnect();
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
    setTimeout(() => {
      this.currentDelay = Math.min(
        this.currentDelay * 1.5,
        this.maxReconnectDelay
      );
      this.emit("connection", { status: "reconnecting" });
      this.connect();
    }, this.currentDelay);
  }

  /** Returns false when the frame was queued instead of sent. */
  send(data: object): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      return true;
    }
    if (this.outbox.length >= WebSocketClient.MAX_OUTBOX) {
      this.outbox.shift();
    }
    this.outbox.push(data);
    return false;
  }

  /** Flush queued frames after the identify handshake. */
  private flushOutbox() {
    if (!this.outbox.length) return;
    const pending = this.outbox;
    this.outbox = [];
    for (const frame of pending) {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        // Socket died again mid-flush — keep what's left for the next open.
        this.outbox.push(frame);
        continue;
      }
      this.ws.send(JSON.stringify(frame));
    }
  }

  private withIdentity(payload: Record<string, any>): Record<string, any> {
    return this.personId
      ? { ...payload, person_id: this.personId }
      : payload;
  }

  sendChat(message: string) {
    this.send(this.withIdentity({ type: "chat", message }));
  }

  sendChatWithAttachments(
    message: string,
    attachments: Array<{ name: string; type: string; data: string }>
  ) {
    this.send(this.withIdentity({ type: "chat", message, attachments }));
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

  private emit(type: string, data: any) {
    const handlers = this.handlers.get(type);
    if (handlers) {
      for (const handler of handlers) {
        handler(data);
      }
    }
  }
}
