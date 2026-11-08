/**
 * Paramètres › Services MCP (ADR 0192) : les services qu'elle a branchés — distants, par une adresse https —, à elle
 * seule. En brancher un (il naît avec une seule ligne d'accès, la sienne), le tester, régler chacun de ses outils
 * (coupé, il lit, il agit : ADR 0129 — un outil nouveau ou changé attend son choix), le régler, le retirer ; ses lignes
 * d'accès, en lecture. Ceux qu'on lui partage (ADR 0188), en lecture : « Partagé avec toi ».
 */
import { ApiError } from "../../api/moi";
import {
  chooseTools,
  plugService,
  removeService,
  saveService,
  testService,
  type AccessLine,
  type ReceivedService,
  type Service,
  type ServiceValues,
  type ToolChoice,
} from "../../api/mcp";
import { h } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { area, backLink, readForm, row, savedFirst, section, seg, showFieldErrors, subTabs, text, toggle } from "./form";
import { confirmModal, failureText, newNonce, toastFailure } from "./kit";
import type { Host, Page } from "./page";
import { openShareModal } from "./shares";
import * as store from "./store";
import { CHOICES, fieldErrors, ofName, serviceNameProblem, servedOf, shareWords, stateWords, urlProblem, type FormValue } from "./words";

const TAB = "#parametres/mcp";
/** Les bornes de l'API pour brancher un service (`app/moi/mcp.py`, en caractères) : au-delà, elle refuse. */
const MCP_LIMITS = { purpose: 1024, url: 500, headers: 8000 } as const;
const SUBS = [["service", "Le service"], ["outils", "Ses outils"], ["acces", "Accès"]] as const;
/** Un choix d'outil dans le formulaire : `tool:<son nom sur le serveur>`. */
const TOOL = "tool:";

function list(): Service[] {
  return store.services.value?.items ?? [];
}

/** Ceux qu'on lui partage. */
function received(): ReceivedService[] {
  return store.services.value?.received ?? [];
}

/** Qui une ligne désigne : « toi » pour la tienne — l'API le dit (`mine`), jamais un nom comparé (deux personnes
 *  peuvent porter le même, et le nom d'une identité n'est pas toujours celui du compte). */
export function whoWords(a: AccessLine): string {
  return a.mine ? "toi" : a.who || "tout le monde";
}

/** Avec qui il est partagé : ses lignes qui ne sont pas la tienne. */
export function sharedWith(s: Service): string {
  return s.access.filter((a) => a.who && !a.mine).map((a) => a.who).join(", ");
}

const LEVEL_CLS: Record<string, string> = { seule: "ok", carte: "warn", toi: "warn", non: "off" };

// ── La liste ─────────────────────────────────────────────────────────

function listView(): string {
  const items = list();
  const plugged = store.services.value?.plugged !== false;
  const table = items.length
    ? `<table class="tbl"><thead><tr><th>Service</th><th>Adresse</th><th>Authentification</th><th>État</th><th>Outils servis</th><th>Partagé avec</th><th></th></tr></thead><tbody>${items
        .map((s) => {
          const [cls, state] = stateWords(s.state);
          const served = servedOf(s.tools);
          return `<tr><td><div class="row">${ico("server", "sm")}<div><b>${h(s.name)}</b>${s.purpose ? `<div class="tiny muted">${h(s.purpose)}</div>` : ""}</div></div></td>
            <td class="small mono">${h(s.url)}</td><td class="small">${s.headers ? "en-têtes secrets" : "aucune"}</td>
            <td><span class="tag ${cls}">${h(state)}</span></td>
            <td class="num nowrap">${served.served} / ${served.total}${served.review ? ` <span class="tag warn">${served.review} à regarder</span>` : ""}</td>
            <td class="small">${h(sharedWith(s) || "—")}</td>
            <td class="actions"><button class="btn xs" type="button" data-act="mcp-test" data-name="${h(s.name)}">Tester</button> <a class="btn xs" href="${TAB}/${encodeURIComponent(s.name)}">Régler</a></td></tr>`;
        })
        .join("")}</tbody></table>`
    : `<div class="empty-card">${ico("plug")}<div><b>Aucun service branché</b><p class="small muted">Un service MCP distant (une adresse https) donne à Mika des outils de plus : ils ne servent qu'à toi, et à qui tu les partages.</p></div>
        <button class="btn sm primary" type="button" data-act="mcp-plug">${ico("plus", "sm")}Brancher un service</button></div>`;
  return `<div class="set-page">
    <p class="lede">Les services MCP que tu as branchés. Mika s'en sert pour toi, et pour les personnes avec qui tu les partages ; chaque outil se choisit un par un.</p>
    ${plugged ? "" : `<div class="info-line small">${ico("info", "sm")}<span>Les services ne sont pas branchés sur ce serveur.</span></div>`}
    ${table}
    <p class="small muted tbl-help">Un service que tu branches ici est distant ; lancer un service sur la machine de Mika reste aux opérateurs, dans la console. Ceux de Mika (le web…) n'apparaissent pas ici : <a href="#outils/services">Outils › Services</a>.</p>
    ${receivedList()}
  </div>`;
}

