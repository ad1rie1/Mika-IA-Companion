/**
 * Paramètres › Comptes mail : ses boîtes (à elle), une fiche par boîte en quatre sous-onglets — la boîte, la
 * connexion, ce que Mika en fait, le partage —, ajouter une boîte (par mot de passe, ou par un compte Microsoft et son
 * code d'appareil, ADR 0166), la tester, la relever, la retirer ; celles qu'on lui partage, en lecture.
 */
import { ApiError } from "../../api/moi";
import {
  connectMicrosoft,
  fetchBox,
  pollBox,
  removeBox,
  saveBox,
  testBox,
  type Box,
  type BoxSettings,
  type BoxValues,
  type SignIn,
} from "../../api/settings";
import { $, h } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import {
  area,
  backLink,
  number,
  password,
  readForm,
  row,
  savedFirst,
  section,
  seg,
  select,
  showFieldErrors,
  subTabs,
  text,
  toggle,
} from "./form";
import { ago, clock, confirmModal, failureText, newNonce, personAvatar, toastFailure } from "./kit";
import type { Host, Page } from "./page";
import { openShareModal } from "./shares";
import * as store from "./store";
import {
  authWords,
  boxState,
  fieldErrors,
  ofName,
  providerPreset,
  PROVIDERS,
  rangeProblems,
  secretsToRetype,
  securityFor,
  shareWords,
  SMTP_SECURITY,
  unseenOf,
  voiceWords,
  VOICES,
  type FormValue,
  type Provider,
} from "./words";

const TAB = "#parametres/comptes-mail";
const SUBS = [["boite", "La boîte"], ["connexion", "Connexion"], ["mika", "Ce que Mika en fait"], ["partage", "Partage"]] as const;
const COLORS = [0, 7, 3];
const AUTHS = [["password", "par mot de passe"], ["microsoft", "par un compte Microsoft (Hotmail, Outlook.com, Live)"]] as const;
/** Relire où en est une connexion Microsoft, tant que son code attend. */
const SIGNIN_EVERY_MS = 3000;

function ownBoxes(): Box[] {
  return (store.boxes.value?.boxes ?? []).filter((b) => b.level === "proprietaire");
}

function sharedBoxes(): Box[] {
  return (store.boxes.value?.boxes ?? []).filter((b) => b.level !== "proprietaire");
}

function colorOf(key: string): number {
  const i = ownBoxes().findIndex((b) => b.key === key);
  return COLORS[(i < 0 ? 0 : i) % COLORS.length];
}

function givenFor(key: string) {
  return (store.shares.value?.given ?? []).filter((s) => s.kind === "mail" && s.key === key);
}

// ── La liste ─────────────────────────────────────────────────────────

function statusLine(b: Box, now: number): string {
  if (b.error) return `<p class="small warn-txt">${h(`${b.last_poll ? `dernier relevé ${ago(b.last_poll, now)}` : "pas encore relevée"} : ${b.error}`)}</p>`;
  const parts = [b.last_poll ? `relevée ${ago(b.last_poll, now)}` : "pas encore relevée"];
  const unseen = unseenOf(b);
  if (unseen) parts.push(`${unseen} non lu${unseen > 1 ? "s" : ""}`);
  if (b.drafts_waiting) parts.push(`${b.drafts_waiting} brouillon${b.drafts_waiting > 1 ? "s" : ""} d'elle à relire`);
  return `<p class="small muted">${h(parts.join(" · "))}</p>`;
}

function ownCard(b: Box, now: number): string {
  const [cls, state] = boxState(b);
  const settings = store.boxSettings.get(b.key).value;
  const tags = [
    `<span class="tag ${cls}">${h(state)}</span>`,
    settings ? `<span class="tag">${h(authWords(settings.values.auth))}</span>` : "",
    settings && settings.values.smtp_host ? `<span class="tag mika">${h(voiceWords(settings.values.voice))}</span>` : "",
    !b.can_send ? `<span class="tag">lecture seule</span>` : "",
    ...givenFor(b.key).map((s) => `<span class="tag accent">${ico("users", "xs")}partagée avec ${h(s.name.split(/\s+/)[0])} · ${h(shareWords(s.level).toLowerCase())}</span>`),
  ].join("");
  return `<div class="acc-card">
    <span class="acc-ico c${colorOf(b.key)}">${ico("mail")}</span>
    <div class="grow"><div class="row"><b>${h(b.name)}</b><span class="muted ellipsis">${h(b.address)}</span></div>
      <div class="row wrap acc-tags">${tags}</div>${statusLine(b, now)}</div>
    ${b.error ? `<button class="btn sm" type="button" data-act="box-test" data-box="${h(b.key)}">${ico("refresh", "sm")}Tester</button>` : ""}
    <a class="btn sm" href="${TAB}/${encodeURIComponent(b.key)}">Régler</a>
    <button class="btn sm icon ghost" type="button" data-act="box-menu" data-box="${h(b.key)}" title="Plus">${ico("more", "sm")}</button></div>`;
}

