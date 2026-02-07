import { WebSocketClient } from "../network/WebSocketClient";

export class ChatOverlay {
  private messagesEl: HTMLElement;
  private inputEl: HTMLInputElement;
  private sendBtn: HTMLElement;
  private ws: WebSocketClient;

  constructor(ws: WebSocketClient) {
    this.ws = ws;
    this.messagesEl = document.getElementById("chat-messages")!;
    this.inputEl = document.getElementById("chat-input") as HTMLInputElement;
    this.sendBtn = document.getElementById("chat-send")!;

    this.setupEvents();
  }

  private setupEvents() {
    // Send on button click
    this.sendBtn.addEventListener("click", () => this.sendMessage());

    // Send on Enter
    this.inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // Receive messages from backend
    this.ws.on("speech", (data) => {
      this.addMessage(data.text, "vtuber");
    });
  }

  private sendMessage() {
    const text = this.inputEl.value.trim();
    if (!text) return;

    this.addMessage(text, "user");
    this.ws.sendChat(text);
    this.inputEl.value = "";
  }

  addMessage(text: string, sender: "user" | "vtuber") {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;
    bubble.textContent = text;
    this.messagesEl.appendChild(bubble);

    // Auto-scroll to bottom
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;

    // Limit displayed messages
    while (this.messagesEl.children.length > 50) {
      this.messagesEl.removeChild(this.messagesEl.firstChild!);
    }
  }
}
