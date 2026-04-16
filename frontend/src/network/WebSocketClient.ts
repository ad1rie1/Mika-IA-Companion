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
        this.emit("connection", { status: "disconnected" });
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
      this.connect();
    }, this.currentDelay);
  }

  send(data: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
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