// ── Partagé avec toi ─────────────────────────────────────────────────

/** Ce que son niveau lui ouvre, en une phrase. */
function receivedSentence(r: ReceivedService): string {
  const owner = r.owner_name || "Son propriétaire";
  const what = r.level === "servir"
    ? "Mika s'en sert pour toi : ses outils qui lisent, et ceux qui agissent."
    : "Mika s'en sert pour toi, seulement ses outils qui lisent.";
  return `${owner} te l'a ouvert : ${shareWords(r.level).toLowerCase()}. ${what} Seul son propriétaire le règle.`;
}

function receivedCard(r: ReceivedService): string {
  const [cls, state] = stateWords(r.state);
  const tools = r.tools.length ? `${r.tools.length} outil${r.tools.length > 1 ? "s" : ""} servi${r.tools.length > 1 ? "s" : ""}` : "aucun outil servi";
  return `<div class="acc-card"><span class="acc-ico c7">${ico("lock")}</span>
    <div class="grow"><div class="row wrap"><b>${h(r.name)}</b><span class="muted">${h(ofName(r.owner_name || "son propriétaire"))}</span><span class="tag ${cls}">${h(state)}</span><span class="tag">${h(tools)}</span></div>
      ${r.purpose ? `<p class="small text-2">${h(r.purpose)}</p>` : ""}<p class="small muted">${h(receivedSentence(r))}</p></div>
    <a class="btn sm" href="${TAB}/${encodeURIComponent(r.name)}">Voir</a></div>`;
}

export function receivedList(items: readonly ReceivedService[] = received()): string {
  if (!items.length) return "";
  return `<h2 class="section-title shared-title">Partagé avec toi <span class="cnt">${items.length}</span></h2>
    <div class="acc-cards">${items.map(receivedCard).join("")}</div>`;
}

/** La fiche d'un service qu'on lui partage, en lecture : ses outils servis, et ce que Mika en fait pour elle. */
export function receivedFiche(r: ReceivedService): string {
  const [cls, state] = stateWords(r.state);
  const forYou = (choice: string) => (choice === "action" ? r.line.act_words : r.line.read_words) || "non";
  const rows = r.tools
    .map((t) => `<tr><td class="mono small">${h(t.remote)}</td><td class="small">${h(t.description || "—")}</td>
      <td><span class="tag accent">${h(CHOICES.find(([k]) => k === t.choice)?.[1] ?? t.choice)}</span></td><td class="small">${h(forYou(t.choice))}</td></tr>`)
    .join("");
  const table = rows
    ? `<table class="tbl"><thead><tr><th>Outil</th><th>Ce qu'il fait</th><th>Il</th><th>Pour toi, elle</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<p class="small muted">Son propriétaire n'en sert encore aucun outil.</p>`;
  return `<div class="set-page">${backLink(TAB, "Services MCP")}
    <div class="fiche-head"><span class="acc-ico c7">${ico("lock")}</span><div class="grow"><h2>${h(r.name)}</h2><p class="muted">${h(`Service ${ofName(r.owner_name || "son propriétaire")}`)}</p></div><span class="tag ${cls}">${h(state)}</span></div>
    ${r.purpose ? `<p class="lede">${h(r.purpose)}</p>` : ""}
    <div class="info-line small">${ico("info", "sm")}<span>${h(receivedSentence(r))} Ce qu'elle en lit, elle le garde : ${h(r.line.keep_words || "rien")}.</span></div>
    ${section("Ses outils servis", `<div class="set-row full">${table}</div>`, { single: true })}</div>`;
}

// ── La fiche ─────────────────────────────────────────────────────────

/**
 * Ses outils, chacun réglable ici : coupé, il lit, ou il agit (ADR 0129). Un outil déjà choisi montre son choix ; un
 * outil nouveau ou changé (suspendu tant qu'on ne l'a pas regardé) n'en montre pas — le choisir, même comme avant, le
 * décide. N'en part que ce qui a bougé (`splitChanges`).
 */
