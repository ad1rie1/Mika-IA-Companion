/**
 * Le rendu de Contacts (ADR 0298), celui de la maquette validée (`frontendv2/maquette/ecrans/contacts.js`), nourri par
 * l'API par personne (`protocole-moi.md` § 12) : la liste (la recherche, Tous / Personnes / Organisations, d'où vient
 * chacun) et la fiche (ce qui l'identifie, ce que Mika en sait, où vous vous croisez, ses personnes, l'oublier). Pur :
 * des chaînes HTML, tout texte venu d'ailleurs échappé. L'écran ne dit que ce que le serveur sert : jamais de qui
 * d'autre c'est le contact (il ne le sait pas), jamais la clé d'un contact du téléphone (il ne la reçoit pas).
 */
import type { ContactFact, ContactKind, ContactLine, ContactPlace, ContactSheet, ContactSource, ContactsPage } from "../../api/contacts";
import { CONTACTS_LIMITS } from "../../api/contacts";
import { h } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { dayAndClock, shortWhen } from "../chat/markup";
import { avatar, writeToHash } from "../mail/format";

export const ID = "contacts";

/** Les choix de la liste : la sorte qu'on montre (`""` : tous). */
export const KINDS: readonly (readonly [ContactKind | "", string, keyof ContactsPage["counts"]])[] = [
  ["", "Tous", "all"],
  ["person", "Personnes", "person"],
  ["org", "Organisations", "org"],
];

/** L'icône d'une source (une étiquette de la liste, un fait de la fiche). */
const SOURCE_ICONS: Record<string, IconName> = { teams: "teams", mail: "mail", whatsapp: "chat", sms: "phone", phone: "phone", told: "sparkle" };
/** L'icône d'une sorte d'identifiant. */
const KIND_ICONS: Record<string, IconName> = {
  email: "mail", teams: "teams", phone: "phone", domain: "globe", company: "users", tenant: "teams", phone_app: "chat",
};
/** Une conversation Teams, en mots. */
const TEAMS_KINDS: Record<string, string> = { dm: "tête-à-tête", group: "groupe", channel: "canal", meeting: "réunion" };

// ── Les adresses ─────────────────────────────────────────────────────

export function contactHash(id: number): string {
  return `#${ID}/${id}`;
}

/** L'objet de la route (`#contacts/<n°>`) : un numéro de fiche, sinon `null`. */
export function routeId(item: string | null): number | null {
  if (!item || !/^\d{1,15}$/.test(item)) return null;
  const id = Number(item);
  return id > 0 ? id : null;
}

/** Une conversation Teams (`#teams/discussions/<clé>`, la route de l'écran Teams : `teams.ts::conversationHash`). */
export function teamsHash(key: string): string {
  return `#teams/discussions/${encodeURIComponent(key)}`;
}

/** Une conversation du téléphone (`#telephone/messages/<appli>|<fil>`). */
export function phoneHash(key: string): string {
  return `#telephone/messages/${encodeURIComponent(key)}`;
}

/** Un mail (`#mail/messages/<réf>`) ; sans réf, la liste du courrier. */
export function mailHash(ref: string): string {
  return ref ? `#mail/messages/${encodeURIComponent(ref)}` : "#mail/messages";
}

/** Écrire (Mail, la fenêtre d'un mail nouveau, le destinataire posé). */
export function writeHash(s: Pick<ContactSheet, "write">): string {
  return s.write ? writeToHash(s.write.address, s.write.name) : "";
}

