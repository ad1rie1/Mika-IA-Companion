/**
 * Écrire un mail : ses pièces jointes, et la fenêtre d'un mail (nouveau, transfert, retouche d'un de ses brouillons).
 * Les destinataires en puces viennent de `shared/recipients.ts` (l'Agenda s'en sert aussi), le compte d'un texte borné
 * et « Corriger » (ADR 0307) de `shared/compose.ts` (Teams aussi).
 */
import type { Person } from "../../api/mail";
import { bindCounts, canCorrect, correctButton, correctField, errorText } from "../../shared/compose";
import { bindRecipients, readRecipients } from "../../shared/recipients";
import { $, h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { addPieces, outgoingText, type OutgoingText, type Piece } from "./format";
import { composeForm, pieceChips, type ComposeForm } from "./markup";

// ── Les pièces ───────────────────────────────────────────────────────

/** Qui garde les pièces d'un mail qu'on écrit (la fenêtre, la réponse en place). */
export interface PiecesHost {
  pieces(): File[];
  /** Les pièces, changées : qui les garde repeint sa liste (`[data-jointes]`). */
  replace(next: File[]): void;
  /** Ce qui n'a pas pu être joint ; vide : plus rien à dire. */
  say(problem: string): void;
  /** Un transfert : les pièces d'origine qui repartent avec lui, comptées dans les bornes. */
  carried?(): readonly Piece[];
}

/** Repeint la liste des pièces sous `root`. */
export function paintPieces(root: ParentNode, files: readonly File[]): void {
  const list = $<HTMLElement>("[data-jointes]", root);
  if (list) list.innerHTML = pieceChips(files);
}

/** Joindre sous `root` (délégué : survit aux rendus) : le bouton et son choix de fichiers, le dépôt (`[data-depot]`), retirer une pièce. */
export function bindPieces(root: HTMLElement, host: PiecesHost): void {
  const add = (picked: readonly File[]) => {
    const got = addPieces(host.pieces(), picked, host.carried?.());
    host.replace(got.pieces);
    host.say(got.problem);
  };
  const zoneOf = (e: Event) => (e.target as Element).closest?.<HTMLElement>("[data-depot]") ?? null;
  root.addEventListener("click", (e) => {
    const t = e.target as Element;
    const button = t.closest?.<HTMLElement>("[data-joindre]");
    if (button) {
      $<HTMLInputElement>("[data-fichiers]", button.closest("[data-reply], [data-compose]") ?? root)?.click();
      return;
    }
    const gone = t.closest?.<HTMLElement>("[data-retirer-piece]");
    if (gone) {
      const at = Number(gone.dataset.retirerPiece);
      host.replace(host.pieces().filter((_, k) => k !== at));
      host.say("");
    }
  });
  root.addEventListener("change", (e) => {
    const input = e.target as HTMLInputElement;
    if (!input.matches?.("[data-fichiers]")) return;
    add([...(input.files ?? [])]);
    input.value = ""; // le même fichier, retiré, se choisit à nouveau
  });
  root.addEventListener("dragover", (e) => {
    const zone = zoneOf(e);
    if (!zone || !e.dataTransfer?.types.includes("Files")) return;
    e.preventDefault();
    zone.classList.add("over");
  });
  root.addEventListener("dragleave", (e) => zoneOf(e)?.classList.remove("over"));
  root.addEventListener("drop", (e) => {
    const zone = zoneOf(e);
    if (!zone) return;
    zone.classList.remove("over");
    if (!e.dataTransfer?.files.length) return;
    e.preventDefault();
    add([...e.dataTransfer.files]);
  });
}

// ── La fenêtre d'un mail ─────────────────────────────────────────────

export interface ComposeValues {
  box: string;
  to: Person[];
  cc: Person[];
  /** Les fichiers joints (jamais pour la retouche d'un brouillon). */
  files: File[];
  subject: string;
  body: string;
  /** Un transfert : joindre ses pièces. */
  pieces: boolean;
  /** Un brouillon qui répond : citer le mail. */
  quote: boolean;
  /** Ce qui part au serveur, dans ses bornes (`outgoingText`) : les destinataires en en-têtes, l'objet, le corps. */
  mail: OutgoingText;
}

export interface ComposeOptions extends ComposeForm {
  title: string;
  submitLabel: string;
  /** Le corps peut-il être vide (un transfert) ? */
  emptyBody?: boolean;
  /** Un transfert : ses pièces d'origine. */
  carried?: readonly Piece[];
  submit: (v: ComposeValues) => Promise<string>;
}

/** Ouvre la fenêtre ; `submit` rend le message à dire (un toast), ou lève le refus du serveur. */
export function openCompose(opts: ComposeOptions): HTMLElement {
  const el = openModal({
    title: opts.title,
    size: "wide",
    body: composeForm(opts),
    foot: `${correctButton("data-corriger", canCorrect())}<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
      <button class="btn primary" type="button" data-envoyer-mail>${ico(opts.kind === "edit" ? "check" : "send", "sm")}${h(opts.submitLabel)}</button>`,
  });
  bindRecipients(el);
  bindCounts(el);
  const form = $<HTMLElement>("[data-compose]", el)!;
  const error = $<HTMLElement>("[data-erreur]", el)!;
  const say = (text: string) => {
    error.innerHTML = text ? `${ico("alert", "xs")}${h(text)}` : "";
    error.hidden = !text;
  };
  el.addEventListener("click", (e) => {
    const t = e.target as Element;
    const fix = t.closest<HTMLButtonElement>("[data-corriger]");
    if (fix) void correctField(() => (el.isConnected ? $<HTMLTextAreaElement>("[data-corps]", form) : null), fix);
    if (t.closest("[data-cc]")) {
      $<HTMLElement>("[data-ccrow]", el)!.hidden = false;
      t.closest("[data-cc]")!.remove();
      $<HTMLInputElement>('[data-rcpt="cc"] [data-ac]', el)?.focus();
    }
    if (t.closest("[data-bcc]")) {
      $<HTMLElement>("[data-bccrow]", el)!.hidden = false;
      t.closest("[data-bcc]")!.remove();
      $<HTMLInputElement>('[data-rcpt="bcc"] [data-ac]', el)?.focus();
    }
  });
  let files: File[] = [];
  bindPieces(el, {
    pieces: () => files,
    replace: (next) => {
      files = next;
      paintPieces(el, files);
    },
    say,
    carried: () => ($<HTMLInputElement>("[data-pieces]", form)?.checked ? opts.carried ?? [] : []),
  });
  const button = $<HTMLButtonElement>("[data-envoyer-mail]", el)!;
  button.addEventListener("click", async () => {
    const to = readRecipients(form, "to");
    const cc = readRecipients(form, "cc");
    const bcc = readRecipients(form, "bcc");
    const subject = $<HTMLInputElement>("[data-objet]", form)!.value.trim();
    const body = $<HTMLTextAreaElement>("[data-corps]", form)!.value;
    if (!to.length) return say("À qui ? Ajoute au moins un destinataire.");
    if (!subject) return say("Il lui faut un objet.");
    if (!body.trim() && !opts.emptyBody) return say("Le message est vide.");
    // dans les bornes de l'API, sinon rien ne part (le serveur refuserait : rien ne part coupé)
    const fits = outgoingText({ to, cc, bcc, subject, body });
    if (!fits.mail) return say(fits.problem);
    const values: ComposeValues = {
      box: $<HTMLSelectElement>("[data-de]", form)?.value ?? opts.box,
      to,
      cc,
      files,
      subject,
      body,
      pieces: !!$<HTMLInputElement>("[data-pieces]", form)?.checked,
      quote: !!$<HTMLInputElement>("[data-citer]", form)?.checked,
      mail: fits.mail,
    };
    say("");
    button.disabled = true;
    try {
      const message = await opts.submit(values);
      closeModal();
      if (message) toast(message, { ico: opts.kind === "edit" ? "check" : "send" });
    } catch (err) {
      button.disabled = false;
      say(errorText(err));
    }
  });
  if (opts.to.length) window.setTimeout(() => $<HTMLTextAreaElement>(opts.subject ? "[data-corps]" : "[data-objet]", form)?.focus(), 40);
  return el;
}