export function toolsTable(s: Service): string {
  if (!s.tools.length) {
    return `<div class="set-row full"><p class="small muted">${s.state === "connecte" ? "Ce service ne propose aucun outil." : "Ses outils se lisent quand il répond : teste-le."}</p></div>`;
  }
  const rows = s.tools
    .map((t) => {
      const waiting = t.new || t.changed;
      const before = CHOICES.find(([k]) => k === t.choice)?.[1];
      const state = t.new
        ? '<span class="tag info">nouveau</span>'
        : t.changed
          ? `<span class="tag warn">changé</span>${before ? `<div class="tiny muted">avant : ${h(before.toLowerCase())}</div>` : ""}`
          : t.choice === "non"
            ? '<span class="tag">coupé</span>'
            : '<span class="tag ok">servi</span>';
      const choice = seg(`${TOOL}${t.remote}`, CHOICES, waiting ? "" : t.choice);
      return `<tr><td class="mono small">${h(t.remote)}${t.name ? `<div class="tiny muted">${h(t.name)}</div>` : ""}</td><td class="small">${h(t.description || "—")}</td><td>${state}</td><td>${choice}</td></tr>`;
    })
    .join("");
  return `<div class="set-row full"><table class="tbl"><thead><tr><th>Outil</th><th>Ce qu'il fait</th><th>État</th><th>Ton choix</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="small muted tbl-help">Chaque outil se règle ici : coupé, il lit, ou il agit (ce qu'il change ailleurs, Mika te le demande d'abord). Un outil nouveau ou changé ne sert pas tant que tu ne l'as pas choisi.</p></div>`;
}

function accessTable(s: Service): string {
  const lv = (code: string, words: string) => `<span class="lv ${LEVEL_CLS[code] ?? "off"}">${h(words)}</span>`;
  const rows = s.access
    .map((a, i) => `<tr><td class="muted">${i + 1}</td><td>${h(whoWords(a))}${a.who && !a.mine ? ' <span class="tag accent">partage</span>' : ""}</td><td class="small">${h(a.when || "toujours")}</td>
      <td>${lv(a.read, a.read_words)}</td><td>${lv(a.act, a.act_words)}</td><td class="small">${h(a.keep_words)}</td></tr>`)
    .join("");
  const d = s.default;
  const closed = !d || (d.read === "non" && d.act === "non");
  const def = `<tr class="def"><td class="muted">—</td><td><b>Par défaut</b></td><td colspan="4" class="small">${closed ? "fermé : personne d'autre" : h(`il lit : ${d!.read_words} · il agit : ${d!.act_words} · ${d!.keep_words}`)}</td></tr>`;
  return `<div class="set-row full"><p class="small text-2">Ses lignes d'accès, lues de haut en bas. Un service que tu branches n'a que la tienne ; le partager ajoute une ligne pour la personne.</p>
    <table class="tbl"><thead><tr><th>#</th><th>Qui</th><th>Quand</th><th>Il lit</th><th>Il agit</th><th>Ce qu'elle en garde</th></tr></thead><tbody>${rows}${def}</tbody></table>
    <div class="row tbl-help"><button class="btn xs" type="button" data-act="mcp-share" data-name="${h(s.name)}">${ico("user-plus", "xs")}Partager avec quelqu'un</button><a class="btn xs ghost" href="#parametres/partages">Gérer les partages</a></div></div>`;
}