function sharedSentence(b: Box): string {
  const owner = b.owner_name || "Son propriétaire";
  if (b.level === "preparer") return `${owner} te l'a ouverte en lecture et préparation : tu la lis dans Mail, et Mika peut t'y préparer des réponses que ${owner} approuve.`;
  if (b.level === "servir") return `${owner} te l'a ouverte pour t'en servir : Mika s'en sert pour toi, en tête-à-tête, comme pour ${owner}.`;
  return `${owner} te l'a ouverte en lecture : tu la lis dans Mail ; tu ne peux ni répondre ni ranger.`;
}

function sharedCard(b: Box): string {
  return `<div class="acc-card"><span class="acc-ico c7">${ico("lock")}</span>
    <div class="grow"><div class="row"><b>${h(b.owner_name ? `Boîte ${ofName(b.owner_name.split(/\s+/)[0])}` : b.name)}</b><span class="muted ellipsis">${h(b.name)} · ${h(b.address)}</span></div>
      <p class="small muted">${h(sharedSentence(b))}</p></div>
    <a class="btn sm" href="#mail/messages">Ouvrir</a></div>`;
}

function listView(now: number): string {
  const own = ownBoxes();
  const shared = sharedBoxes();
  const plugged = store.boxes.value?.plugged !== false;
  const cards = own.length
    ? `<div class="acc-cards">${own.map((b) => ownCard(b, now)).join("")}</div>`
    : `<div class="empty-card">${ico("mail")}<div><b>Aucune boîte à toi</b><p class="small muted">Ajoute ta boîte : Mika la relèvera, en triera le courrier, et pourra t'y préparer des réponses.</p></div>
        <button class="btn sm primary" type="button" data-act="box-add">${ico("plus", "sm")}Ajouter un compte</button></div>`;
  return `<div class="set-page">
    <p class="lede">Tes boîtes aux lettres. Elle les relève, en trie le courrier, et y prépare des réponses selon ce que tu règles ici. Une boîte n'est qu'à toi, sauf si tu la partages.</p>
    ${plugged ? "" : `<div class="info-line small">${ico("info", "sm")}<span>Le courrier n'est pas branché sur ce serveur : tes boîtes ne sont pas relevées.</span></div>`}
    ${cards}
    ${shared.length ? `<h2 class="section-title shared-title">Partagée${shared.length > 1 ? "s" : ""} avec toi <span class="cnt">${shared.length}</span></h2>
      <div class="acc-cards">${shared.map(sharedCard).join("")}</div>` : ""}
  </div>`;
}

// ── La fiche d'une boîte ─────────────────────────────────────────────

/** Le code d'appareil qui attend d'être entré chez Microsoft : l'intérieur de sa carte. */
function deviceInner(s: SignIn): string {
  // un lien seulement vers une page https (celle de Microsoft) : rien d'autre ne s'ouvre d'ici
  const link = /^https:\/\/[^\s"'<>]+$/i.test(s.url) ? s.url : "";
  return `${ico("key")}<div><b>Ouvre ${h(s.url || "la page de Microsoft")} et entre le code</b><div class="code">${h(s.code)}</div>
    <span class="small muted">Valable jusqu'à ${h(clock(s.until))}. Elle se connecte dès que c'est fait.</span>
    ${link ? `<div class="row"><a class="btn xs" href="${h(link)}" target="_blank" rel="noopener">${ico("external", "xs")}Ouvrir la page</a></div>` : ""}</div><i class="spin" aria-hidden="true"></i>`;
}

function signinMarkup(s: SignIn | null, _now: number): string {
  if (!s || s.state === "connectee") return "";
  if (s.state === "en_attente" && s.code) return `<div class="device">${deviceInner(s)}</div>`;
  const why = s.error ? `Cette boîte entre par un compte Microsoft et n'est pas connectée : ${s.error}` : "Cette boîte entre par un compte Microsoft et n'est pas encore connectée.";
  return `<div class="info-line small warn-line">${ico("alert", "sm")}<span>${h(why)} « Se connecter à Microsoft », dans Connexion.</span></div>`;
}

