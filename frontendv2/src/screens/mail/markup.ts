/**
 * Le rendu de Mail, celui de la maquette (`frontendv2/maquette/ecrans/mail.js`), nourri par l'API par personne :
 * la colonne des boîtes, la liste, la liseuse d'un mail ou d'un brouillon d'elle, la réponse en place, le formulaire
 * d'un mail, les contacts. Pur : des chaînes HTML, tout texte venu d'ailleurs échappé.
 */
import { h } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { mikaAvatar } from "../../mika/face";
import { dayAndClock, shortWhen, sizeLabel } from "../chat/markup";
import { MAIL_LIMITS, type Contact, type DraftState, type MailAttachment, type MailBox, type MailDraft, type MailFolder, type MailFull, type MailRow, type MailState, type Person, type SentMail } from "../../api/mail";
import {
  avatar,
  bodyLead,
  boxTitle,
  answerable,
  caps,
  chars,
  countLabel,
  firstName,
  howLabel,
  levelTag,
  markToFill,
  ofName,
  parseAddresses,
  personName,
  replyTargets,
  sameAddress,
  shareSentence,
  textHtml,
  type Caps,
} from "./format";

// ── Les vues de la colonne de gauche ──────────────────────────────────

/** Ce que montre la liste : toutes les réceptions, les suivis, ce qui est parti, ses brouillons, où elle est passée,
 *  ou un dossier d'une boîte. */
export type View =
  | { kind: "inbox" }
  | { kind: "flagged" }
  | { kind: "noticed" }
  | { kind: "sent"; box: string }
  | { kind: "drafts"; box: string }
  | { kind: "folder"; box: string; folder: string };

export function viewKey(v: View): string {
  switch (v.kind) {
    case "sent":
    case "drafts":
      return v.box ? `${v.kind}:${v.box}` : v.kind;
    case "folder":
      return `folder:${v.box}:${v.folder}`;
    default:
      return v.kind;
  }
}

export function parseView(key: string): View {
  if (key === "flagged" || key === "noticed" || key === "inbox") return { kind: key };
  const [kind, ...rest] = key.split(":");
  if (kind === "sent" || kind === "drafts") return { kind, box: rest.join(":") };
  if (kind === "folder" && rest.length >= 2) return { kind, box: rest[0], folder: rest.slice(1).join(":") };
  return { kind: "inbox" };
}

/** Une boîte, telle que la colonne la montre : ses dossiers, sa couleur, son nom (« Boîte de Léa »). */
export interface BoxView {
  box: MailBox;
  title: string;
  color: number;
  open: boolean;
}

const DOT_COLORS = [0, 7, 3, 1];

export function boxViews(boxes: readonly MailBox[], opened: ReadonlySet<string>): BoxView[] {
  const ordered = [...boxes.filter((b) => b.level === "proprietaire"), ...boxes.filter((b) => b.level !== "proprietaire")];
  return ordered.map((box, i) => ({ box, title: boxTitle(box, boxes), color: DOT_COLORS[i % DOT_COLORS.length], open: opened.has(box.key) }));
}

const ROLE_ICON: Record<string, IconName> = { inbox: "inbox", sent: "send", drafts: "file", archive: "archive", junk: "alert", trash: "trash" };
const ROLE_ORDER = ["inbox", "sent", "drafts", "archive", "junk", "trash"];

export function inboxOf(box: MailBox): MailFolder | undefined {
  return box.folders.find((f) => f.role === "inbox") ?? box.folders.find((f) => f.name === "INBOX");
}

/** Le dossier « Brouillons » d'une boîte montre ses brouillons à elle ; « Envoyés », ce qui en est parti. */
export function folderView(box: MailBox, f: MailFolder): View {
  if (f.role === "sent") return { kind: "sent", box: box.key };
  if (f.role === "drafts") return { kind: "drafts", box: box.key };
  return { kind: "folder", box: box.key, folder: f.name };
}

function orderedFolders(box: MailBox): MailFolder[] {
  const rank = (f: MailFolder) => {
    const i = ROLE_ORDER.indexOf(f.role);
    return i < 0 ? ROLE_ORDER.length : i;
  };
  return [...box.folders].sort((a, b) => rank(a) - rank(b));
}

export interface BoxesPane {
  boxes: BoxView[];
  view: string;
  /** Les non-lus de toutes les réceptions. */
  unseen: number;
  /** Ses brouillons qui attendent une décision que tu peux prendre. */
  waiting: number;
  plugged: boolean;
  error: string;
}

function navButton(view: string, current: string, label: string, icon: IconName, count: number | string, cls = "", title = ""): string {
  const classes = [view === current ? "on" : "", cls].filter(Boolean).join(" ");
  return `<button type="button"${classes ? ` class="${classes}"` : ""} data-vue="${h(view)}"${title ? ` title="${h(title)}"` : ""}>${ico(icon)}<span class="ellipsis">${h(label)}</span>${count ? `<span class="cnt">${h(count)}</span>` : ""}</button>`;
}