// ── Les mots ─────────────────────────────────────────────────────────

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n > 1 ? many : one}`;
}

/** Ce qu'on sait de lui en une ligne : son poste et son service. */
export function idea(c: Pick<ContactLine, "title" | "department">): string {
  return [c.title, c.department].filter(Boolean).join(" · ");
}

/** Ce que dit une fiche reliée : « parle aussi à Mika » s'il lui a écrit, sinon « a un compte » (vide : pas reliée). */
export function linkedWords(c: { linked: boolean; talks?: boolean }): string {
  return c.linked ? (c.talks ? "parle aussi à Mika" : "a un compte") : "";
}

/** La seconde ligne d'une entrée : « Organisation », son organisation, ce qu'on sait de lui, sinon un identifiant. */
export function lineSub(c: ContactLine): string {
  if (c.kind === "org") return c.members ? `Organisation · ${plural(c.members, "personne", "personnes")}` : "Organisation";
  return c.organisation?.name || idea(c) || c.identifiers[0]?.value || linkedWords(c);
}

/** Une source en étiquette : son icône, son nombre (rien pour un profil seul). */
export function sourceChip(s: ContactSource): string {
  const n = s.count ? String(s.count) : "";
  return `<span class="cx-src" title="${h(s.label)}${n ? ` · ${n}` : ""}">${ico(SOURCE_ICONS[s.source] ?? "user", "xs")}${h(n)}</span>`;
}

/** Une source dans la ligne des faits de la fiche (« Teams · 64 », « Personnel · 23 »). */
export function sourceFact(s: ContactSource): string {
  return `<span>${ico(SOURCE_ICONS[s.source] ?? "user", "sm")}${h(s.label)}${s.count ? ` · ${s.count}` : ""}</span>`;
}

/** Le rond d'un contact : sa photo de Teams quand le serveur en a une (ADR 0300), sinon ses initiales ; une
 *  organisation, son carré. */
export function contactAvatar(c: Pick<ContactLine, "id" | "kind" | "name" | "photo">, size: string): string {
  const org = c.kind === "org";
  return avatar(c.name, `${size}${org ? " sq" : ""}`, `contact:${c.id}`, org ? "" : c.photo ?? "");
}

/** Ce qu'on cherche, côté client : rien (le serveur cherche, dans ce que tes comptes en montrent). Borné comme l'API. */
export function clippedQuery(q: string): string {
  return q.slice(0, CONTACTS_LIMITS.search);
}

/** La palette : la sorte d'un contact en mots. */
export function paletteSub(c: ContactLine): string {
  return lineSub(c) || (c.kind === "org" ? "Organisation" : "Contact");
}

// ── La liste ─────────────────────────────────────────────────────────

export function contactItem(c: ContactLine, selected: boolean, now: number): string {
  const sub = lineSub(c);
  return `<button class="li" type="button" data-cx="${c.id}" aria-selected="${selected}">${contactAvatar(c, "sm")}
    <span class="li-main"><span class="li-top"><span class="li-title">${h(c.name)}</span><time>${h(shortWhen(c.last, now))}</time></span>
    <span class="li-snip cx-snip">${sub ? `<span class="cx-org">${h(sub)}</span>` : ""}${c.sources.map(sourceChip).join("")}</span></span></button>`;
}

export interface ListView {
  q: string;
  kind: ContactKind | "";
  page: ContactsPage | null;
  items: readonly ContactLine[];
  selected: number | null;
  loading: boolean;
  error: string;
  now: number;
}

/** La recherche et les choix de sorte, avec leurs nombres. */
export function listTools(v: Pick<ListView, "q" | "kind" | "page">): string {
  const counts = v.page?.counts;
  const seg = KINDS.map(([k, label, count]) => {
    const n = counts ? `<span class="cnt">${counts[count]}</span>` : "";
    return `<button type="button" data-cxsorte="${k}" aria-pressed="${v.kind === k}">${label} ${n}</button>`;
  }).join("");
  return `<div class="pane-head"><label class="search grow">${ico("search", "sm")}<input type="search" placeholder="Un nom, un e-mail, un numéro…" data-cxq value="${h(v.q)}" aria-label="Chercher un contact" maxlength="${CONTACTS_LIMITS.search}" autocomplete="off"></label></div>
    <div class="ml-tools"><div class="seg" role="group" aria-label="Sorte">${seg}</div></div>`;
}

export function listBody(v: ListView): string {
  if (!v.page) {
    return v.error
      ? `<div class="empty">${ico("alert")}<b>Impossible de lire tes contacts</b><p>${h(v.error)}</p><button class="btn sm" type="button" data-cx-relire>Réessayer</button></div>`
      : `<div class="empty">${ico("refresh")}<b>Chargement…</b><p>Tes contacts se lisent.</p></div>`;
  }
  if (!v.items.length) {
    if (v.q.trim()) return `<div class="empty">${ico("search")}<b>Personne</b><p>Aucun contact ne correspond à « ${h(v.q.trim())} ».</p></div>`;
    if (v.kind === "org") return `<div class="empty">${ico("users")}<b>Aucune organisation</b><p>Une organisation naît du domaine d'une adresse ou d'un profil Teams.</p></div>`;
    return `<div class="empty">${ico("users")}<b>Aucun contact</b><p>Ceux que Mika lit dans tes comptes Teams, tes boîtes, ton téléphone, ou dont tu lui parles, arrivent ici.</p></div>`;
  }
  const more = v.page.total > v.items.length
    ? `<div class="cx-more"><button class="btn sm" type="button" data-cx-plus${v.loading ? " disabled" : ""}>${v.loading ? "Chargement…" : `Afficher les suivants (${v.page.total - v.items.length})`}</button></div>`
    : "";
  return v.items.map((c) => contactItem(c, c.id === v.selected, v.now)).join("") + more;
}

// ── La fiche ─────────────────────────────────────────────────────────

/** Une conversation, une boîte, où vous vous croisez : l'icône, le titre, le détail, l'adresse qui l'ouvre. */
export function placeParts(p: ContactPlace, name: string, now: number): { icon: IconName; title: string; detail: string; href: string } {
  if (p.source === "teams") {
    const kind = TEAMS_KINDS[p.kind] ?? "conversation";
    return { icon: "teams", title: p.title || (p.kind === "dm" ? name : "Conversation Teams"), detail: `${kind} · ${plural(p.count, "message", "messages")}`, href: teamsHash(p.conversation) };
  }
  if (p.source === "mail") {
    const when = dayAndClock(p.last, now);
    return { icon: "mail", title: p.subject || plural(p.count, "mail", "mails"), detail: [p.box_name, p.subject && p.count ? plural(p.count, "mail", "mails") : "", when].filter(Boolean).join(" · "), href: mailHash(p.ref) };
  }
  const where = [p.app_name, p.group ? "groupe" : "", plural(p.count, "message", "messages")].filter(Boolean).join(" · ");
  return { icon: p.app === "whatsapp" || p.app === "whatsapp_business" ? "chat" : "phone", title: p.title || name, detail: where, href: phoneHash(p.conversation) };
}

/** D'où vient ce que Mika en sait, en une phrase. */
export function privacyNote(s: Pick<ContactSheet, "name" | "privacy">): string {
  return s.privacy === "mine"
    ? `Ce que Mika sait de ${s.name} vient de tes comptes et de ce que tu lui as dit : elle n'en parle qu'à toi.`
    : `Ce que Mika sait de ${s.name} vient aussi d'un compte qu'on te partage ou d'un des siens : d'autres que toi peuvent le lire.`;
}

function identifiersBlock(s: ContactSheet): string {
  if (!s.identifiers.length) {
    return `<p class="small muted">${s.kind === "org" ? "Rien d'autre que son nom." : "Aucun moyen de communication : tu lui en as seulement parlé."}</p>`;
  }
  return `<ul class="ct-ways cx-ways">${s.identifiers.map((i) => {
    const shown = i.value || i.name || "hors de ton carnet";
    const where = [...i.where, i.generic ? "sans personne derrière" : ""].filter(Boolean).join(", ");
    return `<li>${ico(KIND_ICONS[i.kind] ?? "user", "sm")}<span class="muted">${h(i.label)}</span><span class="cx-val"><b>${h(shown)}</b>${where ? `<small>${h(where)}</small>` : ""}</span></li>`;
  }).join("")}</ul>`;
}

function membersBlock(s: ContactSheet, now: number): string {
  if (s.kind !== "org" || !s.members.length) return "";
  const rest = s.members_total - s.members.length;
  return `<h4 class="rd-h4">Ses personnes parmi tes contacts</h4><div class="cx-membres">${s.members.map((m) => `<button class="li" type="button" data-cx="${m.id}">${contactAvatar({ id: m.id, kind: "person", name: m.name, photo: m.photo }, "sm")}<span class="li-main"><span class="li-top"><span class="li-title">${h(m.name)}</span><time>${h(shortWhen(m.last, now))}</time></span><span class="li-snip">${h(idea(m) || linkedWords(m))}</span></span></button>`).join("")}</div>
    ${rest > 0 ? `<p class="small muted">et ${plural(rest, "autre", "autres")}</p>` : ""}`;
}

/** D'où vient un fait qu'elle a tiré de ses messages, et sa confiance : « d'après ses messages dans Teams · en
 * tête-à-tête · sûre à 80 % ». */
export function noteSource(f: ContactFact): string {
  const sure = typeof f.confidence === "number" ? `sûre à ${Math.round(f.confidence * 100)} %` : "";
  return [f.from ? `d'après ${f.from}` : "", f.place ?? "", sure].filter(Boolean).join(" · ");
}

