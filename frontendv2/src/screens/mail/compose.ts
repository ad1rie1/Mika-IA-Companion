/**
 * Écrire : les destinataires en puces, proposés depuis ses correspondants (`/mail/contacts?q=`, flèches et Entrée
 * comme dans la maquette), et la fenêtre d'un mail (nouveau, transfert, retouche d'un de ses brouillons).
 */
import { BackendUnreachableError } from "@web/network/api";
import { ApiError } from "../../api/moi";
import { fetchContacts, MAIL_LIMITS, type Contact, type Person } from "../../api/mail";
import { $, $$, h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { chars, countLabel, outgoingText, parseAddresses, type OutgoingText } from "./format";
import { chip, composeForm, suggestions, type ComposeForm } from "./markup";

// ── Les destinataires ────────────────────────────────────────────────

interface Pending {
  input: HTMLInputElement;
  found: Contact[];
  sel: number;
  seq: number;
  timer: number;
}

const SUGGESTED = 6;

/** Les puces d'un champ (`to`, `cc`) sous `root`, plus ce qui est tapé et vaut une adresse. */
export function readRecipients(root: ParentNode, field: "to" | "cc"): Person[] {
  const box = $<HTMLElement>(`[data-rcpt="${field}"]`, root);
  if (!box) return [];
  const chips = $$<HTMLElement>(".chip[data-addr]", box).map((c) => ({ name: c.dataset.name ?? "", address: c.dataset.addr ?? "" }));
  const typed = parseAddresses($<HTMLInputElement>("[data-ac]", box)?.value ?? "");
  return [...chips, ...typed];
}

/** Le texte d'un refus : son message, et ce qu'il dit champ par champ — le champ seul quand le message ne fait que le
 *  nommer (« « body » : 20000 caractères au plus. » devient « Message : 20000 caractères au plus »). */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) return refusalText(err.message, err.fields);
  if (err instanceof BackendUnreachableError) return "Le serveur ne répond pas : réessaie dans un instant.";
  return err instanceof Error ? err.message : String(err);
}

export function refusalText(message: string, fields: Readonly<Record<string, string>>): string {
  const names = Object.keys(fields);
  const said = names.map((k) => `${FIELD_LABEL[k] ?? k} : ${fields[k]}`).join(" · ");
  if (!said) return message;
  // le message d'une borne (`Call.arg`) nomme le champ par son code : ses mots par champ suffisent
  if (names.some((k) => message.includes(`« ${k} »`))) return said;
  return `${message} (${said})`;
}

const FIELD_LABEL: Record<string, string> = {
  to: "À",
  cc: "Cc",
  subject: "Objet",
  body: "Message",
  instruction: "Consigne",
  note: "Note",
  q: "Recherche",
  box: "Boîte",
  conversation: "Discussion",
};

/** Le compte d'un texte borné (`maxlength`), dans le `[data-limit]` de son cadre : repeint à chaque frappe. */
export function paintCount(t: HTMLTextAreaElement): void {
  const out = t.closest<HTMLElement>(".composer, [data-compose]")?.querySelector<HTMLElement>("[data-limit]");
  const max = Number(out?.dataset.limit) || 0;
  if (!out || !max) return;
  const label = countLabel(t.value, max);
  out.textContent = label;
  out.hidden = !label;
  out.classList.toggle("full", chars(t.value) >= max);
}

/** Les comptes des textes bornés sous `root` (délégué : ils survivent aux rendus). */
export function bindCounts(root: HTMLElement): void {
  root.addEventListener("input", (e) => {
    const t = e.target;
    if (t instanceof HTMLTextAreaElement && t.maxLength > 0) paintCount(t);
  });
}

function container(el: Element): HTMLElement | null {
  return el.closest<HTMLElement>("[data-reply], [data-compose]");
}

/**
 * Les champs de destinataires sous `root` (délégués : ils survivent aux rendus) — proposer ses correspondants,
 * choisir aux flèches et à Entrée, prendre une adresse tapée telle quelle, retirer une puce.
 */
