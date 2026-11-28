/**
 * Écrire un message, ce que Mail et Teams partagent : le compte d'un texte borné, « Corriger » (ADR 0307), le texte
 * d'un refus, la petite fenêtre à un champ (une note, une consigne), les passages « [À COMPLÉTER » d'un brouillon
 * qu'elle a prérempli. Les destinataires en puces sont dans `recipients.ts`.
 */
import { BackendUnreachableError } from "../network/api";
import { correctText } from "../api/me";
import { ApiError } from "../api/moi";
import { $, h } from "../shell/dom";
import { closeModal, openModal, toast } from "../shell/float";
import { ico } from "../shell/icons";
import { me } from "./store";
import { chars, thousands } from "./text";

// ── Le compte d'un texte borné ───────────────────────────────────────

/** Le compte d'un texte borné, montré quand il approche de sa borne (« 16 400 / 20 000 », comme le champ du chat) ;
 *  vide avant. */
export function countLabel(text: string, max: number): string {
  const n = chars(text);
  if (n < max * 0.8) return "";
  return `${thousands(n)} / ${thousands(max)}${n >= max ? " — la limite" : ""}`;
}

/** Le compte d'un texte borné (près de son champ) : caché tant qu'il est loin de sa borne ; `paintCount` le suit.
 *  (`data-limit`, pas `data-count` : ce nom-là est celui des pastilles de la barre du haut.) */
export function countSpan(text: string, max: number, cls = ""): string {
  const label = countLabel(text, max);
  return `<span class="small muted cmp-count${cls ? ` ${cls}` : ""}${chars(text) >= max ? " full" : ""}" data-limit="${max}"${label ? "" : " hidden"}>${h(label)}</span>`;
}

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

// ── Corriger (ADR 0307) ──────────────────────────────────────────────

/** « Corriger » éteint : pourquoi (le rôle `correct` n'a pas de modèle). */
export const CORRECT_OFF = "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence.";

/** Le bouton « Corriger » d'un champ : `attr` le désigne à son écran (`data-tm="corriger"`, `data-act="corriger"`) ;
 *  éteint sans modèle, il dit pourquoi. */
export function correctButton(attr: string, on: boolean): string {
  return `<button class="btn sm ghost" type="button" ${attr} title="${h(on ? "Corriger les fautes, sans changer les mots" : CORRECT_OFF)}"${on ? "" : " disabled"}>${ico("check", "sm")}<span class="lbl">Corriger</span></button>`;
}

/** « Corriger » marche-t-il ? Un modèle est donné au rôle `correct` (`GET /api/moi` → `correct`). */
export function canCorrect(): boolean {
  return me.value?.correct === true;
}

/** Ce que dit « Corriger » une fois fait : combien de fautes, ou aucune ; et ce qui a été écarté parce que ça touchait
 *  aux mots (ADR 0307). */
export function correctedText(changes: number, refused = 0): string {
  if (!changes) return refused ? "La correction touchait aux mots : rien n'a été changé." : "Aucune faute : ton texte reste tel quel.";
  const done = changes > 1 ? `${changes} fautes corrigées` : "1 faute corrigée";
  if (!refused) return `${done}.`;
  return `${done} ; ${refused > 1 ? `${refused} changements écartés : ils touchaient` : "1 changement écarté : il touchait"} aux mots.`;
}

/** Ce que devient une correction revenue (ADR 0307) : posée, ou non — le champ n'est plus là (la fenêtre fermée,
 *  une autre discussion ouverte : rien à dire), ou tu as continué d'écrire. */
export function correctTurn(before: string, now: string | null, sameScope: boolean): "put" | "gone" | "moved" {
  if (now === null || !sameScope) return "gone";
  return now === before ? "put" : "moved";
}

/** Une correction en cours (une à la fois : un bouton redessiné pendant l'appel ne la relance pas). */
let correcting = false;

function put(t: HTMLTextAreaElement, text: string): void {
  t.value = text;
  // ce que l'écran suit à la frappe (le compte, ce qui est tapé) le voit comme une saisie
  t.dispatchEvent(new Event("input", { bubbles: true }));
}

/** « Corriger » : les fautes du texte du champ, corrigées sans changer ses mots (ADR 0307). Le texte corrigé remplace
 *  le tien aussitôt, et le toast offre « Annuler » ; rien n'est posé si tu as continué d'écrire pendant ce temps, ni
 *  ailleurs que là où tu l'as demandé. `field` rend le champ tel qu'il est à l'écran (il a pu être redessiné pendant
 *  l'appel) ; `scope` dit où l'on est (la discussion, le mail ouverts) : changé entre-temps, rien n'est posé. */
export async function correctField(field: () => HTMLTextAreaElement | null, button: HTMLButtonElement | null,
  scope: () => string = () => ""): Promise<void> {
  const start = field();
  if (!start || correcting) return;
  const before = start.value;
  const where = scope();
  if (!before.trim()) {
    toast("Rien à corriger : le champ est vide.", { ico: "info" });
    return;
  }
  correcting = true;
  const label = button?.querySelector(".lbl");
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  if (label) label.textContent = "Correction…";
  try {
    const got = await correctText(before);
    const now = field();
    const turn = correctTurn(before, now?.isConnected ? now.value : null, scope() === where);
    if (turn === "gone" || !now) return;
    if (turn === "moved") {
      toast("Tu as continué d'écrire : la correction n'a pas été posée.", { ico: "info" });
      return;
    }
    if (!got.changes) {
      toast(correctedText(0, got.refused ?? 0), got.refused ? { ico: "info" } : {});
      return;
    }
    put(now, got.text);
    toast(correctedText(got.changes, got.refused ?? 0), {
      action: {
        label: "Annuler",
        run: () => {
          const t = field();
          if (t && t.value === got.text) put(t, before);
        },
      },
    });
  } catch (err) {
    toast(errorText(err), { ico: "alert" });
  } finally {
    correcting = false;
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
    if (label) label.textContent = "Corriger";
  }
}

// ── Le texte d'un refus ──────────────────────────────────────────────

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
  bcc: "Cci",
  files: "Pièces",
  subject: "Objet",
  body: "Message",
  instruction: "Consigne",
  note: "Note",
  q: "Recherche",
  box: "Boîte",
  conversation: "Discussion",
};

// ── Une petite fenêtre à un champ ────────────────────────────────────

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

// ── Ce qu'elle a laissé à compléter ──────────────────────────────────

const TO_FILL = /\[\s*(?:a\s*)?(?:completer|remplir|preciser)\b/;

function fold(text: string): string {
  return String(text || "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

/** Reste-t-il un « [À COMPLÉTER » (sous toutes ses graphies, comme `ports/drafts.py::to_fill`) ? */
export function toFill(...texts: string[]): boolean {
  return texts.some((t) => TO_FILL.test(fold(t)));
}

/** Dans un texte déjà échappé : chaque passage à compléter en rouge (`<mark class="completer">`). */
export function markToFill(escaped: string): string {
  return escaped.replace(/\[[^\]\n]{0,300}(?:\]|$)/gm, (m) => (toFill(m) ? `<mark class="completer">${m}</mark>` : m));
}
