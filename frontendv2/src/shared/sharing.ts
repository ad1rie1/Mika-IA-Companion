/**
 * Partager une de ses ressources (ADR 0188) — une boîte, un compte Teams, un service — avec une personne qui a un
 * compte : les niveaux d'un partage et leurs mots, ce que la personne pourra, ce qu'un partage enregistre, à qui le
 * partager, le nom de qui te partage (« d'Adrien »), ce qu'elle peut partager, et la fenêtre « Partager » que
 * Paramètres › Partages et les réglages d'une boîte ou d'un service ouvrent. Seul le propriétaire partage, et
 * seulement avec une personne qui a un compte (`app/me/sharing.py`) ; les codes sont ceux du moteur
 * (`vocab/access.py`).
 */
import { ApiError } from "../api/moi";
import { setShare, type ShareKind, type ShareLevel } from "../api/shares";
import { h } from "../shell/dom";
import { closeModal, openModal, toast } from "../shell/float";
import { ico } from "../shell/icons";
import { failureText, toastFailure } from "./kit";
import { seg, type Host } from "./settings";
import * as store from "./store";

// ── Les partages (ADR 0188) ──────────────────────────────────────────

export const SHARE_LEVELS: readonly [ShareLevel, string][] = [
  ["lire", "Lire"],
  ["preparer", "Lire et préparer"],
  ["servir", "S'en servir"],
];

/** Les niveaux d'un partage : un service se partage pour lire ou pour s'en servir, jamais « préparer ». */
export function shareLevelsFor(kind: ShareKind): [ShareLevel, string][] {
  return SHARE_LEVELS.filter(([k]) => kind !== "mcp" || k !== "preparer");
}

/** « Lire », « Lire et préparer », « S'en servir » ; « Propriétaire » pour la sienne. */
export function shareWords(level: string): string {
  if (level === "proprietaire") return "Propriétaire";
  return SHARE_LEVELS.find(([k]) => k === level)?.[1] ?? level;
}

/** Ce que la personne pourra, dit en une phrase (la fenêtre « Partager »). */
export function sharePhrase(kind: ShareKind, title: string, person: string, level: ShareLevel): string {
  const first = person.split(/\s+/)[0] || person;
  const where = kind === "mcp" ? "dans ses Outils" : kind === "teams" ? "dans son Teams" : kind === "agenda" ? "dans son Agenda" : "dans son Mail";
  const can =
    level === "lire"
      ? kind === "mcp"
        ? "pour que Mika s'en serve pour lire, en tête-à-tête avec elle ou lui"
        : "en lecture seule : ni répondre ni ranger"
      : level === "preparer"
        ? "en lecture, et Mika pourra lui préparer des réponses que tu approuveras"
        : kind === "mcp"
          ? "pour que Mika s'en serve pour elle ou lui, sur son accord pour ce qui agit"
          : "pour que Mika s'en serve pour elle ou lui, en tête-à-tête, comme pour toi";
  return `${first} verra « ${title} » ${where}, ${can}.`;
}

export const KIND_WORDS: Record<ShareKind, string> = { mail: "Boîte", teams: "Compte Teams", mcp: "Service", agenda: "Agenda" };

export interface ShareTarget {
  kind: ShareKind;
  key: string;
  person: string;
  /** Un partage qu'on change (la fenêtre a été ouverte sur lui). */
  editing: boolean;
  /** Sa personne n'a plus de compte actif (désactivé, relié depuis à une autre personne) : il ne se change plus, il
   *  se retire. */
  gone: boolean;
}

/**
 * Ce qu'un partage enregistre. En modification, la ressource et la personne du partage même — jamais ce que montrent
 * les listes de la fenêtre (désactivées, elles retombent sur leur premier choix quand le sien n'y est plus : le
 * partage partirait à une autre personne). Sinon, ce qu'on a choisi.
 */
export function shareTarget(
  preset: { kind?: ShareKind; key?: string; person?: string },
  picked: { kind: ShareKind; key: string; person: string },
  people: readonly { person: string }[],
): ShareTarget {
  if (preset.kind && preset.key && preset.person) {
    const gone = !people.some((p) => p.person === preset.person);
    return { kind: preset.kind, key: preset.key, person: preset.person, editing: true, gone };
  }
  return { ...picked, editing: false, gone: false };
}

/** À qui partager : tout le monde, sauf, pour une ressource « à toi » (`common`), ses propriétaires — elle est déjà
 *  à elles (l'API refuserait, 400). */
export function sharePeople<P extends { owner?: boolean }>(thing: { common?: boolean } | undefined, people: readonly P[]): P[] {
  return thing?.common ? people.filter((p) => !p.owner) : [...people];
}