export function bindRecipients(root: HTMLElement): void {
  let pending: Pending | null = null;

  const popOf = (input: HTMLElement) => {
    const host = container(input);
    return host ? $<HTMLElement>("[data-acpop]", host) : null;
  };
  const hide = () => {
    if (!pending) return;
    const pop = popOf(pending.input);
    if (pop) pop.hidden = true;
  };
  const show = (p: Pending) => {
    const pop = popOf(p.input);
    const host = container(p.input);
    const rcpt = p.input.closest(".rcpt");
    if (!pop || !host || !rcpt) return;
    pop.innerHTML = suggestions(p.found, p.input.value.trim(), p.sel);
    const r = rcpt.getBoundingClientRect();
    const base = host.getBoundingClientRect();
    pop.style.left = `${r.left - base.left}px`;
    pop.style.top = `${r.bottom - base.top + 4}px`;
    pop.style.width = `${Math.min(420, Math.max(260, r.width))}px`;
    pop.hidden = false;
  };
  /** Une puce de plus ; `refocus` : la saisie reste dans ce champ (un choix au clavier ou à la souris) — jamais quand
   *  la puce se pose parce qu'on l'a quitté (on est déjà dans le champ suivant). */
  const addChip = (input: HTMLInputElement, p: Person, refocus = true) => {
    const box = input.closest(".rcpt");
    const exists = box && $$<HTMLElement>(".chip[data-addr]", box).some((c) => (c.dataset.addr ?? "").toLowerCase() === p.address.toLowerCase());
    if (!exists) input.insertAdjacentHTML("beforebegin", chip(p));
    input.value = "";
    hide();
    pending = null;
    if (refocus) input.focus();
  };
  /** Ce qui est tapé, s'il vaut une adresse, devient une puce. */
  const takeTyped = (input: HTMLInputElement, refocus = true): boolean => {
    const typed = parseAddresses(input.value);
    if (!typed.length) return false;
    for (const p of typed) addChip(input, p, refocus);
    return true;
  };

  root.addEventListener("input", (e) => {
    const input = e.target as HTMLInputElement;
    if (!input.matches?.("[data-ac]")) return;
    const text = input.value.trim();
    if (pending && pending.input !== input) hide();
    if (!text) {
      hide();
      pending = null;
      return;
    }
    const p: Pending = pending && pending.input === input ? pending : { input, found: [], sel: 0, seq: 0, timer: 0 };
    pending = p;
    window.clearTimeout(p.timer);
    const seq = ++p.seq;
    if (chars(text) > MAIL_LIMITS.contacts) {
      // au-delà de sa borne, la recherche serait refusée : l'adresse tapée reste prise telle quelle
      p.found = [];
      show(p);
      return;
    }
    p.timer = window.setTimeout(() => {
      fetchContacts(text, SUGGESTED + 4)
        .then((found) => {
          if (pending !== p || seq !== p.seq) return;
          // pas deux fois la même personne : ce qui est déjà en puce, dans « À » ou « Cc », n'est plus proposé
          const host = container(input);
          const chosen = new Set(host ? $$<HTMLElement>(".chip[data-addr]", host).map((c) => (c.dataset.addr ?? "").toLowerCase()) : []);
          p.found = found.filter((c) => !chosen.has(c.address.toLowerCase())).slice(0, SUGGESTED);
          p.sel = 0;
          show(p);
        })
        .catch(() => {
          // sans correspondants, l'adresse tapée reste prise telle quelle
          if (pending !== p || seq !== p.seq) return;
          p.found = [];
          show(p);
        });
    }, 140);
  });

  root.addEventListener("keydown", (e) => {
    const input = e.target as HTMLInputElement;
    if (!input.matches?.("[data-ac]")) return;
    const p = pending && pending.input === input ? pending : null;
    const open = !!p && !popOf(input)?.hidden;
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && p && open && p.found.length) {
      e.preventDefault();
      p.sel = (p.sel + (e.key === "ArrowDown" ? 1 : -1) + p.found.length) % p.found.length;
      show(p);
      return;
    }
    if (e.key === "Enter" || e.key === "," || e.key === ";" || e.key === "Tab") {
      if (p && open && p.found[p.sel] && e.key !== ",") {
        e.preventDefault();
        const c = p.found[p.sel];
        addChip(input, { name: c.name, address: c.address });
        return;
      }
      if (input.value.trim() && e.key !== "Tab") {
        e.preventDefault();
        if (!takeTyped(input)) toast(`« ${input.value.trim()} » n'est pas une adresse.`, { ico: "alert" });
        return;
      }
      if (e.key === "Enter") e.preventDefault();
      return;
    }
    if (e.key === "Escape" && open) {
      e.stopPropagation();
      hide();
      return;
    }
    if (e.key === "Backspace" && !input.value) {
      const last = input.previousElementSibling;
      if (last?.matches(".chip")) last.remove();
    }
  });

  root.addEventListener("focusout", (e) => {
    const input = e.target as HTMLInputElement;
    if (!input.matches?.("[data-ac]")) return;
    window.setTimeout(() => {
      const pop = popOf(input);
      if (pop && pop.contains(document.activeElement)) return;
      if (pending?.input === input) hide();
      // on a quitté le champ : la puce se pose sans y ramener la saisie (elle est déjà dans « Objet », le message…)
      if (input.isConnected && input.value.trim() && document.activeElement !== input) takeTyped(input, false);
    }, 150);
  });

  root.addEventListener("mousedown", (e) => {
    const pick = (e.target as Element).closest?.<HTMLElement>("[data-pick]");
    if (!pick || !pending) return;
    e.preventDefault();
    const c = pending.found[Number(pick.dataset.pick)];
    if (c) addChip(pending.input, { name: c.name, address: c.address });
  });

  root.addEventListener("click", (e) => {
    const x = (e.target as Element).closest?.<HTMLElement>("[data-unchip]");
    if (x && root.contains(x)) {
      e.preventDefault();
      const field = x.closest(".rcpt");
      x.closest(".chip")?.remove();
      $<HTMLInputElement>("[data-ac]", field ?? root)?.focus();
      return;
    }
    // un clic dans le champ, à côté des puces : la saisie
    const rcpt = (e.target as Element).closest?.<HTMLElement>(".rcpt");
    if (rcpt && e.target === rcpt) $<HTMLInputElement>("[data-ac]", rcpt)?.focus();
  });
}