function boxBlock(v: BoxView, current: string): string {
  const b = v.box;
  const shared = b.level !== "proprietaire";
  const inbox = inboxOf(b);
  const unseen = inbox?.unseen ?? 0;
  const why = b.error || (!b.ready ? "Sa connexion n'est pas prête." : "");
  const mark = shared
    ? `<span class="tag" title="Partagée avec toi par ${h(b.owner_name)}">${ico("lock", "xs")}${h(levelTag(b.level))}</span>`
    : why
      ? `<a class="mb-err" href="#parametres/comptes-mail" title="${h(why)}">${ico("alert", "xs")}</a>`
      : unseen
        ? `<span class="cnt">${unseen}</span>`
        : "";
  const title = shared ? `${b.name} <${b.address}>, partagée avec toi par ${b.owner_name}` : `${b.name} <${b.address}>`;
  const folders = v.open
    ? `<div class="nav-list">${orderedFolders(b)
        .map((f) => {
          const fv = viewKey(folderView(b, f));
          const count = f.role === "drafts" ? b.drafts_waiting : f.unseen;
          const off = !f.polled && f.role !== "sent" && f.role !== "drafts";
          return navButton(fv, current, f.label || f.name, ROLE_ICON[f.role] ?? "folder", count, off ? "unpolled" : "", off ? "Pas relevé par Mika" : "");
        })
        .join("")}</div>`
    : "";
  return `<div class="mb-box${v.open ? " open" : ""}"><button type="button" class="mb-name" data-boite="${h(b.key)}" title="${h(title)}">${ico(v.open ? "chev-down" : "chev-right", "xs")}<span class="dot c${v.color}"></span><b class="ellipsis">${h(v.title)}</b>${mark}</button>${folders}</div>`;
}

export function boxesPane(p: BoxesPane): string {
  if (!p.plugged) {
    return `<div class="empty">${ico("mail")}<b>Le courrier n'est pas branché</b><p>Ce serveur n'a pas de courrier.</p></div>`;
  }
  const own = p.boxes.filter((b) => b.box.level === "proprietaire");
  const shared = p.boxes.filter((b) => b.box.level !== "proprietaire");
  return `<div class="pane-scroll mb-scroll">
    <div class="nav-list">${navButton("inbox", p.view, "Toutes les réceptions", "inbox", p.unseen)}${navButton("flagged", p.view, "Suivis", "star", 0)}${navButton("sent", p.view, "Envoyés", "send", 0)}</div>
    <div class="group-label">Mika</div>
    <div class="nav-list">${navButton("drafts", p.view, "Ses brouillons", "pen", p.waiting, "mika-link")}${navButton("noticed", p.view, "Où Mika est passée", "eye", 0, "mika-link")}</div>
    ${p.error ? `<p class="small mb-note">${ico("alert", "xs")}${h(p.error)}</p>` : ""}
    <div class="group-label">Tes boîtes<span class="cnt">${own.length}</span></div>
    ${own.length ? own.map((b) => boxBlock(b, p.view)).join("") : '<p class="small muted mb-note">Aucune boîte à toi.</p>'}
    ${shared.length ? `<div class="group-label">Partagée${shared.length > 1 ? "s" : ""} avec toi</div>${shared.map((b) => boxBlock(b, p.view)).join("")}` : ""}
    <a class="mb-add" href="#parametres/comptes-mail">${ico("plus", "sm")}Ajouter un compte</a>
  </div>`;
}

// ── La liste ──────────────────────────────────────────────────────────

export const FILTERS: readonly (readonly [MailState, string])[] = [
  ["", "Tout"],
  ["unread", "Non lus"],
  ["noticed", "Où Mika est passée"],
];

/** Le seul filtre d'une vue qui l'accepte (une réception, un dossier) : l'état est un seul paramètre de l'API. */
export function filtersApply(v: View): boolean {
  return v.kind === "inbox" || v.kind === "folder";
}

export function viewTitle(v: View, boxes: readonly BoxView[]): string {
  const box = "box" in v && v.box ? boxes.find((b) => b.box.key === v.box) : undefined;
  switch (v.kind) {
    case "inbox":
      return "Toutes les réceptions";
    case "flagged":
      return "Suivis";
    case "noticed":
      return "Où Mika est passée";
    case "sent":
      return box ? `${box.title} · Envoyés` : "Envoyés";
    case "drafts":
      return box ? `${box.title} · Ses brouillons` : "Ses brouillons";
    case "folder": {
      const f = box?.box.folders.find((x) => x.name === v.folder);
      return `${box?.title ?? v.box} · ${f?.label || v.folder}`;
    }
  }
}

export function listHead(title: string, total: number, checked: number): string {
  if (checked) {
    return `<b>${checked} choisi${checked > 1 ? "s" : ""}</b><span class="grow"></span>
      <button class="btn xs" type="button" data-groupe="read">${ico("check", "xs")}Lu</button>
      <button class="btn xs icon" type="button" data-groupe="unread" title="Marquer non lus">${ico("mail", "xs")}</button>
      <button class="btn xs" type="button" data-groupe="archive">${ico("archive", "xs")}Archiver</button>
      <button class="btn xs" type="button" data-groupe="trash" title="Corbeille">${ico("trash", "xs")}</button>
      <button class="btn xs ghost" type="button" data-groupe="none">Annuler</button>`;
  }
  return `<button class="btn sm ghost folder-pick" type="button" data-dossiers title="Boîtes et dossiers">${ico("folder", "sm")}</button>
    <h2 class="ellipsis">${h(title)}</h2><span class="cnt">${total}</span><span class="grow"></span>
    <button class="btn icon ghost sm" type="button" title="Relever maintenant" data-relever>${ico("refresh", "sm")}</button>`;
}