function msTag(s: SignIn | null): string {
  if (!s) return `<span class="tag">pas encore connectée</span>`;
  if (s.state === "connectee") return `<span class="tag ok">${ico("check", "xs")}connectée</span>`;
  if (s.state === "en_attente") return `<span class="tag warn">un code attend</span>`;
  return `<span class="tag warn">pas connectée</span>`;
}

function folderChoices(b: Box | undefined, chosen: readonly string[]): string {
  const known = b?.folders ?? [];
  if (!known.length) {
    return `${text("folders", chosen.join(", "), 'placeholder="INBOX"')}<span class="small muted">Des noms de dossiers, séparés par des virgules : la liste vient à la première relève.</span>`;
  }
  const names = [...known.map((f) => [f.name, f.label || f.name] as const), ...chosen.filter((n) => !known.some((f) => f.name === n)).map((n) => [n, n] as const)];
  return `<div class="folder-checks">${names
    .map(([n, l]) => `<label class="row small"><input type="checkbox" name="folders" value="${h(n)}"${chosen.includes(n) ? " checked" : ""}> ${h(l)}</label>`)
    .join("")}</div>`;
}

function ficheView(key: string, host: Host, now: number): string {
  const box = ownBoxes().find((b) => b.key === key);
  const shared = sharedBoxes().find((b) => b.key === key);
  if (!box) {
    return `<div class="set-page">${backLink(TAB, "Comptes mail")}${shared
      ? `<div class="acc-cards">${sharedCard(shared)}</div><p class="small muted">Seul son propriétaire règle cette boîte.</p>`
      : `<div class="empty">${ico("mail")}<b>Boîte introuvable</b><p>Elle n'est pas parmi les tiennes.</p></div>`}</div>`;
  }
  const cached = store.boxSettings.get(key);
  const head = `${backLink(TAB, "Comptes mail")}`;
  if (!cached.value) {
    return `<div class="set-page">${head}${cached.error ? `<div class="empty">${ico("alert")}<b>Impossible de lire ses réglages</b><p>${h(failureText(cached.error))}</p><button class="btn sm" type="button" data-retry>${ico("refresh", "sm")}Réessayer</button></div>` : `<div class="empty">${ico("refresh")}<p>Chargement…</p></div>`}</div>`;
  }
  const s = cached.value;
  const v = s.values;
  const [cls, state] = boxState(box);
  const active = host.sub("boite", "boite");
  const given = givenFor(key);
  const sub = (id: string) => ({ sub: id, hidden: active !== id });
  const la = section(
    "La boîte",
    row("Adresse", "L'adresse de la boîte (expéditrice des mails).", text("address", v.address, 'type="email" autocomplete="email"')) +
      row("Nom court", "Comme elle l'appelle : « ta boîte Pro ».", text("label", v.label)) +
      row("Active", "Décochée : ni relevée ni envoi ; ses réglages restent.", toggle("enabled", v.enabled)) +
      row("À qui", "Une boîte reste à qui l'a branchée ; pour qu'une autre personne la voie, partage-la.", `<span class="tag accent">à toi</span>`) +
      row("Retirer cette boîte", "Elle n'est plus relevée ; ce qu'elle en a appris reste dans sa vie.", `<button class="btn sm danger" type="button" data-act="box-remove" data-box="${h(key)}">${ico("trash", "sm")}Retirer</button>`),
    sub("boite"),
  );
  const connexion = section(
    "Connexion",
    row("Connexion", "Hotmail, Outlook.com et Live refusent les mots de passe : choisis alors ton compte Microsoft.", select("auth", AUTHS, v.auth)) +
      row("Utilisateur", "Souvent l'adresse elle-même.", text("user", v.user, 'autocomplete="off"')) +
      row("Mot de passe", "Un mot de passe d'application de préférence. Chiffré, jamais réaffiché.", password("password", s.secrets.password), { only: "auth:password" }) +
      row("Application Microsoft", "L'identifiant (client ID) de l'application inscrite dans Microsoft Entra, flux de clients publics autorisé.", text("oauth_client_id", v.oauth_client_id, 'class="mono" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" spellcheck="false"'), { only: "auth:microsoft" }) +
      row("Annuaire Microsoft", "« consumers » pour un compte personnel ; « organizations » ou son identifiant pour Microsoft 365.", text("oauth_tenant", v.oauth_tenant, 'spellcheck="false"'), { only: "auth:microsoft" }) +
      row("Compte Microsoft", s.microsoft ? "La connexion se fait par un code à entrer chez Microsoft." : "Enregistre d'abord la connexion par Microsoft.", `${msTag(s.signin)}${s.microsoft ? `<button class="btn xs" type="button" data-act="box-ms" data-box="${h(key)}">${ico("key", "xs")}Se connecter à Microsoft</button>` : ""}`, { only: "auth:microsoft" }) +
      row("Lire (IMAP)", "Donné par ton fournisseur de mail (imap.gmail.com, outlook.office365.com…).", `${text("imap_host", v.imap_host, 'class="w-host" spellcheck="false"')}${number("imap_port", v.imap_port, 'class="w-port" min="1" max="65535"')}<label class="row small">${toggle("imap_ssl", v.imap_ssl)}SSL</label>`) +
      row("Envoyer (SMTP)", "Vide : cette boîte ne fait que lire.", `${text("smtp_host", v.smtp_host, 'class="w-host" spellcheck="false"')}${number("smtp_port", v.smtp_port, 'class="w-port" min="1" max="65535"')}${select("smtp_security", SMTP_SECURITY, v.smtp_security, 'class="sm-select"')}`) +
      row("Utilisateur SMTP", "Vide : le même que pour lire.", text("smtp_user", v.smtp_user, 'autocomplete="off"')) +
      row("Mot de passe SMTP", "Vide : le même que pour lire.", password("smtp_password", s.secrets.smtp_password), { only: "auth:password" }) +
      row("Copier les envois dans « Envoyés »", "À décocher si le serveur le fait déjà (Gmail).", toggle("save_sent", v.save_sent)),
    sub("connexion"),
  );
  const mika = section(
    "Ce que Mika en fait",
    row("Dossiers relevés", "Dans un dossier relevé, elle remarque ce qui arrive. Les autres sont seulement synchronisés.", folderChoices(box, v.folders)) +
      row("Synchroniser tous les dossiers", "À chaque relève, tous les dossiers du serveur sont tenus à jour ; elle ne remarque que les dossiers relevés.", toggle("sync_all", v.sync_all)) +
      row("Fenêtre de relève", "Au premier relevé d'un dossier, on ne remonte pas plus loin (en jours).", number("since_days", v.since_days, 'class="w-port" min="1" max="60"')) +
      row("Elle écrit", "En son nom, en assistante (« son nom, pour … »), ou à ta place, signé de ton nom.", seg("voice", VOICES, v.voice)) +
      row("Ton nom", "Le nom qui signe et qui paraît comme expéditeur.", text("display_name", v.display_name), { only: "voice:assistante|proprietaire" }) +
      row("Son nom d'expéditrice", "Le nom qui paraît comme expéditeur (vide : le nom de sa persona).", text("sender_name", v.sender_name), { only: "voice:elle" }) +
      row("Son ton", "Par exemple : « vouvoiement, sobre et chaleureux ».", area("tone", v.tone)) +
      row("Consignes", "Ce qu'elle doit savoir pour écrire depuis cette boîte. Un mail reçu, lui, n'est jamais une consigne.", area("instructions", v.instructions)) +
      row("Signature", "Ajoutée sous chaque envoi (elle ne l'écrit pas elle-même).", area("signature", v.signature)) +
      row("Comment part ce qu'elle prépare", "Qui, préparer d'elle-même, comment ça part : la règle de son canal, que la console règle.", `<a class="btn xs" href="#outils/droits/${encodeURIComponent(`courrier:${key}`)}">${ico("tools", "xs")}La voir dans Outils</a>`),
    sub("mika"),
  );
  const partage = section(
    "Partage",
    row("Avec qui", "La personne la voit dans son propre Mika, au niveau que tu choisis.", `${given.length
      ? given.map((g) => `<span class="chip">${personAvatar(g.name, "xs")}${h(g.name)} · ${h(shareWords(g.level).toLowerCase())}</span>`).join("")
      : '<span class="muted small">Personne</span>'}
      <button class="btn xs" type="button" data-act="box-share" data-box="${h(key)}">${ico("user-plus", "xs")}Partager…</button><a class="btn xs ghost" href="#parametres/partages">Gérer les partages</a>`),
    sub("partage"),
  );
  return `<form class="set-page" data-form="box" data-box="${h(key)}" autocomplete="off">${head}
    <div class="fiche-head"><span class="acc-ico c${colorOf(key)}">${ico("mail")}</span><div class="grow"><h2>${h(box.name)}</h2><p class="muted">${h(box.address)} · ${h(authWords(v.auth))}</p></div><span class="tag ${cls}">${h(state)}</span></div>
    ${box.error ? `<div class="rd-block">${ico("alert", "sm")}${h(box.error)}</div>` : ""}
    <div data-signin>${s.microsoft ? signinMarkup(s.signin, now) : ""}</div>
    ${!v.smtp_host ? `<div class="info-line small">${ico("info", "sm")}<span>Sans serveur d'envoi, cette boîte ne fait que lire : sa voix attend qu'on lui en donne un.</span></div>` : ""}
    ${subTabs("boite", SUBS, active)}${la}${connexion}${mika}${partage}</form>`;
}

