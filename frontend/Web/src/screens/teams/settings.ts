/**
 * Paramètres › Teams : ses comptes Teams (à elle), leur voix — comment Mika y écrit à sa place —, comment part ce
 * qu'elle y prépare (la règle de leur canal, qu'elle règle ici : ADR 0207), la clé de leur extension (ADR 0069, 0186)
 * — montrée une seule fois à sa création, retirée d'un clic —, et les retirer. Un compte partagé avec elle se montre en
 * lecture.
 *
 * La règle d'envoi d'un compte se dessine et s'enregistre par les pièces de `../../shared/sendrules.ts` (`rulesEditor`,
 * `withoutRule`, `ruleUpdate`), les mêmes que pour une boîte (`../mail/settings.ts`).
 */
import { API_BASE } from "../../network/api";
import { ApiError } from "../../api/moi";
import {
  EXTENSION_URL,
  newExtensionKey,
  removeTeamsAccount,
  revokeExtensionKey,
  saveSendRules,
  saveTeamsAccount,
  type TeamsAccount,
} from "../../api/settings";
import { h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { area, backLink, readForm, row, section, showRefusal, subTabs, text, toggle } from "../../shared/settings";
import { ago, confirmModal, copyText, dateWords, failureText, newNonce, toastFailure } from "../../shared/kit";
import type { Host, Page } from "../../shared/settings";
import * as store from "../../shared/store";
import { ofName } from "../../shared/names";
import { rulesEditor, ruleUpdate, withoutRule } from "../../shared/sendrules";
import { shareWords } from "../../shared/sharing";

const TAB = "#parametres/teams";
const SUBS = [["compte", "Ton compte Teams"], ["regles", "Comment ça part"], ["extension", "L'extension"]] as const;

function own(): TeamsAccount[] {
  return (store.teamsAccounts.value?.accounts ?? []).filter((a) => a.level === "proprietaire");
}

function shared(): TeamsAccount[] {
  return (store.teamsAccounts.value?.accounts ?? []).filter((a) => a.level !== "proprietaire");
}

/** Le compte que la page montre : celui de la route, sinon le seul qu'elle a. */
function target(item: string | null): string | null {
  if (item) return item;
  const mine = own();
  return mine.length === 1 ? mine[0].key : null;
}

function batchTag(a: TeamsAccount, now: number): string {
  if (!a.enabled) return `<span class="tag">inactif</span>`;
  if (!a.last_batch) return `<span class="tag warn">rien reçu de son extension</span>`;
  return `<span class="tag ok">${ico("check", "xs")}dernier envoi ${h(ago(a.last_batch, now))}</span>`;
}

function extCard(a: TeamsAccount, now: number, link: boolean): string {
  const who = a.self_name ? ` · ton nom dans Teams : ${a.self_name}` : "";
  return `<div class="ext-card"><span class="acc-ico c0">${ico("plug")}</span><div class="grow"><div class="row wrap"><b>Extension « Mika · Teams »</b>${batchTag(a, now)}${a.drafts_waiting ? `<span class="tag mika">${a.drafts_waiting} réponse${a.drafts_waiting > 1 ? "s" : ""} d'elle à relire</span>` : ""}</div>
    <p class="small muted">Compte « ${h(a.name)} »${h(who)}. Le reste (sa relève toutes les 30 s, sa pause, ses exclusions) se lit dans la fenêtre de l'extension.</p></div>
    ${link ? `<a class="btn sm" href="${TAB}/${encodeURIComponent(a.key)}">Régler</a>` : `<a class="btn sm" href="#teams/discussions">Voir les discussions</a>`}</div>`;
}

function sharedCard(a: TeamsAccount): string {
  const owner = a.owner_name || "Son propriétaire";
  return `<div class="acc-card"><span class="acc-ico c7">${ico("lock")}</span>
    <div class="grow"><div class="row"><b>${h(a.name)}</b><span class="muted">${h(ofName(owner))}</span></div>
      <p class="small muted">${h(`${owner} te l'a ouvert : ${shareWords(a.level).toLowerCase()}. Tu le lis dans Teams ; seul son propriétaire le règle.`)}</p></div>
    <a class="btn sm" href="#teams/discussions">Ouvrir</a></div>`;
}

function listView(now: number): string {
  const mine = own();
  const others = shared();
  const plugged = store.teamsAccounts.value?.plugged !== false;
  const body = mine.length
    ? mine.map((a) => extCard(a, now, true)).join("")
    : `<div class="empty-card">${ico("teams")}<div><b>Aucun compte Teams à toi</b><p class="small muted">Ajoute ton compte, puis crée sa clé : l'extension « Mika · Teams » lui fera lire tes discussions, et poser ce que tu acceptes.</p></div>
        <button class="btn sm primary" type="button" data-act="teams-add">${ico("plus", "sm")}Ajouter un compte Teams</button></div>`;
  return `<div class="set-page">
    <p class="lede">Ton Teams : Mika lit tes discussions par l'extension de ton navigateur, et y prépare des réponses selon ce que tu règles ici.</p>
    ${plugged ? "" : `<div class="info-line small">${ico("info", "sm")}<span>Teams n'est pas branché sur ce serveur.</span></div>`}
    ${body}
    ${others.length ? `<h2 class="section-title shared-title">Partagé avec toi <span class="cnt">${others.length}</span></h2><div class="acc-cards">${others.map(sharedCard).join("")}</div>` : ""}
  </div>`;
}

// ── La fiche ─────────────────────────────────────────────────────────

/** L'adresse que l'extension doit joindre : celle de l'API, ou celle de cette page quand le client est construit sans
 * adresse (`VITE_BACKEND_ORIGIN` vide, en service : il parle alors à l'adresse de sa page). */
function server(): string {
  return API_BASE || location.origin;
}

/** Le zip de l'extension (ADR 0246), tel que le serveur l'a à côté de lui ; sinon, à qui le demander. */
function extensionDownload(): string {
  const ext = store.teamsAccounts.value?.extension;
  if (!ext) return `<span class="small muted">Elle n'est pas à côté de ce serveur : demande-la à ton opérateur.</span>`;
  return `<a class="btn xs primary" href="${h(EXTENSION_URL)}" download="mika-teams-${h(ext.version)}.zip">${ico("download", "xs")}Télécharger</a>
    <span class="small muted">version ${h(ext.version)}</span>`;
}

function keyRow(key: string, a: TeamsAccount, now: number): string {
  const k = a.extension_key;
  const value = k
    ? `<code class="key">${h(k.hint)}••••••••</code><span class="small muted">créée le ${h(dateWords(k.created_at, now))}</span>
       <button class="btn xs" type="button" data-act="teams-key" data-account="${h(key)}">${ico("key", "xs")}Nouvelle clé</button>
       <button class="btn xs ghost danger" type="button" data-act="teams-revoke" data-account="${h(key)}">Retirer la clé</button>`
    : `<span class="small muted">Pas de clé : son extension est refusée.</span>
       <button class="btn xs primary" type="button" data-act="teams-key" data-account="${h(key)}">${ico("key", "xs")}Nouvelle clé</button>`;
  return row("Ta clé", "Montrée une fois à sa création ; seule son empreinte est gardée. L'extension s'en sert pour pousser ce que Teams reçoit et relever ce qui part.", value);
}

function ficheView(key: string, host: Host, item: string | null, now: number): string {
  const a = own().find((x) => x.key === key);
  const other = shared().find((x) => x.key === key);
  const back = item && own().length > 1 ? backLink(TAB, "Tes comptes Teams") : item ? backLink(TAB, "Teams") : "";
  if (!a) {
    return `<div class="set-page">${back}${other
      ? `<div class="acc-cards">${sharedCard(other)}</div>`
      : `<div class="empty">${ico("teams")}<b>Compte introuvable</b><p>Il n'est pas parmi les tiens.</p></div>`}</div>`;
  }
  const cached = store.teamsSettings.get(key);
  if (!cached.value) {
    return `<div class="set-page">${back}${extCard(a, now, false)}${cached.error
      ? `<div class="empty">${ico("alert")}<b>Impossible de lire ses réglages</b><p>${h(failureText(cached.error))}</p><button class="btn sm" type="button" data-retry>${ico("refresh", "sm")}Réessayer</button></div>`
      : `<div class="empty">${ico("refresh")}<p>Chargement…</p></div>`}</div>`;
  }
  const v = cached.value.values;
  const active = host.sub("teams", "compte");
  const sub = (id: string) => ({ sub: id, hidden: active !== id });
  const compte = section(
    "Ton compte Teams",
    row("Nom affiché", "Comme elle l'appelle. Laissé vide, il prend le nom écrit en gris, reçu à sa création.", text("label", v.label, `placeholder="${h(a.key)}"`)) +
      row("Actif", "Décoché : son extension est refusée — rien n'arrive, rien ne part ; ses réglages et sa clé restent.", toggle("enabled", v.enabled)) +
      row("Ton nom", "Comme tes collègues te connaissent (vide : celui que Teams donne). Elle écrit à ta place, à la première personne.", text("display_name", v.display_name, a.self_name ? `placeholder="${h(a.self_name)}"` : "")) +
      row("Ton", "Par exemple : « tutoiement, bref, amical ».", text("tone", v.tone)) +
      row("Consignes", "Ce qu'elle ne doit jamais faire à ta place. Un message reçu, lui, n'est jamais une consigne.", area("instructions", v.instructions)) +
      row("Signer ses réponses", "Ajoute la signature sous chaque message qu'elle prépare ; « {elle} » y devient son nom.", `${toggle("sign", v.sign)}${text("signature", v.signature)}`) +
      row("Retirer ce compte", "Sa clé part avec lui, et ce que son extension avait apporté (conversations, messages, brouillons) s'efface ; ce qu'elle en a appris reste dans sa vie.", `<button class="btn sm danger" type="button" data-act="teams-remove" data-account="${h(key)}">${ico("trash", "sm")}Retirer</button>`),
    sub("compte"),
  );
  const regles = section("Comment part ce qu'elle prépare", rulesEditor(cached.value.rules, "teams"), { ...sub("regles"), single: true });
  const extension = section(
    "Brancher l'extension",
    keyRow(key, a, now) +
      row("L'adresse de Mika", "À coller dans la fenêtre de l'extension, avec ta clé.", `<code class="key">${h(server())}</code><button class="btn xs ghost" type="button" data-act="copy" data-copy="${h(server())}">${ico("copy", "xs")}Copier</button>`) +
      row("L'extension", "Chrome, Edge ou Chromium : télécharge-la et décompresse-la ; dans chrome://extensions, le mode développeur, puis « Charger l'extension non empaquetée » sur le dossier mika-teams. Colle l'adresse et ta clé dans sa fenêtre, Enregistrer et Tester. Un Teams par navigateur (ou par profil). Pour la mettre à jour : la décompresser par-dessus, puis la recharger.", extensionDownload()),
    sub("extension"),
  );
  return `<form class="set-page" data-form="teams" data-account="${h(key)}" autocomplete="off">${back}${extCard(a, now, false)}
    ${subTabs("teams", SUBS, active)}${compte}${regles}${extension}</form>`;
}

// ── Les gestes ───────────────────────────────────────────────────────

function keyModal(fresh: string): void {
  const el = openModal({
    title: "Ta clé neuve",
    size: "narrow",
    body: `<div class="stack"><p>La clé de l'extension de ce compte, montrée cette fois seulement :</p>
      <div class="row key-once"><code class="key">${h(fresh)}</code><button class="btn sm" type="button" data-copy-key>${ico("copy", "sm")}Copier</button></div>
      <div class="info-line small warn-line">${ico("alert", "sm")}<span>Elle ne sera plus montrée : colle-la maintenant dans la fenêtre de l'extension. L'ancienne ne vaut plus.</span></div></div>`,
    foot: `<span class="grow"></span><button class="btn primary" type="button" data-close>C'est collé</button>`,
  });
  el.querySelector("[data-copy-key]")?.addEventListener("click", async () => {
    toast((await copyText(fresh)) ? "Clé copiée." : "Copie refusée : sélectionne-la à la main.", { ico: "copy" });
  });
}

async function newKey(key: string, host: Host): Promise<void> {
  const a = own().find((x) => x.key === key);
  if (a?.extension_key) {
    const yes = await confirmModal({
      title: "Une clé neuve",
      text: "L'ancienne clé ne vaudra plus : l'extension sera refusée jusqu'à ce que tu lui colles la neuve.",
      ok: "Créer la clé",
    });
    if (!yes) return;
  }
  try {
    const done = await newExtensionKey(key);
    keyModal(done.key);
    await host.reload(store.teamsAccounts, store.teamsSettings);
  } catch (err) {
    toastFailure(err);
  }
}

async function removeAccount(key: string, host: Host): Promise<void> {
  const a = own().find((x) => x.key === key);
  const yes = await confirmModal({
    title: "Retirer ce compte Teams",
    text: `Retirer « ${a?.name ?? key} » ? Sa clé part avec lui : son extension sera refusée. Ce qu'elle avait apporté s'efface — ses conversations, ses messages, les brouillons de Mika. Ce que Mika en a appris reste dans sa vie.`,
    ok: "Retirer",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await removeTeamsAccount(key);
    toast(done.message || "Compte Teams retiré.", { ico: "trash" });
    host.go(TAB);
    await host.reload(store.teamsAccounts, store.teamsSettings, store.shares, store.rights);
  } catch (err) {
    toastFailure(err);
  }
}

async function revoke(key: string, host: Host): Promise<void> {
  const yes = await confirmModal({
    title: "Retirer la clé",
    text: "Son extension sera refusée jusqu'à une clé neuve : rien n'arrivera de Teams, rien n'y partira.",
    ok: "Retirer la clé",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await revokeExtensionKey(key);
    toast(done.message || "Clé retirée.", { ico: "x" });
    await host.reload(store.teamsAccounts, store.teamsSettings);
  } catch (err) {
    toastFailure(err);
  }
}

function addModal(host: Host): void {
  const el = openModal({
    title: "Ajouter un compte Teams",
    size: "narrow",
    body: `<form class="stack" data-new-teams autocomplete="off">
      <label class="field"><span>Nom affiché</span><input name="label" placeholder="Teams pro"></label>
      <label class="field"><span>Ton nom</span><input name="display_name" placeholder="comme tes collègues te connaissent"></label>
      <p class="small muted">Il sera à toi. Ensuite, crée sa clé et colle-la dans l'extension « Mika · Teams » de ton navigateur.</p></form>`,
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("plus", "sm")}Ajouter</button>`,
  });
  const form = el.querySelector<HTMLFormElement>("[data-new-teams]")!;
  const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
  const nonce = newNonce();
  const submit = async () => {
    const v = readForm(form);
    ok.disabled = true;
    try {
      const done = await saveTeamsAccount({ label: String(v.label ?? "").trim(), display_name: String(v.display_name ?? "").trim() }, "", nonce);
      closeModal();
      toast(done.message || "Compte Teams enregistré.", { ico: "check" });
      host.setSub("teams", "extension");
      host.go(`${TAB}/${encodeURIComponent(done.account)}`);
      await host.reload(store.teamsAccounts, store.rights);
    } catch (err) {
      ok.disabled = false;
      showRefusal(form, err);
    }
  };
  ok.addEventListener("click", () => void submit());
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    void submit();
  });
}

export const teamsPage: Page = {
  id: "teams",
  needs: () => [store.teamsAccounts],
  extras(item) {
    const key = target(item);
    return key && own().some((a) => a.key === key) ? [store.teamsSettings.get(key)] : [];
  },
  view(item, host) {
    const now = Date.now();
    const key = target(item);
    return key ? ficheView(key, host, item, now) : listView(now);
  },
  actions: () => `<button class="btn primary" type="button" data-act="teams-add">${ico("plus", "sm")}<span class="lbl">Ajouter un compte Teams</span></button>`,
  act(name, el, item, host) {
    const key = el.dataset.account ?? target(item) ?? "";
    if (name === "teams-add") addModal(host);
    else if (name === "teams-key") void newKey(key, host);
    else if (name === "teams-revoke") void revoke(key, host);
    else if (name === "teams-remove") void removeAccount(key, host);
    else if (name === "copy") void copyText(el.dataset.copy ?? "").then((ok) => toast(ok ? "Copié." : "Copie refusée.", { ico: "copy" }));
  },
  async save(form, changes, values, item, host) {
    const key = form.dataset.account ?? target(item) ?? "";
    // les réglages du compte d'un côté, sa règle d'envoi de l'autre (ADR 0207)
    const { rule, rest } = withoutRule(changes);
    const rules = store.teamsSettings.get(key).value?.rules;
    try {
      const said: string[] = [];
      if (Object.keys(rest).length) said.push((await saveTeamsAccount(rest as Record<string, string | boolean>, key)).message);
      if (rule && rules) said.push((await saveSendRules(ruleUpdate(rules, values))).message);
      toast(said.filter(Boolean).join(" ") || "Enregistré.", { ico: "check" });
      await host.reload(store.teamsAccounts, store.teamsSettings, store.rights);
      return true;
    } catch (err) {
      showRefusal(form, err);
      // une règle changée ailleurs entre-temps : relue, « Annuler » la remontre telle qu'elle est
      if (err instanceof ApiError && err.status === 409) void host.reload(store.teamsSettings);
      return false;
    }
  },
  search() {
    return own().map((a) => ({ group: "Paramètres", title: `Teams « ${a.name} »`, sub: a.self_name, icon: "teams" as const, route: `${TAB}/${encodeURIComponent(a.key)}` }));
  },
};