export function listTools(q: string, placeholder: string): string {
  return `<label class="search grow">${ico("search", "sm")}<input type="search" placeholder="${h(placeholder)}" data-mq value="${h(q)}" aria-label="Chercher" maxlength="${MAIL_LIMITS.search}"></label>`;
}

/** Le compte d'un texte borné (près de son champ) : caché tant qu'il est loin de sa borne ; `paintCount` le suit.
 *  (`data-limit`, pas `data-count` : ce nom-là est celui des pastilles de la barre du haut.) */
export function countSpan(text: string, max: number, cls = ""): string {
  const label = countLabel(text, max);
  return `<span class="small muted cmp-count${cls ? ` ${cls}` : ""}${chars(text) >= max ? " full" : ""}" data-limit="${max}"${label ? "" : " hidden"}>${h(label)}</span>`;
}

export function listFilters(filter: MailState): string {
  return `<div class="seg" role="group" aria-label="Filtrer">${FILTERS.map(([k, label]) => `<button type="button" data-filtre="${k}" aria-pressed="${filter === k}">${h(label)}</button>`).join("")}</div>`;
}

export interface RowView {
  now: number;
  selected: string;
  checked: ReadonlySet<string>;
  /** Plusieurs boîtes dans la vue : chaque ligne dit la sienne. */
  many: boolean;
  boxes: ReadonlyMap<string, BoxView>;
}

function boxMark(b: BoxView | undefined): string {
  return b ? `<span class="box-mark"><span class="dot c${b.color}"></span>${h(b.title)}</span>` : "";
}

/** Ce qu'elle a fait d'un mail, en marques roses (et ce que le serveur en dit). */
export function herMarks(r: Pick<MailRow, "her" | "answered">): string {
  const her = r.her;
  const out: string[] = [];
  if (her?.important) out.push('<span class="tag danger">important</span>');
  if (her?.needs_reply) out.push('<span class="tag warn">réponse attendue</span>');
  if (her?.read) {
    const how = howLabel(her.how);
    out.push(`<span class="mk${how.icon === "eye" ? "" : " quiet"}">${ico(how.icon)}${h(how.text)}</span>`);
  }
  if (her?.draft) out.push(`<span class="mk">${ico("pen")}brouillon prêt</span>`);
  else if (her?.asked) out.push(`<span class="mk quiet">${ico("sparkle")}elle s'y met</span>`);
  if (r.answered) out.push('<span class="tag">répondu</span>');
  return out.join("");
}

export function mailRow(r: MailRow, v: RowView, canTidy: boolean): string {
  const b = v.boxes.get(r.box);
  const marks = `${v.many ? boxMark(b) : ""}${herMarks(r)}`;
  const from = personName(r.from) || "(sans expéditeur)";
  return `<div class="li mrow${r.seen ? "" : " unread"}" role="button" tabindex="0" data-mail="${h(r.ref)}" aria-selected="${v.selected === r.ref}">
    ${canTidy ? `<label class="mrow-check" title="Choisir"><input type="checkbox" data-coche="${h(r.ref)}"${v.checked.has(r.ref) ? " checked" : ""}></label>` : '<span class="mrow-check"></span>'}
    <span class="mrow-av">${avatar(from, "sm", r.from.address || from)}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">${h(from)}</span>${r.attachments ? ico("clip", "xs") : ""}${r.flagged ? `<span class="star">${ico("star", "xs")}</span>` : ""}<time>${h(shortWhen(r.date, v.now))}</time></span>
      <span class="li-sub">${h(r.subject || "(sans objet)")}</span><span class="li-snip">${h(r.snippet)}</span>
      ${marks ? `<span class="li-marks">${marks}</span>` : ""}</span></div>`;
}

function recipients(people: readonly Person[]): string {
  if (!people.length) return "(personne)";
  const names = people.map(personName);
  return names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(", ");
}

export function sentRow(s: SentMail, v: RowView): string {
  const b = v.boxes.get(s.box);
  const first = s.to[0];
  const marks = `${v.many ? boxMark(b) : ""}${s.by ? "" : `<span class="mk">${ico("pen")}envoyé par elle</span>`}`;
  return `<button class="li mrow" type="button" data-mail="${h(s.ref)}" aria-selected="${v.selected === s.ref}">
    <span class="mrow-check"></span><span class="mrow-av">${first ? avatar(personName(first), "sm", first.address) : avatar("?", "sm")}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">À ${h(recipients(s.to))}</span>${s.attachments ? ico("clip", "xs") : ""}<time>${h(shortWhen(s.date, v.now))}</time></span>
      <span class="li-sub">${h(s.subject || "(sans objet)")}</span><span class="li-snip">${h(s.snippet)}</span>
      ${marks ? `<span class="li-marks">${marks}</span>` : ""}</span></button>`;
}

/** L'état d'un de ses brouillons, en mots, et son ton. */
export function draftState(d: Pick<MailDraft, "state" | "edited">): [string, string] {
  const states: Record<DraftState, [string, string]> = {
    attend: ["warn", "attend ton accord"],
    approuve: ["info", "approuvé, en partance"],
    parti: ["ok", "parti"],
    refuse: ["", "refusé"],
    echec: ["danger", "échec de l'envoi"],
  };
  const [tone, label] = states[d.state] ?? ["", d.state];
  return [tone, d.edited && (d.state === "parti" || d.state === "approuve") ? `${label} · retouché par toi` : label];
}

