/**
 * Les cartes d'accord au-dessus du champ (ADR 0064, ADR 0191) et « Tout accepter » (ADR 0170) : leur état, les décisions
 * qui partent, l'acceptation d'office, leur dessin. Les règles sont dans le module pur `@web/ui/approvals`, le balisage
 * dans `markup.ts` ; `chat.ts` lui passe les trames.
 */
import type { WebSocketClient } from "@web/network/WebSocketClient";
import type { ApprovalDecision, ConnectionEvent } from "@web/types";
import {
  approvalKey,
  approvalResult,
  autoAcceptFrame,
  decisionFrame,
  EMPTY_APPROVALS,
  isDecisionTaken,
  nextRefreshDelay,
  resultMessage,
  withApprovals,
  withConnection,
  withDecisionSent,
  withResult,
  type ApprovalsState,
} from "@web/ui/approvals";
import { read, write } from "../../shared/storage";
import { $, on } from "../../shell/dom";
import { accordToggle, approvalsMarkup, cardKinds, elsewhere, type ApprovalNote, type CardKind } from "./markup";

const APPROVAL_NOTE_MS = 6000;
const OFFLINE_NOT_SENT = "Hors ligne : ta décision n'est pas partie. Réessaie à la reconnexion.";
/** « Tout accepter » (ADR 0170) : retenu par l'onglet seulement. */
const AUTO_KEY = "mika2_chat_auto_accept";

/** Ce que les cartes demandent au chat. */
export interface ApprovalsHost {
  ws(): WebSocketClient | null;
  body(): HTMLElement | null;
  operator(): boolean;
}

export class ApprovalCards {
  private approvals: ApprovalsState = EMPTY_APPROVALS;
  private readonly autoAccepted = new Set<string>();
  private autoPreferred: boolean;
  private approvalNote: ApprovalNote | null = null;
  private approvalNoteTimer: number | null = null;
  private approvalTimer: number | null = null;
  private readonly approvalOpen = new Set<number>();
  /** Ce que veut faire chaque carte (sa capacité, son brouillon), relevé dans la trame brute. */
  private cardKinds = new Map<number, CardKind>();
  /** Sur un téléphone, les cartes-liens (Mail, Teams) dépliées sous leur ligne. */
  private linksOpen = false;

  constructor(private readonly host: ApprovalsHost) {
    this.autoPreferred = read(() => sessionStorage, AUTO_KEY) === "1";
  }

  private get ws(): WebSocketClient | null {
    return this.host.ws();
  }

  private get body(): HTMLElement | null {
    return this.host.body();
  }

  get autoAccept(): boolean {
    return this.host.operator() && this.autoPreferred;
  }

  /** La connexion change ; le chat repeint ensuite (`paintApprovals`), après avoir mis à jour le reste. */
  onConnection(status: ConnectionEvent["status"]): void {
    this.approvals = withConnection(this.approvals, status);
    if (status === "connected") this.autoAccepted.clear();
  }

  onApprovals(items: unknown): void {
    this.cardKinds = cardKinds(items);
    this.approvals = withApprovals(this.approvals, items);
    const ids = new Set(this.approvals.cards.map((c) => c.id));
    for (const id of [...this.approvalOpen]) if (!ids.has(id)) this.approvalOpen.delete(id);
    this.paintApprovals();
    this.autoAcceptPending();
  }

  onApprovalResult(data: unknown): void {
    const result = approvalResult(data);
    if (!result) return;
    this.approvals = withResult(this.approvals, result.id);
    this.noteApproval(resultMessage(result.status), isDecisionTaken(result.status));
    this.paintApprovals();
  }

  private decide(id: number, decision: ApprovalDecision): void {
    const frame = decisionFrame(this.approvals, id, decision, Date.now());
    if (!frame) {
      // un bouton que le minuteur n'avait pas encore éteint : repeindre suffit
      this.paintApprovals();
      return;
    }
    if (!this.ws?.sendApproval(frame)) {
      this.noteApproval(OFFLINE_NOT_SENT, false);
      this.paintApprovals();
      return;
    }
    this.approvals = withDecisionSent(this.approvals, id);
    this.paintApprovals();
  }

  /** « Tout accepter » (ADR 0170) : la première carte acceptable part acceptée, une à la fois. */
  private autoAcceptPending(): void {
    if (!this.autoAccept || !this.ws) return;
    // un brouillon de mail ou une réponse Teams se décide là où il partira (ADR 0191) : jamais accepté d'office ici
    const here = { ...this.approvals, cards: this.approvals.cards.filter((c) => !elsewhere(this.cardKinds.get(c.id))) };
    const frame = autoAcceptFrame(here, Date.now(), this.autoAccepted);
    if (!frame || !this.ws.sendApproval(frame)) return;
    this.autoAccepted.add(approvalKey(frame));
    this.approvals = withDecisionSent(this.approvals, frame.id);
    this.paintApprovals();
  }

  private noteApproval(text: string, ok: boolean): void {
    if (this.approvalNoteTimer !== null) window.clearTimeout(this.approvalNoteTimer);
    this.approvalNote = { text, ok };
    this.approvalNoteTimer = window.setTimeout(() => {
      this.approvalNoteTimer = null;
      this.approvalNote = null;
      this.paintApprovals();
    }, APPROVAL_NOTE_MS);
  }

  paintApprovals(): void {
    if (this.approvalTimer !== null) window.clearTimeout(this.approvalTimer);
    this.approvalTimer = null;
    const now = Date.now();
    const zone = this.body ? $("[data-approvals]", this.body) : null;
    if (zone) {
      zone.innerHTML = approvalsMarkup(this.approvals, now, {
        note: this.approvalNote,
        auto: this.autoAccept,
        open: this.approvalOpen,
        kinds: this.cardKinds,
        linksOpen: this.linksOpen,
      });
      zone.hidden = !zone.innerHTML.trim();
    }
    const delay = nextRefreshDelay(this.approvals.cards, now);
    if (delay !== null) {
      this.approvalTimer = window.setTimeout(() => {
        this.approvalTimer = null;
        this.paintApprovals();
      }, delay);
    }
  }

  toggleAuto(): void {
    this.autoPreferred = !this.autoPreferred;
    write(() => sessionStorage, AUTO_KEY, this.autoPreferred ? "1" : "0");
    this.paintToggle();
    this.paintApprovals();
    this.autoAcceptPending();
  }

  paintToggle(): void {
    const btn = this.body ? $('[data-cmp="accord"]', this.body) : null;
    if (!btn) return;
    const view = accordToggle(this.autoAccept);
    btn.innerHTML = view.html;
    btn.title = view.title;
    btn.classList.toggle("bolt", this.autoAccept);
    btn.setAttribute("aria-pressed", String(this.autoAccept));
  }

  mount(section: HTMLElement): void {
    on(section, "[data-ap]", "click", (_e, b) => {
      this.decide(Number(b.dataset.id), b.dataset.ap === "accept" ? "accept" : "refuse");
    });
    on(section, "[data-ap-links]", "click", () => {
      this.linksOpen = !this.linksOpen;
      this.paintApprovals();
    });
    // les dépliants restent comme on les a laissés d'un rendu à l'autre (`toggle` ne remonte pas : on le capte)
    section.addEventListener(
      "toggle",
      (e) => {
        const d = e.target as HTMLDetailsElement;
        if (d.dataset.apMore) {
          const id = Number(d.dataset.apMore);
          if (d.open) this.approvalOpen.add(id);
          else this.approvalOpen.delete(id);
        }
      },
      true,
    );
  }
}