// ── Ajouter une boîte ────────────────────────────────────────────────

function stepMarkup(p: Provider): string {
  const preset = providerPreset(p);
  const address = row("Adresse", "", text("address", "", 'type="email" placeholder="toi@exemple.fr" autocomplete="email"'));
  const label = row("Nom court", "Comme elle l'appellera : « ta boîte Pro ».", text("label", "", 'placeholder="Pro, Perso…"'));
  if (p === "microsoft") {
    return `<div class="set-grid">${address}${label}
      ${row("Application Microsoft", "L'identifiant (client ID) de l'application inscrite dans Microsoft Entra — comptes personnels acceptés, flux de clients publics autorisé.", text("oauth_client_id", "", 'class="mono" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" spellcheck="false"'))}
      ${row("Annuaire Microsoft", "« consumers » pour Hotmail, Outlook.com, Live.", text("oauth_tenant", preset.oauth_tenant ?? "consumers", 'spellcheck="false"'))}</div>
      <div class="device" data-device hidden></div>`;
  }
  return `<div class="set-grid">${address}${label}
    ${row("Utilisateur", "Vide : l'adresse.", text("user", "", 'autocomplete="off"'))}
    ${row("Mot de passe", p === "gmail" ? "Un mot de passe d'application, pas celui de ton compte." : "", password("password", false))}
    ${row("Serveur IMAP", p === "davmail" ? "La passerelle DavMail, sur la machine de Mika." : "", `${text("imap_host", preset.imap_host ?? "", 'class="w-host" placeholder="imap.exemple.fr" spellcheck="false"')}${number("imap_port", preset.imap_port ?? 993, 'class="w-port" min="1" max="65535"')}`)}
    ${row("Serveur SMTP", "Vide : elle ne fera que lire.", `${text("smtp_host", preset.smtp_host ?? "", 'class="w-host" placeholder="smtp.exemple.fr" spellcheck="false"')}${number("smtp_port", preset.smtp_port ?? 587, 'class="w-port" min="1" max="65535"')}`)}</div>`;
}