function draftBlocked(d: MailDraft): boolean {
  return !!(d.preview?.blocked || d.to_fill);
}

export function draftRow(d: MailDraft, v: RowView): string {
  const [tone, label] = draftState(d);
  const to = parseAddresses(d.preview?.to || d.to);
  const b = v.boxes.get(d.box);
  return `<button class="li mrow draft" type="button" data-draft="${h(d.id)}" aria-selected="${v.selected === `brouillon/${d.id}`}">
    <span class="mrow-check"></span><span class="mrow-av">${mikaAvatar("sm")}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">À ${h(recipients(to.length ? to : [{ name: d.to, address: d.to }]))}</span><time>${h(shortWhen(d.at, v.now))}</time></span>
      <span class="li-sub">${h(d.subject || "(sans objet)")}</span><span class="li-snip">${h(bodyLead(d.body))}</span>
      <span class="li-marks">${v.many ? boxMark(b) : ""}<span class="tag ${tone}">${h(label)}</span>${draftBlocked(d) && d.state === "attend" ? '<span class="tag danger">à compléter</span>' : ""}</span></span></button>`;
}

export function emptyList(icon: IconName, title: string, text: string): string {
  return `<div class="empty">${ico(icon)}<b>${h(title)}</b><p>${h(text)}</p></div>`;
}

