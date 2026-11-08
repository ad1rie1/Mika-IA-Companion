/**
 * Paramètres › Partages (ADR 0188) : ce que tu partages — tes boîtes, tes comptes Teams, tes services — avec qui et
 * à quel niveau (lire ; lire et préparer ; s'en servir), ce qu'on te partage, et « Partager… ». Seul le propriétaire
 * partage, et seulement avec une personne qui a un compte (`app/moi/shares.py`).
 */
import { ApiError } from "../../api/moi";
import { setShare, type GivenShare, type ShareKind, type ShareLevel } from "../../api/shares";
import { h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico, type IconName } from "../../shell/icons";
import { seg } from "./form";
import { confirmModal, failureText, personAvatar, toastFailure } from "./kit";
import type { Host, Page } from "./page";
import * as store from "./store";
import { KIND_WORDS, shareLevelsFor, sharePeople, sharePhrase, shareTarget, shareWords } from "./words";

const KIND_ICONS: Record<ShareKind, IconName> = { mail: "mail", teams: "teams", mcp: "server" };

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

function whatLabel(kind: ShareKind, title: string): string {
  return `${KIND_WORDS[kind]} « ${title} »`;
}

function subOf(kind: ShareKind, key: string): string {
  return shareables().find((s) => s.kind === kind && s.key === key)?.sub ?? "";
}

/** Où s'ouvre ce qu'on te partage : une boîte dans Mail, un compte dans Teams, un service sur sa fiche (Paramètres ›
 *  Services MCP, « Partagé avec toi »). */
export function openOf(kind: ShareKind, key: string): string {
  return kind === "mail" ? "#mail/messages" : kind === "teams" ? "#teams/discussions" : `#parametres/mcp/${encodeURIComponent(key)}`;
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

async function withdraw(s: GivenShare, host: Host): Promise<void> {
  const yes = await confirmModal({
    title: "Retirer ce partage",
    text: `${s.name} ne verra plus « ${s.title} » dans son Mika, et Mika ne s'en servira plus pour elle ou lui.`,
    ok: "Retirer",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await setShare(s.kind, s.key, s.person, "");
    toast(done.message || "Partage retiré.", { ico: "x" });
    await host.reload(store.shares, store.boxes, store.teamsAccounts, store.services, store.rights);
  } catch (err) {
    toastFailure(err);
  }
}

// ── La page ──────────────────────────────────────────────────────────

function givenTable(given: readonly GivenShare[]): string {
  if (!given.length) {
    return `<p class="small muted share-none">Tu ne partages rien pour l'instant. « Partager… » ouvre une de tes boîtes, un de tes comptes Teams ou un de tes services à une personne qui a un compte.</p>`;
  }
  return `<table class="tbl"><thead><tr><th>Quoi</th><th>Avec</th><th>Ce que la personne peut</th><th></th></tr></thead><tbody>${given
    .map((s, i) => {
      const sub = subOf(s.kind, s.key);
      return `<tr><td><div class="row">${ico(KIND_ICONS[s.kind], "sm")}<div><b>${h(whatLabel(s.kind, s.title))}</b>${sub ? `<div class="tiny muted">${h(sub)}</div>` : ""}</div></div></td>
        <td><div class="row">${personAvatar(s.name, "sm")}${h(s.name)}</div></td><td><span class="tag accent">${h(shareWords(s.level))}</span></td>
        <td class="actions"><button class="btn xs" type="button" data-act="share-edit" data-i="${i}">Modifier</button> <button class="btn xs ghost danger" type="button" data-act="share-remove" data-i="${i}">Retirer</button></td></tr>`;
    })
    .join("")}</tbody></table>`;
}

function receivedTable(): string {
  const received = store.shares.value?.received ?? [];
  if (!received.length) return `<p class="small muted share-none">Personne ne te partage rien pour l'instant.</p>`;
  return `<table class="tbl"><thead><tr><th>Quoi</th><th>De</th><th>Ce que tu peux</th><th></th></tr></thead><tbody>${received
    .map((s) => `<tr><td><div class="row">${ico(KIND_ICONS[s.kind], "sm")}<b>${h(whatLabel(s.kind, s.title))}</b></div></td>
      <td><div class="row">${personAvatar(s.owner_name, "sm")}${h(s.owner_name)}</div></td><td><span class="tag">${h(shareWords(s.level))}</span></td>
      <td class="actions"><a class="btn xs" href="${openOf(s.kind, s.key)}">Ouvrir</a></td></tr>`)
    .join("")}</tbody></table>`;
}

export const sharesPage: Page = {
  id: "partages",
  needs: () => [store.shares],
  extras: () => [store.boxes, store.teamsAccounts, store.services],
  view() {
    const given = store.shares.value?.given ?? [];
    const received = store.shares.value?.received ?? [];
    return `<div class="set-page">
      <p class="lede">Ce que tu partages apparaît dans le Mika de la personne, à son nom : elle le voit dans son propre Mika. Mika ne lui en dit pas plus que ce que tu ouvres, et tu retires un partage quand tu veux.</p>
      <div><h2 class="section-title">Ce que tu partages <span class="cnt">${given.length}</span></h2>${givenTable(given)}</div>
      <div><h2 class="section-title shared-title">Partagé avec toi <span class="cnt">${received.length}</span></h2>${receivedTable()}</div>
    </div>`;
  },
  actions: () => `<button class="btn primary" type="button" data-act="share-new">${ico("user-plus", "sm")}<span class="lbl">Partager…</span></button>`,
  act(name, el, _item, host) {
    const given = store.shares.value?.given ?? [];
    const s = given[Number(el.dataset.i)];
    if (name === "share-new") void openShareModal(host);
    else if (name === "share-edit" && s) void openShareModal(host, { kind: s.kind, key: s.key, person: s.person, level: s.level, title: s.title, name: s.name });
    else if (name === "share-remove" && s) void withdraw(s, host);
  },
};