/** Les valeurs d'une boîte nouvelle : le préréglage du fournisseur, ce qui est tapé, l'adresse pour utilisateur. */
export function newBoxValues(p: Provider, typed: Record<string, FormValue>): Partial<BoxValues> {
  const preset = providerPreset(p);
  const address = String(typed.address ?? "").trim();
  const values: Partial<BoxValues> = { ...preset, address, label: String(typed.label ?? "").trim() || address.split("@")[0] || "" };
  if (p === "microsoft") {
    return { ...values, user: address, oauth_client_id: String(typed.oauth_client_id ?? "").trim(), oauth_tenant: String(typed.oauth_tenant ?? "").trim() || "consumers" };
  }
  const smtpPort = Number(typed.smtp_port) || preset.smtp_port || 587;
  return {
    ...values,
    user: String(typed.user ?? "").trim() || address,
    password: String(typed.password ?? ""),
    imap_host: String(typed.imap_host ?? "").trim(),
    imap_port: Number(typed.imap_port) || preset.imap_port || 993,
    smtp_host: String(typed.smtp_host ?? "").trim(),
    smtp_port: smtpPort,
    smtp_security: securityFor(smtpPort, preset.smtp_security ?? "starttls"),
  };
}

/** Les fournisseurs qu'on peut lui proposer : la passerelle DavMail vit sur la machine de Mika, qu'une personne qui
 *  n'est pas opératrice ne fait pas joindre (l'API refuse la boucle locale et le réseau privé). */
export function providersFor(operator: boolean | undefined): typeof PROVIDERS {
  return operator === false ? PROVIDERS.filter(([k]) => k !== "davmail") : PROVIDERS;
}