export function listFoot(total: number, page: number, size: number): string {
  if (total <= size) return "";
  const from = (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  return `<button class="btn xs icon ghost" type="button" data-page="${page - 1}" title="Plus récents"${page <= 1 ? " disabled" : ""}>${ico("chev-left", "xs")}</button>
    <span class="small muted">${from}–${to} sur ${total}</span>
    <button class="btn xs icon ghost" type="button" data-page="${page + 1}" title="Plus anciens"${to >= total ? " disabled" : ""}>${ico("chev-right", "xs")}</button>`;
}

// ── La liseuse ────────────────────────────────────────────────────────

export interface ReaderView {
  now: number;
  box: BoxView | null;
  caps: Caps;
  /** L'adresse de son cadre (un mail HTML). */
  frame: string;
  /** Ses images distantes, montrées cette fois. */
  imagesOnce: boolean;
  /** Son brouillon qui attend pour ce mail (dans « Ses brouillons »). */
  draft: MailDraft | null;
  /** Une réponse demandée, pas encore écrite (« Elle s'y met… »). */
  asked: boolean;
  /** La réponse en place, déjà rendue (vide : la bande « Répondre à … »). */
  composer: string;
  /** Son brouillon est déjà repris dans la réponse en place. */
  taken?: boolean;
  mobile: boolean;
  /** Une de ses propriétaires (`GET /api/moi` → `owner`) : seule elle règle les images d'un expéditeur « toujours »
   *  — ce choix vaut pour tout le serveur ; les autres les affichent cette fois. */
  owner?: boolean;
}

function sharedBanner(box: MailBox): string {
  return `<div class="rd-shared">${ico("lock", "sm")}<span><b>Boîte ${h(ofName(box.owner_name || "son propriétaire"))}</b>, ${h(shareSentence(box.level, box.owner_name))}</span></div>`;
}

function toLine(m: MailFull, box: BoxView | null): string {
  const own = box?.box.level === "proprietaire";
  const mine = (p: Person) => !!box && sameAddress(p.address, box.box.address);
  const who = (p: Person) => (mine(p) ? (own ? "toi" : firstName(box!.box.owner_name) || personName(p)) : personName(p));
  const people = m.to.length ? m.to : box ? [{ name: "", address: box.box.address }] : [];
  const shown = people.slice(0, 3).map((p) => `${h(who(p))} &lt;${h(p.address)}&gt;`);
  const more = people.length > 3 ? ` +${people.length - 3}` : "";
  return `à ${shown.join(", ")}${more}`;
}

export function attachmentKind(a: Pick<MailAttachment, "name" | "mime">): string {
  const ext = /\.([a-z0-9]{1,5})$/i.exec(a.name)?.[1];
  if (ext) return ext.toUpperCase();
  const sub = a.mime.split("/")[1] ?? "";
  return (sub.split(/[.+;-]/)[0] || "FICHIER").slice(0, 5).toUpperCase();
}

function pieces(m: MailFull, url: (part: string) => string): string {
  if (!m.attachments.length) return "";
  return `<div class="rd-pieces"><h4>Pièces jointes <span class="cnt">${m.attachments.length}</span></h4><div class="row wrap">${m.attachments
    .map((a) => {
      const kind = attachmentKind(a);
      return `<div class="piece"><span class="piece-ico">${h(kind)}</span><span class="piece-main"><b class="ellipsis" title="${h(a.name)}">${h(a.name)}</b><small>${h(kind)}${a.size ? ` · ${h(sizeLabel(a.size))}` : ""}</small></span>
        <a class="btn xs icon ghost" href="${h(url(a.part))}" target="_blank" rel="noopener" download="${h(a.name)}" title="Télécharger">${ico("download", "xs")}</a></div>`;
    })
    .join("")}</div></div>`;
}

export function readerMail(m: MailFull, v: ReaderView, fileUrl: (part: string) => string): string {
  const box = v.box?.box ?? null;
  const shared = !!box && box.level !== "proprietaire";
  const c = v.caps;
  const her = m.her;
  const from = personName(m.from) || "(sans expéditeur)";
  const tags = [
    her?.important ? '<span class="tag danger">important</span>' : "",
    her?.needs_reply ? '<span class="tag warn">réponse attendue</span>' : "",
    m.flagged ? '<span class="tag accent">★ suivi</span>' : "",
    m.answered ? '<span class="tag">répondu</span>' : "",
    m.sent ? `<span class="tag">${ico("send", "xs")}parti de ta boîte</span>` : "",
  ].join("");
  // un mail parti de sa boîte, sans copie reçue, ne se répond pas (l'API refuse, 409) : il se transfère ; et elle
  // ne prépare jamais de réponse à un mail parti de ta boîte, même revenu en copie (409 aussi)
  const canAnswer = c.write && answerable(m);
  const actions =
    c.write || c.prepare
      ? `<div class="rd-actions" data-rd-actions>
        ${canAnswer ? `<button class="btn sm" type="button" data-act="repondre">${ico("reply", "sm")}Répondre</button>
        <button class="btn sm rd-sec" type="button" data-act="tous" title="Répondre à tous">${ico("reply-all", "sm")}<span class="lbl">Répondre à tous</span></button>` : ""}
        ${c.write ? `<button class="btn sm${canAnswer ? " rd-sec" : ""}" type="button" data-act="transferer" title="Transférer">${ico("forward", "sm")}<span class="lbl">Transférer</span></button>` : ""}
        ${c.prepare && !m.sent ? `<button class="btn sm mika" type="button" data-act="preremplir">${ico("sparkle", "sm")}Préremplir avec Mika</button>` : ""}
        <span class="grow"></span>
        ${c.write ? readerTidy(m) : ""}</div>`
      : "";
  const summary = her?.summary ? `<span>« ${h(her.summary)} »</span>` : "";
  const draftActions = v.draft
    ? `<div class="mn-actions"><button class="btn xs mika" type="button" data-ouvrir-brouillon="${h(v.draft.id)}">${ico("pen", "xs")}Relire son brouillon</button>
        ${canAnswer && !v.taken ? `<button class="btn xs ghost" type="button" data-act="reprendre-brouillon">${ico("reply", "xs")}Le reprendre dans ta réponse</button>` : ""}
        ${c.decide && v.draft.in_reply_to ? '<button class="btn xs ghost" type="button" data-act="autre-version">Lui demander une autre version</button>' : ""}</div>`
    : "";
  const asked = !v.draft && v.asked ? `<span class="rd-asked">${ico("sparkle", "xs")}Elle s'y met… sa réponse arrivera dans « Ses brouillons », et ici.</span>` : "";
  const knows = her?.noticed || her?.read || summary || v.draft || v.asked;
  const note = knows
    ? `<div class="mika-note rd-note">${mikaAvatar("sm")}<div class="mn-body"><div class="mn-title">${ico("eye", "xs")}Ce qu'elle en sait${her?.read ? ` · ${h(howLabel(her.how).text)}` : her?.noticed ? " · remarqué" : ""}</div>
        ${summary}${asked}${draftActions}</div></div>`
    : "";
  const masked = m.html && m.images.remote && !m.images.shown && !v.imagesOnce;
  // « toujours pour cet expéditeur » vaut pour tout le serveur : une de ses propriétaires seulement (l'API : 403 sinon)
  const always = c.write && !!v.owner;
  const images = masked
    ? `<div class="rd-images">${ico("image", "sm")}<span>Ses images distantes sont masquées : les charger dit à l'expéditeur que tu as ouvert ce mail.</span>
        <button class="btn xs" type="button" data-images="fois">Les afficher cette fois</button>${always ? '<button class="btn xs ghost" type="button" data-images="toujours">Toujours pour cet expéditeur</button>' : ""}</div>`
    : m.html && m.images.shown && always
      ? `<p class="small muted rd-images-on">${ico("image", "xs")}Ses images s'affichent pour cet expéditeur. <button class="linkish" type="button" data-images="jamais">Ne plus les afficher</button></p>`
      : "";
  const frame = m.html
    ? `<div class="rd-frame framed" title="Le mail s'affiche dans un cadre isolé (ADR 0169)"><iframe data-frame sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin" src="${h(v.frame)}" title="${h(m.subject || "Le mail")}" referrerpolicy="no-referrer"></iframe></div>`
    : `<div class="rd-frame">${textHtml(m.body) || '<p class="muted">(ce mail n\'a pas de texte)</p>'}</div>`;
  const partial = m.complete ? "" : `<p class="small muted">${ico("info", "xs")} Ce mail n'est relevé qu'en partie : son texte complet n'a pas encore été lu sur le serveur.</p>`;
  // à qui ira la réponse : l'expéditeur — ou, pour une copie revenue de ton propre mail, ses destinataires
  const answered = m.sent ? replyTargets(m, box?.address ?? "", false).to[0] : undefined;
  const answeredName = answered ? personName(answered) : from;
  const reply = canAnswer ? v.composer || `<button class="rd-reply-stub" type="button" data-act="repondre">${ico("reply", "sm")}Répondre à ${h(firstName(answeredName) || answeredName)}…</button>` : "";
  return `<div class="rd">
    ${shared && box ? sharedBanner(box) : ""}
    <div class="rd-head"><h2>${h(m.subject || "(sans objet)")}</h2><div class="row wrap" data-rd-tags>${tags}</div></div>
    <div class="rd-from">${avatar(from, "lg", m.from.address || from)}<div class="grow"><b>${h(from)}</b>${m.from.address && m.from.address !== from ? ` <span class="muted">&lt;${h(m.from.address)}&gt;</span>` : ""}
      <div class="small muted">${toLine(m, v.box)}${m.cc.length ? ` · cc ${h(m.cc.map(personName).join(", "))}` : ""} · ${boxMark(v.box ?? undefined)} · ${h(dayAndClock(m.date, v.now))}</div></div></div>
    ${actions}${note}${images}${frame}${partial}${pieces(m, fileUrl)}${reply}
  </div>`;
}

/** Les gestes de « ranger » de la liseuse (repeints seuls quand un drapeau change). */
export function readerTidy(m: Pick<MailFull, "seen" | "flagged">): string {
  return `<button class="btn sm icon ghost" type="button" data-act="archiver" title="Archiver">${ico("archive", "sm")}</button>
    <button class="btn sm icon ghost" type="button" data-act="lu" title="${m.seen ? "Marquer non lu" : "Marquer comme lu"}">${ico(m.seen ? "mail" : "check", "sm")}</button>
    <button class="btn sm icon ghost${m.flagged ? " on" : ""}" type="button" data-act="suivre" title="${m.flagged ? "Ne plus suivre" : "Suivre"}" aria-pressed="${m.flagged}">${ico("star", "sm")}</button>
    <button class="btn sm icon ghost" type="button" data-act="corbeille" title="Corbeille">${ico("trash", "sm")}</button>`;
}

export interface DraftReaderView {
  now: number;
  box: BoxView | null;
  caps: Caps;
  mobile: boolean;
}

export function readerDraft(d: MailDraft, v: DraftReaderView): string {
  const [tone, label] = draftState(d);
  const box = v.box?.box ?? null;
  const waiting = d.state === "attend";
  const blocked = d.preview?.blocked || (waiting && d.to_fill ? "il reste des passages à compléter" : "");
  const text = d.preview?.text ?? d.body;
  // l'expéditeur exact n'est connu que de l'aperçu (tant qu'il attend) : sinon, la boîte seule
  const from = d.preview?.sender ?? "";
  const original = d.original
    ? `<button class="linkish" type="button" data-ouvrir-mail="${h(d.in_reply_to)}">${h(d.original.subject || "(sans objet)")}</button><span class="muted"> · ${h(d.original.from)}</span>`
    : d.in_reply_to
      ? `<button class="linkish" type="button" data-ouvrir-mail="${h(d.in_reply_to)}">le mail d'origine</button>`
      : "";
  const owner = box?.owner_name || "son propriétaire";
  const decide = waiting && v.caps.decide
    ? `<div class="rd-decide"><button class="btn sm ghost danger" type="button" data-decide="refuser">Refuser</button>
        ${d.in_reply_to ? `<button class="btn sm" type="button" data-decide="reprendre">${ico("refresh", "sm")}<span class="lbl">Lui demander de le reprendre</span></button>` : ""}
        <button class="btn sm" type="button" data-decide="retoucher">${ico("pen", "sm")}Retoucher</button><span class="grow"></span>
        <button class="btn sm primary" type="button" data-decide="envoyer"${blocked || !d.preview ? " disabled" : ""}>${ico("send", "sm")}Envoyer</button></div>
      <p class="small muted">Rien ne part sans toi. Ce que tu changes, elle l'apprend : sa version et la tienne.</p>`
    : waiting
      ? `<div class="rd-shared">${ico("lock", "sm")}<span>Ce brouillon attend la décision de <b>${h(owner)}</b> : c'est le propriétaire de la boîte qui décide de ce qui en part.</span></div>`
      : `<p class="small muted">${h(label.charAt(0).toUpperCase() + label.slice(1))}${d.decided_at ? ` · ${h(dayAndClock(d.decided_at, v.now))}` : ""}.${d.note ? ` Note : « ${h(d.note)} ».` : ""}</p>`;
  return `<div class="rd">
    <div class="rd-head"><h2>${h(d.subject || "(sans objet)")}</h2><div class="row wrap"><span class="tag ${tone}">${h(label)}</span>${blocked && waiting ? '<span class="tag danger">à compléter</span>' : ""}<span class="mk">${ico("pen")}rédigé par Mika</span></div></div>
    <h4 class="rd-h4">${waiting ? "Ce qui partira" : d.state === "parti" ? "Ce qui est parti" : "Son brouillon"}</h4>
    <dl class="kv rd-kv">${from ? `<dt>De</dt><dd>${h(from)}</dd>` : ""}<dt>À</dt><dd>${h(d.preview?.to || d.to || "—")}</dd>
      ${(d.preview?.cc || d.cc) ? `<dt>Cc</dt><dd>${h(d.preview?.cc || d.cc)}</dd>` : ""}<dt>Objet</dt><dd>${h(d.preview?.subject || d.subject)}</dd>
      ${original ? `<dt>En réponse à</dt><dd>${original}</dd>` : ""}${box ? `<dt>Boîte</dt><dd>${boxMark(v.box ?? undefined)}</dd>` : ""}</dl>
    <pre class="rd-exact">${markToFill(h(text))}</pre>
    ${blocked && waiting ? `<div class="rd-block">${ico("alert", "sm")}Il ne peut pas partir tel quel : ${h(blocked)}. Retouche-le.</div>` : ""}
    ${decide}
  </div>`;
}

export function readerEmpty(icon: IconName, title: string, text: string): string {
  return `<div class="empty">${ico(icon)}<b>${h(title)}</b><p>${h(text)}</p></div>`;
}

// ── Écrire ────────────────────────────────────────────────────────────

/** Un destinataire en puce (son adresse dans `data-addr`). */
export function chip(p: Person): string {
  const name = personName(p);
  return `<span class="chip" title="${h(p.address)}" data-addr="${h(p.address)}" data-name="${h(p.name)}">${avatar(name, "xs", p.address)}${h(name)}<button type="button" title="Retirer" data-unchip>${ico("x", "xs")}</button></span>`;
}

export function recipientField(field: "to" | "cc", people: readonly Person[], placeholder: string): string {
  return `<div class="rcpt" data-rcpt="${field}">${people.map(chip).join("")}<input data-ac placeholder="${h(placeholder)}" autocomplete="off" aria-label="${field === "to" ? "Destinataires" : "Copie"}"></div>`;
}

export interface InlineReply {
  all: boolean;
  to: Person[];
  /** L'objet : « Re: … », ou celui de son brouillon repris. */
  subject: string;
  cc: Person[];
  showCc: boolean;
  body: string;
  quote: boolean;
  /** Le brouillon d'elle repris ici (son identifiant). */
  fromDraft: string;
  filled: string;
  sending: boolean;
  error: string;
}

export function inlineReply(c: InlineReply, box: BoxView | null, canPrepare: boolean): string {
  return `<div class="composer rd-reply${c.filled ? " filled" : ""}" data-reply>
    <div class="rd-reply-head"><span class="small muted">De</span><span class="small rd-reply-from" title="${box ? h(box.box.address) : ""}">${box ? `${h(box.title)} &lt;${h(box.box.address)}&gt;` : ""}</span>
      <span class="small muted">À</span>${recipientField("to", c.to, "Ajouter…")}${c.showCc ? "" : '<button class="btn xs ghost" type="button" data-act="cc">Cc</button>'}</div>
    ${c.showCc ? `<div class="rd-reply-head"><span class="small muted">Cc</span>${recipientField("cc", c.cc, "Copie…")}</div>` : ""}
    <div class="ac-pop" data-acpop hidden></div>
    ${c.filled ? `<div class="tm-filled">${ico("sparkle", "xs")}${h(c.filled)} — relis avant d'envoyer<button type="button" class="btn xs ghost" data-act="vider">Effacer</button></div>` : ""}
    <textarea rows="5" data-rd-txt placeholder="Ta réponse…" aria-label="Ta réponse" maxlength="${MAIL_LIMITS.body}">${h(c.body)}</textarea>
    ${c.error ? `<p class="small rd-reply-error">${ico("alert", "xs")}${h(c.error)}</p>` : ""}
    <div class="cmp-bar">${canPrepare ? `<button class="btn sm mika" type="button" data-act="preremplir">${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>` : ""}
      <label class="small muted row cite" title="Citer le mail auquel tu réponds"><input type="checkbox" data-quote${c.quote ? " checked" : ""}><span class="lbl">citer le mail</span></label><span class="grow"></span>
      ${countSpan(c.body, MAIL_LIMITS.body)}
      <button class="btn sm ghost" type="button" data-act="fermer-rep">Annuler</button>
      <button class="btn sm primary" type="button" data-act="envoyer"${c.sending ? " disabled" : ""}>${ico("send", "sm")}<span class="lbl">${c.sending ? "Envoi…" : "Envoyer"}</span></button></div></div>`;
}

export interface ComposeForm {
  kind: "new" | "forward" | "edit";
  /** Les boîtes d'où l'on peut écrire (un mail nouveau) ; sinon la boîte imposée. */
  boxes: readonly BoxView[];
  box: string;
  to: readonly Person[];
  cc: readonly Person[];
  subject: string;
  body: string;
  /** Un transfert : ses pièces (0 : rien à joindre). */
  attachments: number;
  /** Un brouillon qui répond à un mail : citer ou non. */
  quote: boolean | null;
}

export function composeForm(f: ComposeForm): string {
  const from = f.kind === "new"
    ? `<select data-de aria-label="De">${f.boxes.map((b) => `<option value="${h(b.box.key)}"${b.box.key === f.box ? " selected" : ""}>${h(b.title)} &lt;${h(b.box.address)}&gt;</option>`).join("")}</select>`
    : `<span class="cf-fixed">${h(f.boxes.find((b) => b.box.key === f.box)?.title ?? f.box)} &lt;${h(f.boxes.find((b) => b.box.key === f.box)?.box.address ?? "")}&gt;</span>`;
  const showCc = f.cc.length > 0;
  return `<div class="cmp-form" data-compose>
    <div class="cf-row"><span>De</span>${from}<span></span></div>
    <div class="cf-row"><span>À</span>${recipientField("to", f.to, "Un nom ou une adresse…")}<span class="row">${showCc ? "" : '<button class="btn xs ghost" type="button" data-cc>Cc</button>'}</span></div>
    <div class="cf-row" data-ccrow${showCc ? "" : " hidden"}><span>Cc</span>${recipientField("cc", f.cc, "Copie…")}<span></span></div>
    <div class="ac-pop" data-acpop hidden></div>
    <label class="cf-row"><span>Objet</span><input data-objet value="${h(f.subject)}" placeholder="Objet" maxlength="${MAIL_LIMITS.subject}"></label>
    <textarea rows="10" data-corps placeholder="${f.kind === "forward" ? "Un mot d'accompagnement (facultatif)…" : "Ton message…"}" aria-label="Le message" maxlength="${MAIL_LIMITS.body}">${h(f.body)}</textarea>
    ${countSpan(f.body, MAIL_LIMITS.body, "cf-count")}
    ${f.kind === "forward" && f.attachments ? `<label class="small row cf-check"><input type="checkbox" data-pieces checked>${f.attachments > 1 ? `Joindre ses ${f.attachments} pièces jointes` : "Joindre sa pièce jointe"}</label>` : ""}
    ${f.kind === "forward" ? '<p class="small muted">Le message d\'origine complet suit ton texte.</p>' : ""}
    ${f.quote !== null ? `<label class="small row cf-check"><input type="checkbox" data-citer${f.quote ? " checked" : ""}>Citer le mail auquel il répond</label>` : ""}
    <p class="small cf-error" data-erreur hidden></p>
  </div>`;
}

/** Les correspondants proposés sous un champ de destinataires. */
export function suggestions(found: readonly Contact[], typed: string, sel: number): string {
  if (!found.length) return `<div class="ac-none">Aucun contact : « ${h(typed)} » sera pris tel quel.</div>`;
  return found
    .map((c, k) => `<button type="button" class="ac-item${k === sel ? " on" : ""}" data-pick="${k}">${avatar(c.name || c.address, "sm", c.address)}
      <span><b>${h(c.name || c.address)}</b><small>${h(c.address)} · ${c.received} reçu${c.received > 1 ? "s" : ""} · ${c.sent} envoyé${c.sent > 1 ? "s" : ""}</small></span></button>`)
    .join("");
}

// ── Les contacts ──────────────────────────────────────────────────────

export function contactRow(c: Contact, selected: string, now: number): string {
  const name = c.name || c.address;
  return `<button class="li" type="button" data-contact="${h(c.address)}" aria-selected="${selected === c.address}">
    ${avatar(name, "sm", c.address)}<span class="li-main"><span class="li-top"><span class="li-title">${h(name)}</span><time>${h(shortWhen(c.last, now))}</time></span><span class="li-snip">${h(c.address)}</span></span></button>`;
}

export function contactCard(c: Contact, mails: readonly MailRow[] | null, now: number, canWrite: boolean, mobile: boolean, boxes: ReadonlyMap<string, BoxView>): string {
  const name = c.name || c.address;
  const recent = mails === null
    ? '<p class="small muted">Chargement…</p>'
    : mails.length
      ? `<div class="ct-mails">${mails.map((m) => `<button class="li" type="button" data-ouvrir-mail="${h(m.ref)}"><span class="li-main"><span class="li-top"><span class="li-title">${h(m.subject || "(sans objet)")}</span><time>${h(shortWhen(m.date, now))}</time></span>
          <span class="li-snip">${h(boxes.get(m.box)?.title ?? m.box)}</span></span></button>`).join("")}</div>`
      : '<p class="small muted">Aucun mail relevé de cette adresse.</p>';
  return `<div class="pane-scroll ct-card">${mobile ? `<button class="btn sm ghost mobile-back" type="button" data-retour-c>${ico("chev-left", "sm")}Contacts</button>` : ""}
    <div class="ct-head">${avatar(name, "xl", c.address)}<div class="grow"><h2>${h(name)}</h2><p class="text-2">correspondant</p></div>
      ${canWrite ? `<button class="btn primary sm" type="button" data-ecrire-a="${h(c.address)}">${ico("send", "sm")}Écrire</button>` : ""}</div>
    <div class="facts ct-facts"><span>${ico("inbox", "sm")}${c.received} reçu${c.received > 1 ? "s" : ""}</span><span>${ico("send", "sm")}${c.sent} envoyé${c.sent > 1 ? "s" : ""}</span>${c.last ? `<span>${ico("clock", "sm")}dernier échange ${h(dayAndClock(c.last, now))}</span>` : ""}</div>
    <h4 class="rd-h4">Ses moyens de communication</h4>
    <ul class="ct-ways"><li>${ico("mail", "sm")}<span class="muted">Mail</span><b>${h(c.address)}</b></li></ul>
    <h4 class="rd-h4">Derniers mails reçus</h4>${recent}
  </div>`;
}

/** Les capacités d'une boîte (sa boîte, ou celle d'un partage). */
export function boxCaps(box: MailBox | null | undefined): Caps {
  return caps(box?.level ?? "lire");
}