function factsBlock(s: ContactSheet): string {
  if (!s.facts.length) return `<p class="small muted">Rien de plus que ce qui l'identifie.</p>`;
  return `<ul class="cx-sait">${s.facts.map((f) => {
    if (f.kind === "note") {
      const forget = f.forget && f.id ? `<button class="btn xs ghost" type="button" data-cx-oublier-fait="${f.id}" title="Qu'elle l'oublie" aria-label="Qu'elle oublie ce fait">${ico("x", "xs")}</button>` : "";
      return `<li class="cx-note-fait"><p>${h(f.value)}</p><small>${h(noteSource(f))}</small>${forget}</li>`;
    }
    const value = f.kind === "organisation" && f.id ? `<a href="${contactHash(f.id)}" data-cx-lien="${f.id}">${h(f.value)}</a>` : h(f.value);
    return `<li><p><span class="muted">${h(f.label)}</span>${value}</p>${f.from ? `<small>d'après ${h(f.from)}</small>` : ""}</li>`;
  }).join("")}</ul>`;
}

function placesBlock(s: ContactSheet, now: number): string {
  if (!s.places.length) return "";
  return `<h4 class="rd-h4">Où vous vous croisez</h4><div class="cx-croise">${s.places.map((p) => {
    const part = placeParts(p, s.name, now);
    return `<a class="li" href="${h(part.href)}">${ico(part.icon, "sm")}<span class="li-main"><span class="li-title">${h(part.title)}</span><span class="li-snip">${h(part.detail)}</span></span>${ico("chev-right", "sm")}</a>`;
  }).join("")}</div>`;
}