async function addBoxModal(host: Host): Promise<void> {
  // qui elle est (opératrice ou non) décide des fournisseurs qu'on lui propose
  await store.me.load();
  let provider: Provider | null = null;
  let made = "";
  const el = openModal({
    title: "Ajouter un compte mail",
    size: "wide",
    body: `<div class="providers">${providersFor(store.me.value?.operator).map(([k, t, d, i]) => `<button type="button" class="provider" data-prov="${k}">${ico(i, "lg")}<b>${h(t)}</b><span>${h(d)}</span></button>`).join("")}</div>
      <form class="prov-step" data-step hidden autocomplete="off"></form>`,
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
      <button class="btn primary" type="button" data-ok disabled>${ico("plus", "sm")}Ajouter la boîte</button>`,
  });
  const step = el.querySelector<HTMLFormElement>("[data-step]")!;
  const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
  el.addEventListener("click", (e) => {
    const b = (e.target as Element).closest<HTMLElement>("[data-prov]");
    if (!b || made) return;
    provider = b.dataset.prov as Provider;
    el.querySelectorAll(".provider").forEach((x) => x.classList.toggle("on", x === b));
    step.hidden = false;
    step.innerHTML = stepMarkup(provider);
    ok.disabled = false;
    step.querySelector<HTMLInputElement>("input")?.focus();
  });
  const nonce = newNonce();
  const submit = async () => {
    if (!provider || ok.disabled) return;
    const typed = readForm(step);
    if (!String(typed.address ?? "").trim()) {
      showFieldErrors(step, { address: "son adresse" });
      return;
    }
    const bounds = rangeProblems(typed);
    if (Object.keys(bounds).length) {
      showFieldErrors(step, bounds);
      return;
    }
    ok.disabled = true;
    try {
      if (!made) {
        const done = await saveBox(newBoxValues(provider, typed), "", nonce);
        made = done.box;
        store.boxes.invalidate();
        // la boîte existe : un nouvel essai enregistre d'abord ce qu'on aura corrigé
        ok.innerHTML = `${ico("refresh", "sm")}Enregistrer et réessayer`;
      } else {
        // un essai précédent a échoué après la création : ce qu'on a corrigé ici (un client ID mal copié, l'annuaire)
        // s'enregistre avant de réessayer — sans clé d'envoi : ce n'est pas la création rejouée
        await saveBox(newBoxValues(provider, typed), made);
      }
      if (provider === "microsoft") {
        await connectMicrosoft(made);
        await followSignin(el, made, host);
        return;
      }
      const tested = await testBox(made).then((d) => ({ ok: true, message: d.message }), (err: unknown) => ({ ok: false, message: failureText(err) }));
      closeModal();
      toast(tested.ok ? `Boîte ajoutée. ${tested.message}` : `Boîte ajoutée, mais le test n'a pas abouti : ${tested.message}`, { ico: tested.ok ? "check" : "alert", duration: 4200 });
      host.go(`${TAB}/${encodeURIComponent(made)}`);
      void host.reload(store.boxes, store.rights);
    } catch (err) {
      ok.disabled = false;
      if (err instanceof ApiError && Object.keys(err.fields).length) {
        const rest = showFieldErrors(step, fieldErrors(err.fields));
        if (rest.length) toast(rest.join(" ; "), { ico: "alert", duration: 4200 });
      } else toastFailure(err);
    }
  };
  ok.addEventListener("click", () => void submit());
  step.addEventListener("submit", (e) => {
    e.preventDefault();
    void submit();
  });
}

/** Le code d'appareil d'une boîte Microsoft, dans la fenêtre : relu jusqu'à ce qu'elle soit connectée. Un échec rend
 *  le bouton : on corrige (le client ID, l'annuaire) et on réessaie, sans fermer la fenêtre. */
async function followSignin(modal: HTMLElement, box: string, host: Host): Promise<void> {
  const place = $<HTMLElement>("[data-device]", modal);
  const ok = $<HTMLButtonElement>("[data-ok]", modal);
  const again = () => {
    if (!ok) return;
    ok.hidden = false;
    ok.disabled = false;
  };
  if (ok) ok.hidden = true;
  for (let i = 0; i < 400 && modal.isConnected; i++) {
    let got: BoxSettings | null = null;
    try {
      got = await fetchBox(box);
    } catch (err) {
      if (place) {
        place.hidden = false;
        place.innerHTML = `${ico("alert")}<div><b>La connexion n'a pas pu se lire</b><p class="small">${h(failureText(err))}</p></div>`;
      }
      again();
      return;
    }
    const s = got.signin;
    if (s?.state === "connectee") {
      closeModal();
      toast("Boîte ajoutée et connectée à Microsoft.", { ico: "check" });
      host.go(`${TAB}/${encodeURIComponent(box)}`);
      void host.reload(store.boxes, store.boxSettings, store.rights);
      return;
    }
    if (place) {
      place.hidden = false;
      place.innerHTML = s?.state === "en_attente" && s.code
        ? deviceInner(s)
        : s?.error
          ? `${ico("alert")}<div><b>Pas encore connectée</b><p class="small">${h(s.error)}</p></div>`
          : `${ico("refresh")}<div><b>Microsoft prépare le code…</b></div><i class="spin" aria-hidden="true"></i>`;
    }
    if (s && s.state !== "en_attente" && s.error) {
      again();
      return;
    }
    await new Promise((r) => window.setTimeout(r, SIGNIN_EVERY_MS));
  }
  again();
}