// ── La fenêtre d'un mail ─────────────────────────────────────────────

export interface ComposeValues {
  box: string;
  to: Person[];
  cc: Person[];
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
  submit: (v: ComposeValues) => Promise<string>;
}

/** Ouvre la fenêtre ; `submit` rend le message à dire (un toast), ou lève le refus du serveur. */
export function openCompose(opts: ComposeOptions): HTMLElement {
  const el = openModal({
    title: opts.title,
    size: "wide",
    body: composeForm(opts),
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
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
    if (t.closest("[data-cc]")) {
      $<HTMLElement>("[data-ccrow]", el)!.hidden = false;
      t.closest("[data-cc]")!.remove();
      $<HTMLInputElement>('[data-rcpt="cc"] [data-ac]', el)?.focus();
    }
  });
  const button = $<HTMLButtonElement>("[data-envoyer-mail]", el)!;
  button.addEventListener("click", async () => {
    const to = readRecipients(form, "to");
    const cc = readRecipients(form, "cc");
    const subject = $<HTMLInputElement>("[data-objet]", form)!.value.trim();
    const body = $<HTMLTextAreaElement>("[data-corps]", form)!.value;
    if (!to.length) return say("À qui ? Ajoute au moins un destinataire.");
    if (!subject) return say("Il lui faut un objet.");
    if (!body.trim() && !opts.emptyBody) return say("Le message est vide.");
    // dans les bornes de l'API, sinon rien ne part (le serveur refuserait : rien ne part coupé)
    const fits = outgoingText({ to, cc, subject, body });
    if (!fits.mail) return say(fits.problem);
    const values: ComposeValues = {
      box: $<HTMLSelectElement>("[data-de]", form)?.value ?? opts.box,
      to,
      cc,
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

/** Une petite fenêtre à un champ (une note, une consigne) ; `submit` rend le message à dire. `max` : la borne du
 *  champ dans l'API (une note : 500, une consigne : 4 000). */
export function openAsk(opts: {
  title: string;
  lede: string;
  label: string;
  placeholder: string;
  required: boolean;
  submitLabel: string;
  max: number;
  mika?: boolean;
  danger?: boolean;
  submit: (text: string) => Promise<string>;
}): void {
  const el = openModal({
    title: opts.title,
    size: "narrow",
    body: `<p class="small text-2 ask-lede">${h(opts.lede)}</p>
      <label class="field"><span>${h(opts.label)}</span><textarea rows="4" data-ask placeholder="${h(opts.placeholder)}" maxlength="${opts.max}"></textarea></label>
      <p class="small cf-error" data-erreur hidden></p>`,
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
      <button class="btn ${opts.mika ? "mika" : opts.danger ? "danger" : "primary"}" type="button" data-ok>${opts.mika ? ico("sparkle", "sm") : ""}${h(opts.submitLabel)}</button>`,
  });
  const ok = $<HTMLButtonElement>("[data-ok]", el)!;
  const error = $<HTMLElement>("[data-erreur]", el)!;
  ok.addEventListener("click", async () => {
    const text = $<HTMLTextAreaElement>("[data-ask]", el)!.value.trim();
    if (opts.required && text.length < 2) {
      error.textContent = "Dis-lui en quelques mots ce qu'il faut changer.";
      error.hidden = false;
      return;
    }
    ok.disabled = true;
    try {
      const message = await opts.submit(text);
      closeModal();
      if (message) toast(message, { mika: opts.mika, ico: opts.mika ? "sparkle" : "check" });
    } catch (err) {
      ok.disabled = false;
      error.textContent = errorText(err);
      error.hidden = false;
    }
  });
}
