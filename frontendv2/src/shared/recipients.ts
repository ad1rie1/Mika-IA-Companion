/**
 * Les destinataires en puces, proposés depuis ses correspondants (`/mail/contacts?q=`, flèches et Entrée comme dans
 * la maquette) : ceux d'un mail qu'on écrit, et les participants d'un événement de l'Agenda.
 */
import { fetchContacts, MAIL_LIMITS, type Contact, type Person } from "../api/mail";
import { $, $$, h } from "../shell/dom";
import { toast } from "../shell/float";
import { ico } from "../shell/icons";
import { avatar, parseAddresses, personName } from "./people";
import { chars } from "./text";

/** Un destinataire en puce (son adresse dans `data-addr`). */
export function chip(p: Person): string {
  const name = personName(p);
  return `<span class="chip" title="${h(p.address)}" data-addr="${h(p.address)}" data-name="${h(p.name)}">${avatar(name, "xs", p.address)}${h(name)}<button type="button" title="Retirer" data-unchip>${ico("x", "xs")}</button></span>`;
}

/** Les correspondants proposés sous un champ de destinataires. */
export function suggestions(found: readonly Contact[], typed: string, sel: number): string {
  if (!found.length) return `<div class="ac-none">Aucun contact : « ${h(typed)} » sera pris tel quel.</div>`;
  return found
    .map((c, k) => `<button type="button" class="ac-item${k === sel ? " on" : ""}" data-pick="${k}">${avatar(c.name || c.address, "sm", c.address)}
      <span><b>${h(c.name || c.address)}</b><small>${h(c.address)} · ${c.received} reçu${c.received > 1 ? "s" : ""} · ${c.sent} envoyé${c.sent > 1 ? "s" : ""}</small></span></button>`)
    .join("");
}

interface Pending {
  input: HTMLInputElement;
  found: Contact[];
  sel: number;
  seq: number;
  timer: number;
}

const SUGGESTED = 6;

/** Les puces d'un champ (`to`, `cc`, `bcc`) sous `root`, plus ce qui est tapé et vaut une adresse. */
export function readRecipients(root: ParentNode, field: "to" | "cc" | "bcc"): Person[] {
  const box = $<HTMLElement>(`[data-rcpt="${field}"]`, root);
  if (!box) return [];
  const chips = $$<HTMLElement>(".chip[data-addr]", box).map((c) => ({ name: c.dataset.name ?? "", address: c.dataset.addr ?? "" }));
  const typed = parseAddresses($<HTMLInputElement>("[data-ac]", box)?.value ?? "");
  return [...chips, ...typed];
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