// ── Les gestes ───────────────────────────────────────────────────────

async function remove(key: string, host: Host): Promise<void> {
  const box = ownBoxes().find((b) => b.key === key);
  const yes = await confirmModal({
    title: "Retirer cette boîte",
    text: `Retirer « ${box?.name ?? key} » ? Elle ne sera plus relevée ; ce qu'elle en a appris reste dans sa vie.`,
    ok: "Retirer",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await removeBox(key);
    toast(done.message || "Boîte retirée.", { ico: "trash" });
    host.go(TAB);
    await host.reload(store.boxes, store.shares, store.rights);
  } catch (err) {
    toastFailure(err);
  }
}

async function test(key: string, host: Host): Promise<void> {
  toast("Essai de la connexion…", { ico: "refresh", duration: 1600 });
  try {
    const done = await testBox(key);
    toast(done.message || "La connexion répond.", { ico: "check", duration: 4200 });
  } catch (err) {
    toast(failureText(err), { ico: "alert", duration: 5200 });
  }
  await host.reload(store.boxes);
}

async function signin(key: string, host: Host): Promise<void> {
  try {
    const done = await connectMicrosoft(key);
    toast(done.message || "Un code attend chez Microsoft.", { ico: "key" });
  } catch (err) {
    toastFailure(err);
  }
  await host.reload(store.boxSettings);
}

/** Le cadre de la connexion Microsoft dans la fiche de cette boîte-là (jamais celui d'une autre fiche). */
function signinPlace(root: ParentNode, key: string): HTMLElement | null {
  return root.querySelector<HTMLElement>(`[data-form="box"][data-box="${CSS.escape(key)}"] [data-signin]`);
}

/** Les boîtes dont on suit la connexion Microsoft : un suivi par boîte, qui n'écrit que dans sa propre fiche. */
const watching = new Set<string>();

/** Tant qu'un code Microsoft attend, la fiche relit où en est la connexion — sans toucher au reste du formulaire. Passée
 *  à la fiche d'une autre boîte, le suivi de celle-ci s'arrête (il reprend en rouvrant sa fiche). */
function watchSignin(root: HTMLElement, key: string, host: Host): void {
  const s = store.boxSettings.get(key).value?.signin;
  if (!s || s.state !== "en_attente" || watching.has(key)) return;
  watching.add(key);
  const tick = async () => {
    if (!signinPlace(root, key)) {
      watching.delete(key);
      return;
    }
    await store.boxSettings.get(key).load(true);
    // relu après la lecture : on a pu changer de fiche entre-temps
    const place = signinPlace(root, key);
    if (!place) {
      watching.delete(key);
      return;
    }
    const now = store.boxSettings.get(key).value?.signin ?? null;
    place.innerHTML = signinMarkup(now, Date.now());
    if (now?.state === "en_attente") window.setTimeout(() => void tick(), SIGNIN_EVERY_MS);
    else {
      watching.delete(key);
      if (now?.state === "connectee") {
        toast("Connectée à Microsoft.", { ico: "check" });
        // son état dans la fiche (« connectée », prête) : redessinée, sauf sous une saisie pas encore enregistrée
        void host.reload(store.boxes, store.boxSettings);
      }
    }
  };
  window.setTimeout(() => void tick(), SIGNIN_EVERY_MS);
}

/** La fiche de cette boîte, si elle est à l'écran (ses gestes l'enregistrent d'abord : `savedFirst`). */
function boxForm(key: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-form="box"][data-box="${CSS.escape(key)}"]`);
}

function boxMenu(anchor: HTMLElement, key: string, host: Host): void {
  openMenu(anchor, [
    {
      label: "Relever maintenant",
      icon: "refresh",
      action: () =>
        void pollBox(key).then(
          (d) => {
            toast(d.message || "Relève demandée.", { ico: "refresh" });
            void host.reload(store.boxes);
          },
          toastFailure,
        ),
    },
    { label: "Tester la connexion", icon: "plug", action: () => void test(key, host) },
    { label: "Partager…", icon: "users", action: () => void openShareModal(host, { kind: "mail", key }) },
    "sep",
    { label: "Retirer cette boîte", icon: "trash", danger: true, action: () => void remove(key, host) },
  ]);
}

/** Ce qui part au serveur : les nombres en nombres, les dossiers en liste, un secret vide jamais. */
export function boxChanges(changes: Record<string, FormValue>): Partial<BoxValues> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(changes)) {
    if ((k === "password" || k === "smtp_password") && !v) continue;
    if (k === "folders" && typeof v === "string") out[k] = v.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
    else if (k === "imap_port" || k === "smtp_port" || k === "since_days") out[k] = Number(v);
    else out[k] = v;
  }
  return out as Partial<BoxValues>;
}

export const mailPage: Page = {
  id: "comptes-mail",
  needs: () => [store.boxes],
  extras(item) {
    if (item) return ownBoxes().some((b) => b.key === item) ? [store.boxSettings.get(item), store.shares] : [store.shares];
    return [store.shares, ...ownBoxes().map((b) => store.boxSettings.get(b.key))];
  },
  view(item, host) {
    const now = Date.now();
    return item ? ficheView(item, host, now) : listView(now);
  },
  actions(item) {
    if (item && ownBoxes().some((b) => b.key === item)) {
      return `<button class="btn" type="button" data-act="box-test" data-box="${h(item)}">${ico("refresh", "sm")}<span class="lbl">Tester la connexion</span></button>`;
    }
    return `<button class="btn primary" type="button" data-act="box-add">${ico("plus", "sm")}<span class="lbl">Ajouter un compte</span></button>`;
  },
  act(name, el, item, host) {
    const key = el.dataset.box ?? item ?? "";
    // tester, connecter à Microsoft : la boîte telle qu'elle est enregistrée — ses modifications d'abord
    const saved = async (gesture: () => Promise<void>) => {
      if (await savedFirst(boxForm(key), host.bar)) await gesture();
    };
    if (name === "box-add") void addBoxModal(host);
    else if (name === "box-test") void saved(() => test(key, host));
    else if (name === "box-remove") void remove(key, host);
    else if (name === "box-ms") void saved(() => signin(key, host));
    else if (name === "box-share") void openShareModal(host, { kind: "mail", key });
    else if (name === "box-menu") boxMenu(el, key, host);
  },
  async save(form, changes, values, item, host) {
    const key = form.dataset.box ?? item ?? "";
    const sent = boxChanges(changes);
    if (!Object.keys(sent).length) return true;
    const bounds = rangeProblems(changes);
    if (Object.keys(bounds).length) {
      showFieldErrors(form, bounds);
      return false;
    }
    // la connexion change : ses secrets gardés se redonnent (le serveur refuserait sinon), dit sous leurs champs
    const kept = store.boxSettings.get(key).value?.secrets;
    const retype = kept
      ? secretsToRetype(changes, kept, String(values.auth ?? ""), { imap_host: values.imap_host, smtp_host: values.smtp_host })
      : {};
    if (Object.keys(retype).length) {
      const rest = showFieldErrors(form, retype);
      const which = Object.keys(retype).map((k) => (k === "smtp_password" ? "le mot de passe SMTP" : "le mot de passe")).join(" et ");
      toast(rest.length ? `La connexion a changé : ${rest.join(" ; ")}` : `La connexion a changé : redonne ${which} (un secret gardé ne part jamais vers un autre serveur).`, { ico: "alert", duration: 5200 });
      return false;
    }
    try {
      const done = await saveBox(sent, key);
      toast(done.message || "Enregistré.", { ico: "check" });
      await host.reload(store.boxes, store.boxSettings, store.rights);
      return true;
    } catch (err) {
      // un champ refusé (un serveur hors d'Internet, un mot de passe à redonner, une borne) : dit sous son champ
      if (err instanceof ApiError && Object.keys(err.fields).length) {
        const rest = showFieldErrors(form, fieldErrors(err.fields));
        toast(rest.length ? `${err.message} ${rest.join(" ; ")}` : err.message, { ico: "alert", duration: 4200 });
      } else toastFailure(err);
      return false;
    }
  },
  after(root, item, host) {
    if (item) watchSignin(root, item, host);
  },
  search() {
    return ownBoxes().map((b) => ({ group: "Paramètres", title: `Boîte « ${b.name} »`, sub: b.address, icon: "mail" as const, route: `${TAB}/${encodeURIComponent(b.key)}` }));
  },
};