function ficheView(name: string, host: Host): string {
  const s = list().find((x) => x.name === name);
  if (!s) {
    const shared = received().find((x) => x.name === name);
    if (shared) return receivedFiche(shared);
    return `<div class="set-page">${backLink(TAB, "Services MCP")}<div class="empty">${ico("server")}<b>Service introuvable</b><p>Il n'est pas parmi les tiens, ni parmi ceux qu'on te partage.</p></div></div>`;
  }
  const [cls, state] = stateWords(s.state);
  const active = host.sub("mcp", "service");
  const sub = (id: string) => ({ sub: id, hidden: active !== id });
  const problem = s.state === "erreur" || s.state === "panne" || s.state === "incomplet";
  const service = section(
    "Le service",
    row("À quoi il lui sert", "Ce qu'elle lit pour savoir quand s'en servir.", text("purpose", s.purpose, `maxlength="${MCP_LIMITS.purpose}"`)) +
      row("Quand y penser", "Facultatif : quand elle devrait y penser d'elle-même.", area("when_to_use", s.when_to_use, 2, `maxlength="${MCP_LIMITS.purpose}"`)) +
      row("Adresse", "L'adresse MCP « streamable HTTP » du service, en https.", text("url", s.url, `class="mono" spellcheck="false" maxlength="${MCP_LIMITS.url}"`)) +
      row("En-têtes secrets", s.headers ? "Gardés, jamais réaffichés : laisse vide pour ne pas les changer." : "Un par ligne (Authorization: Bearer …), s'il en demande.", area("secret_headers", "", 2, `class="mono" spellcheck="false" maxlength="${MCP_LIMITS.headers}" placeholder="${s.headers ? "gardés — vide : inchangés" : "Authorization: Bearer …"}"`)) +
      row("Actif", "Décoché : plus joint ni offert ; ses réglages restent.", toggle("enabled", s.enabled)) +
      row("Retirer ce service", "Il n'est plus joint ni offert ; ce qu'elle y a lu reste dans sa vie.", `<button class="btn sm danger" type="button" data-act="mcp-remove" data-name="${h(s.name)}">${ico("trash", "sm")}Retirer</button>`),
    sub("service"),
  );
  return `<form class="set-page" data-form="mcp" data-name="${h(s.name)}" autocomplete="off">${backLink(TAB, "Services MCP")}
    <div class="fiche-head"><span class="acc-ico c0">${ico("server")}</span><div class="grow"><h2>${h(s.name)}</h2><p class="muted mono small">${h(s.url)}</p></div><span class="tag ${cls}">${h(state)}</span></div>
    ${problem && s.detail ? `<div class="rd-block">${ico("alert", "sm")}${h(s.detail)}</div>` : ""}
    ${subTabs("mcp", SUBS, active)}${service}
    ${section("Ses outils", toolsTable(s), { ...sub("outils"), single: true })}
    ${section("Accès", accessTable(s), { ...sub("acces"), single: true })}</form>`;
}

// ── Les gestes ───────────────────────────────────────────────────────