/** « de Léa », « d'Adrien », « d'Hélène » : l'élision devant une voyelle ou un h. */
export function ofName(name: string): string {
  return /^[aeiouyhàâäéèêëîïôöùûüœ]/iu.test(name.trim()) ? `d'${name.trim()}` : `de ${name.trim()}`;
}

// ── Ce qu'elle peut partager ─────────────────────────────────────────

/** Ce qu'elle peut partager : ses boîtes, ses comptes Teams, ses services. */
export interface Shareable {
  kind: ShareKind;
  key: string;
  title: string;
  sub: string;
  /** « À toi » : déjà à chacune de ses propriétaires, qui ne se la partagent pas. */
  common?: boolean;
}

export function shareables(): Shareable[] {
  const out: Shareable[] = [];
  for (const b of store.boxes.value?.boxes ?? []) {
    if (b.level === "proprietaire") out.push({ kind: "mail", key: b.key, title: b.name, sub: b.address, common: b.common });
  }
  for (const a of store.teamsAccounts.value?.accounts ?? []) {
    if (a.level === "proprietaire") out.push({ kind: "teams", key: a.key, title: a.name, sub: a.self_name ? `ton nom dans Teams : ${a.self_name}` : "", common: a.common });
  }
  for (const s of store.services.value?.items ?? []) {
    out.push({ kind: "mcp", key: s.name, title: s.name, sub: s.purpose });
  }
  return out;
}

export function whatLabel(kind: ShareKind, title: string): string {
  return `${KIND_WORDS[kind]} « ${title} »`;
}

// ── La fenêtre « Partager » ──────────────────────────────────────────

export interface SharePreset {
  kind?: ShareKind;
  key?: string;
  person?: string;
  level?: ShareLevel;
  /** Un partage qu'on change : le nom de sa ressource et de sa personne, tels que `given` les dit (elles peuvent ne
   *  plus être dans les listes : un compte désactivé, une ressource que les listes n'ont pas encore relue). */
  title?: string;
  name?: string;
}