/** La tête de la fiche : son nom, ce qu'on en sait, son organisation, s'il parle aussi à Mika ; Écrire, Teams, Message. */
function sheetHead(s: ContactSheet): string {
  const line = s.kind === "org" ? (s.members_total ? `Organisation · ${plural(s.members_total, "personne", "personnes")} parmi tes contacts` : "Organisation") : idea(s);
  const org = s.organisation ? `${line ? " · " : ""}<a href="${contactHash(s.organisation.id)}" data-cx-lien="${s.organisation.id}">${h(s.organisation.name)}</a>` : "";
  const tag = s.linked ? ` <span class="tag${s.talks ? " ok" : ""}">${h(linkedWords(s))}</span>` : "";
  const write = s.write ? `<a class="btn primary sm" href="${h(writeHash(s))}">${ico("send", "sm")}Écrire</a>` : "";
  const teams = s.teams ? `<a class="btn sm" href="${h(teamsHash(s.teams))}">${ico("teams", "sm")}Teams</a>` : "";
  const message = s.message ? `<a class="btn sm" href="${h(phoneHash(s.message))}">${ico("phone", "sm")}Message</a>` : "";
  return `<div class="ct-head">${contactAvatar(s, "xl")}<div class="grow"><h2>${h(s.name)}</h2>
      <p class="text-2">${h(line)}${org}${tag}</p></div>${write}${teams}${message}</div>`;
}