/** La fiche de ce service, si elle est à l'écran. */
function serviceForm(name: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-form="mcp"][data-name="${CSS.escape(name)}"]`);
}

async function test(name: string, host: Host): Promise<void> {
  toast("Essai du service…", { ico: "refresh", duration: 1600 });
  try {
    const got = await testService(name);
    toast(got.message || (got.ok ? "Il répond." : "Il ne répond pas."), { ico: got.ok ? "check" : "alert", duration: 5200 });
  } catch (err) {
    toastFailure(err);
  }
  await host.reload(store.services, store.rights);
}

async function remove(name: string, host: Host): Promise<void> {
  const yes = await confirmModal({
    title: "Retirer ce service",
    text: `Retirer « ${name} » ? Il ne sera plus joint ni offert, à toi comme à qui tu l'as partagé ; ce qu'elle y a lu reste dans sa vie.`,
    ok: "Retirer",
    danger: true,
  });
  if (!yes) return;
  try {
    const done = await removeService(name);
    toast(done.message || "Service retiré.", { ico: "trash" });
    host.go(TAB);
    await host.reload(store.services, store.shares, store.rights);
  } catch (err) {
    toastFailure(err);
  }
}

function plugModal(host: Host): void {
  const el = openModal({
    title: "Brancher un service MCP",
    size: "wide",
    body: `<form class="set-grid" data-plug autocomplete="off">
      ${row("Son nom", "Court : des minuscules, chiffres et _ (il entre dans le nom de ses outils).", text("name", "", 'class="mono" placeholder="agenda_club" spellcheck="false" maxlength="24"'))}
      ${row("À quoi il lui sert", "Elle le lit pour savoir quand s'en servir.", text("purpose", "", `placeholder="Les sorties et les inscriptions de l'association" maxlength="${MCP_LIMITS.purpose}"`))}
      ${row("Adresse", "Un serveur MCP distant, en https (« streamable HTTP »).", text("url", "", `class="mono" placeholder="https://…/mcp" spellcheck="false" maxlength="${MCP_LIMITS.url}"`))}
      ${row("En-têtes secrets", "Facultatif : un par ligne, gardés scellés, jamais réaffichés.", area("headers", "", 2, `class="mono" placeholder="Authorization: Bearer …" spellcheck="false" maxlength="${MCP_LIMITS.headers}"`))}
      ${row("Quand y penser", "Facultatif.", text("when_to_use", "", `maxlength="${MCP_LIMITS.purpose}"`))}</form>
      <div class="info-line small">${ico("info", "sm")}<span>Il sera à toi : une seule ligne d'accès, la tienne. Ses outils arrivent coupés : tu les choisis un par un. Pour qu'un autre s'en serve, partage-le.</span></div>`,
    foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("plug", "sm")}Brancher et tester</button>`,
  });
  const form = el.querySelector<HTMLFormElement>("[data-plug]")!;
  const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
  const nonce = newNonce();
  const submit = async () => {
    const v = readForm(form);
    const name = String(v.name ?? "").trim().toLowerCase();
    const url = String(v.url ?? "").trim();
    const errors: Record<string, string> = {};
    const bad = serviceNameProblem(name);
    if (bad) errors.name = bad;
    const badUrl = urlProblem(url);
    if (badUrl) errors.url = badUrl;
    if (Object.keys(errors).length) {
      showFieldErrors(form, errors);
      return;
    }
    ok.disabled = true;
    try {
      const done = await plugService({ name, url, purpose: String(v.purpose ?? "").trim(), headers: String(v.headers ?? ""), when_to_use: String(v.when_to_use ?? "") }, nonce);
      closeModal();
      const tested = await testService(done.name).catch((err: unknown) => ({ ok: false, message: failureText(err) }));
      toast(tested.ok ? `${done.message} ${tested.message}` : `Branché, mais il ne répond pas encore : ${tested.message}`, { ico: tested.ok ? "check" : "alert", duration: 5200 });
      host.setSub("mcp", "outils");
      host.go(`${TAB}/${encodeURIComponent(done.name)}`);
      await host.reload(store.services, store.rights);
    } catch (err) {
      ok.disabled = false;
      if (err instanceof ApiError && Object.keys(err.fields).length) showFieldErrors(form, fieldErrors(err.fields));
      else toastFailure(err);
    }
  };
  ok.addEventListener("click", () => void submit());
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    void submit();
  });
}

/** Ce qui part au serveur : les choix d'outils d'un côté, les réglages du service de l'autre. */
export function splitChanges(changes: Record<string, FormValue>): { choices: Record<string, ToolChoice>; values: Partial<ServiceValues> } {
  const choices: Record<string, ToolChoice> = {};
  const values: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(changes)) {
    if (k.startsWith(TOOL)) {
      if (v === "non" || v === "lecture" || v === "action") choices[k.slice(TOOL.length)] = v;
    } else if (k === "secret_headers" && !v) continue;
    else values[k] = v;
  }
  return { choices, values: values as Partial<ServiceValues> };
}

export const mcpPage: Page = {
  id: "mcp",
  needs: () => [store.services],
  view(item, host) {
    return item ? ficheView(item, host) : listView();
  },
  actions(item) {
    if (item && list().some((s) => s.name === item)) {
      return `<button class="btn" type="button" data-act="mcp-test" data-name="${h(item)}">${ico("refresh", "sm")}<span class="lbl">Tester</span></button>`;
    }
    return `<button class="btn primary" type="button" data-act="mcp-plug">${ico("plus", "sm")}<span class="lbl">Brancher un service</span></button>`;
  },
  act(name, el, item, host) {
    const service = el.dataset.name ?? item ?? "";
    if (name === "mcp-plug") plugModal(host);
    // un service dont on vient de changer l'adresse se teste à sa nouvelle adresse : enregistrée d'abord
    else if (name === "mcp-test") void (async () => {
      if (await savedFirst(serviceForm(service), host.bar)) await test(service, host);
    })();
    else if (name === "mcp-remove") void remove(service, host);
    else if (name === "mcp-share") void openShareModal(host, { kind: "mcp", key: service });
  },
  async save(form, changes, _values, item, host) {
    const name = form.dataset.name ?? item ?? "";
    const { choices, values } = splitChanges(changes);
    try {
      const said: string[] = [];
      if (Object.keys(values).length) said.push((await saveService(name, values)).message);
      if (Object.keys(choices).length) said.push((await chooseTools(name, choices)).message);
      toast(said.filter(Boolean).join(" ") || "Enregistré.", { ico: "check" });
      await host.reload(store.services, store.rights);
      return true;
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) showFieldErrors(form, fieldErrors(err.fields));
      else toastFailure(err);
      return false;
    }
  },
  search() {
    return [...list(), ...received()].map((s) => ({ group: "Paramètres", title: `Service « ${s.name} »`, sub: s.purpose, icon: "server" as const, route: `${TAB}/${encodeURIComponent(s.name)}` }));
  },
};