/** Partager une de ses ressources (ou changer un partage) : quoi, avec qui, à quel niveau. */
export async function openShareModal(host: Host, preset: SharePreset = {}): Promise<void> {
  await Promise.all([store.boxes.load(), store.teamsAccounts.load(), store.services.load(), store.people.load()]);
  if (store.people.value === null && store.people.error !== null) {
    toastFailure(store.people.error);
    return;
  }
  const things = shareables();
  const people = store.people.value?.items ?? [];
  // en modification, toujours la ressource et la personne du partage même (jamais ce que montrent les listes, qui
  // retombent sur leur premier choix quand le sien n'y est plus)
  const fixed = shareTarget(preset, { kind: "mail", key: "", person: "" }, people);
  const editing = fixed.editing;
  if (!editing && (!things.length || !people.length)) {
    openModal({
      title: "Partager",
      size: "narrow",
      body: `<p>${h(!things.length
        ? "Tu n'as rien à partager : branche d'abord une boîte, un compte Teams ou un service."
        : "Personne d'autre n'a de compte : un partage va à une personne qui a un compte.")}</p>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Fermer</button>`,
    });
    return;
  }
  // ce qu'on change n'est plus dans les listes : sa propre option, pour que la fenêtre dise le vrai
  const listed = things.find((t) => t.kind === preset.kind && t.key === preset.key);
  const options: Shareable[] = editing && !listed
    ? [{ kind: fixed.kind, key: fixed.key, title: preset.title || fixed.key, sub: "" }, ...things]
    : things;
  // la ressource demandée (« Partager… » depuis sa fiche, ou le partage qu'on change), sinon la première
  const chosen = listed ?? options[0];
  // un partage resté à une de ses propriétaires sur ce qui est « à toi » : elle l'a déjà, il ne se retire plus que
  const owns = editing && !!chosen?.common && people.some((p) => p.person === fixed.person && p.owner);
  const whom = editing && (fixed.gone || owns)
    ? [{ person: fixed.person, name: preset.name || fixed.person }, ...people.filter((p) => p.person !== fixed.person)]
    : people;
  const gone = fixed.gone || owns;
  const goneName = preset.name || fixed.person;
  const goneWhy = owns
    ? `${goneName} est une de ses propriétaires : elle l'a déjà. Ce partage ne sert plus ; tu peux le retirer.`
    : `${goneName} n'a plus de compte actif : ce partage ne se change plus. Tu peux le retirer.`;
  const el = openModal({
    title: editing ? "Changer ce partage" : "Partager",
    size: "narrow",
    body: `<div class="stack">
      <label class="field"><span>Quoi</span><select data-quoi${editing ? " disabled" : ""}>${options
        .map((t) => `<option value="${t.kind}:${h(t.key)}"${t === chosen ? " selected" : ""}>${h(whatLabel(t.kind, t.title))}</option>`)
        .join("")}</select></label>
      <label class="field"><span>Avec qui</span><select data-qui${editing ? " disabled" : ""}>${(editing ? whom : sharePeople(chosen, whom))
        .map((p) => `<option value="${h(p.person)}"${editing && p.person === fixed.person ? " selected" : ""}>${h(p.name)}</option>`)
        .join("")}</select></label>
      <div class="info-line small" data-nobody hidden>${ico("info", "sm")}<span>Les autres personnes sont ses propriétaires : ce qui est « à toi » est déjà à elles.</span></div>
      ${gone
        ? `<div class="info-line small warn-line">${ico("alert", "sm")}<span>${h(goneWhy)}</span></div>`
        : `<div class="field"><span>Ce que la personne peut</span><div data-levels></div></div>
      <div class="info-line small" data-phrase>${ico("info", "sm")}<span></span></div>`}</div>`,
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
      ${gone
        ? `<button class="btn danger" type="button" data-ok>${ico("x", "sm")}Retirer ce partage</button>`
        : `<button class="btn primary" type="button" data-ok>${ico("users", "sm")}${editing ? "Enregistrer" : "Partager"}</button>`}`,
  });
  const quoi = el.querySelector<HTMLSelectElement>("[data-quoi]")!;
  const qui = el.querySelector<HTMLSelectElement>("[data-qui]")!;
  const levels = el.querySelector<HTMLElement>("[data-levels]");
  const phrase = el.querySelector<HTMLElement>("[data-phrase] span");
  let level: ShareLevel = preset.level ?? "lire";
  const picked = () => {
    const [kind, ...rest] = quoi.value.split(":");
    const thing = options.find((t) => t.kind === kind && t.key === rest.join(":")) ?? options[0];
    return { thing, target: shareTarget(preset, { kind: thing.kind, key: thing.key, person: qui.value }, people) };
  };
  const nobody = el.querySelector<HTMLElement>("[data-nobody]");
  const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
  /** « Avec qui » suit « Quoi » : une ressource « à toi » ne se partage pas à ses propriétaires. */
  const fillWhom = () => {
    if (editing) return;
    const [kind, ...rest] = quoi.value.split(":");
    const thing = options.find((t) => t.kind === kind && t.key === rest.join(":")) ?? options[0];
    const choices = sharePeople(thing, people);
    const before = qui.value;
    qui.innerHTML = choices.map((p) => `<option value="${h(p.person)}"${p.person === before ? " selected" : ""}>${h(p.name)}</option>`).join("");
    if (nobody) nobody.hidden = choices.length > 0;
    qui.disabled = !choices.length;
    ok.disabled = !choices.length;
  };
  const levelsField = levels?.closest<HTMLElement>(".field") ?? null;
  const phraseLine = el.querySelector<HTMLElement>("[data-phrase]");
  const paint = () => {
    if (!levels || !phrase) return;
    // personne à qui le partager (les autres en sont propriétaires) : ni niveau à choisir, ni phrase sans sujet
    const none = !qui.value;
    if (levelsField) levelsField.hidden = none;
    if (phraseLine) phraseLine.hidden = none;
    if (none) return;
    const { thing, target } = picked();
    const allowed = shareLevelsFor(target.kind);
    if (!allowed.some(([k]) => k === level)) level = allowed[0][0];
    levels.innerHTML = seg("niveau", allowed, level);
    const person = whom.find((p) => p.person === target.person)?.name ?? "";
    phrase.textContent = sharePhrase(target.kind, thing.title, person, level);
  };
  quoi.addEventListener("change", () => {
    fillWhom();
    paint();
  });
  qui.addEventListener("change", paint);
  el.addEventListener("mika:seg", (e) => {
    const v = (e as CustomEvent<{ value?: string }>).detail.value as ShareLevel | undefined;
    if (v) level = v;
    paint();
  });
  fillWhom();
  paint();
  ok.addEventListener("click", async () => {
    const { target } = picked();
    ok.disabled = true;
    try {
      // une personne qui n'a plus de compte actif, ou qui en est devenue propriétaire : son partage se retire
      // seulement (un niveau vide)
      const removing = gone || target.gone;
      const done = await setShare(target.kind, target.key, target.person, removing ? "" : level);
      closeModal();
      toast(done.message || (removing ? "Partage retiré." : "Partagé."), { ico: removing ? "x" : "users" });
      await host.reload(store.shares, store.boxes, store.teamsAccounts, store.services, store.rights);
    } catch (err) {
      ok.disabled = false;
      toast(err instanceof ApiError && err.fields.person ? `${err.message}` : failureText(err), { ico: "alert", duration: 4200 });
    }
  });
}