export function sheetMarkup(s: ContactSheet, now: number): string {
  const facts = [...s.sources.map(sourceFact), s.last ? `<span>${ico("clock", "sm")}dernier échange ${h(dayAndClock(s.last, now))}</span>` : ""].join("");
  return `<div class="pane-scroll ct-card cx-card"><button class="btn sm ghost mobile-back" type="button" data-retour-cx>${ico("chev-left", "sm")}Contacts</button>
    ${sheetHead(s)}
    ${facts ? `<div class="facts ct-facts">${facts}</div>` : ""}
    <div class="ct-cols">
      <div><h4 class="rd-h4">Ce qui l'identifie</h4>${identifiersBlock(s)}${membersBlock(s, now)}</div>
      <div><h4 class="rd-h4">${ico("sparkle", "sm")}Ce que Mika en sait</h4>${factsBlock(s)}${placesBlock(s, now)}</div>
    </div>
    <p class="small muted cx-note">${h(privacyNote(s))}</p>
    <div class="ct-foot"><button class="btn sm ghost danger" type="button" data-cx-oublier${s.forget.allowed ? "" : ` title="${h(s.forget.reason)}"`}>${ico("trash", "sm")}Oublier ce contact</button></div>
  </div>`;
}

/** La fiche pendant sa lecture, après un refus, ou rien de choisi. */
export function sheetPlaceholder(state: "none" | "loading" | "missing" | "error", error = ""): string {
  const back = `<button class="btn sm ghost mobile-back" type="button" data-retour-cx>${ico("chev-left", "sm")}Contacts</button>`;
  if (state === "loading") return `<div class="pane-scroll ct-card">${back}<div class="empty">${ico("refresh")}<b>Chargement…</b></div></div>`;
  if (state === "missing") return `<div class="pane-scroll ct-card">${back}<div class="empty">${ico("user")}<b>Contact introuvable</b><p>Il n'est pas parmi tes contacts (ou Mika l'a oublié).</p></div></div>`;
  if (state === "error") return `<div class="pane-scroll ct-card">${back}<div class="empty">${ico("alert")}<b>Impossible de lire ce contact</b><p>${h(error)}</p><button class="btn sm" type="button" data-cx-relire>Réessayer</button></div></div>`;
  return `<div class="pane-scroll"><div class="empty">${ico("users")}<b>Choisis un contact</b><p>Ce qui l'identifie, ce que Mika en sait et où vous vous croisez s'affichent ici.</p></div></div>`;
}

/** Ce que demande la confirmation de l'oubli d'un fait. */
export function forgetFactQuestion(f: Pick<ContactFact, "value">): string {
  return `Mika oubliera ce qu'elle avait compris : « ${f.value} ». Elle ne le réapprendra pas, même dit autrement ; les messages restent où ils sont.`;
}

/** Ce que demande la confirmation de l'oubli. */
export function forgetQuestion(s: Pick<ContactSheet, "name">): string {
  return `Mika oubliera ${s.name} : sa fiche, et ce que Teams, le courrier, ton téléphone et sa mémoire en gardaient. Les messages restent dans leurs boîtes.`;
}
