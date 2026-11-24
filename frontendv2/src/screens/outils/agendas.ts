/**
 * Outils › Droits : chaque agenda, une ressource de la matrice (ADR 0309, lot 6 ; la maquette validée
 * `maquette/ecrans/agenda-droits.js`). Un groupe « Tes agendas » dans la liste des ressources, et pour chacun son
 * tableau : Lire ; Ajouter, modifier, supprimer (non · avec ton accord · seule) ; Répondre aux invitations (non · avec
 * ton accord) ; Ce qu'elle en garde — sur ses lignes Qui × Par où × Quand, lues de haut en bas. Le propriétaire d'un
 * agenda règle son tableau ici (`GET`/`POST /api/moi/agenda/rights`) ; la ligne d'un partage se retire avec lui.
 * Adresse : `#outils/droits/ag:<agenda>`.
 */
import type { AgendaCalendar, AgendaRule } from "../../api/agenda";
import { resetAgendaRights, saveAgendaRights } from "../../api/agenda";
import { setShare } from "../../api/shares";
import { h, norm } from "../../shell/dom";
import { toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { confirmModal, toastFailure } from "../../shared/kit";
import * as store from "../../shared/store";
import { colorOf, ownerLine, providerShort } from "../agenda/model";

export const AG = "ag:";

const READ: readonly (readonly [string, string])[] = [["oui", "Oui"], ["non", "Non"]];
const WRITE: readonly (readonly [string, string])[] = [["non", "Non"], ["accord", "Ton accord"], ["seule", "Seule"]];
const RESPOND: readonly (readonly [string, string])[] = [["non", "Non"], ["accord", "Ton accord"]];
const KEEP: readonly (readonly [string, string])[] = [["rien", "rien"], ["perso", "un souvenir"], ["public", "un savoir"], ["prive", "une confidence"]];
const TONE: Record<string, string> = { oui: "ok", seule: "ok", accord: "warn", non: "off" };
const COLS = [["read", "Lire", READ], ["write", "Ajouter, modifier, supprimer", WRITE], ["respond", "Répondre aux invitations", RESPOND], ["keep", "Ce qu'elle en garde", KEEP]] as const;

/** Ses agendas dont elle règle le tableau (les siens). */
export function ownedCalendars(): AgendaCalendar[] {
  return (store.agendaCalendars.value?.calendars ?? []).filter((c) => c.level === "proprietaire" && c.can.rights);
}

function valueOf(line: AgendaRule, col: (typeof COLS)[number][0]): string {
  return col === "read" ? (line.read ? "oui" : "non") : String(line[col]);
}

function cell(key: string, i: number, col: (typeof COLS)[number][0], line: AgendaRule, choices: readonly (readonly [string, string])[], readOnly: boolean): string {
  const v = valueOf(line, col);
  if (readOnly && (col === "write" || col === "respond")) return `<td class="ag-mx-c"><span class="lv off">—</span></td>`;
  return `<td class="ag-mx-c"><select class="ag-lv ${col === "keep" ? "garde" : TONE[v] ?? ""}" data-agdroit="${h(key)}|${i}|${col}" aria-label="${h(COLS.find((c) => c[0] === col)![1])}">${choices.map(([k, l]) => `<option value="${k}"${k === v ? " selected" : ""}>${h(l)}</option>`).join("")}</select></td>`;
}

/** La personne d'une ligne qui ne nomme qu'elle (`personne:<clé>`), si elle a un partage de cet agenda. */
function sharedPerson(cal: AgendaCalendar, line: AgendaRule): string {
  if (line.who.length !== 1 || !line.who[0].startsWith("personne:")) return "";
  const person = line.who[0].slice("personne:".length);
  return (cal.shares ?? []).some((s) => s.person === person) ? person : "";
}

function who(cal: AgendaCalendar, line: AgendaRule): string {
  const me = store.me.value?.person ?? "";
  const mine = line.who.includes("proprietaire") || (!!me && line.who.length === 1 && line.who[0] === `personne:${me}`);
  const words = mine ? "Toi" : line.who.length === 1 && line.who[0] === "elle" ? "Mika" : line.words?.who ?? line.who.join(", ");
  const person = sharedPerson(cal, line);
  const share = person ? (cal.shares ?? []).find((s) => s.person === person) : null;
  const sub = line.who.includes("elle") ? "elle seule" : share ? `<span class="ag-part-tag">partage · ${h(share.level === "lire" ? "lire" : share.level === "preparer" ? "lire et préparer" : "s'en servir")}</span>` : "";
  return `<div class="ag-qui"><span><b>${h(words)}</b>${sub ? `<small>${sub}</small>` : ""}</span></div>`;
}

export class AgendaRightsPart {
  private readonly tables = store.agendaRights;

  constructor(private readonly repaint: () => void) {}

  load(force = false): Promise<unknown> {
    return Promise.all([store.me.load(), store.agendaCalendars.load(force)]).then(() => Promise.all(ownedCalendars().map((c) => this.tables.get(c.key).load(force))));
  }

  invalidate(): void {
    this.tables.invalidate();
  }

  stamp(): string {
    return [store.agendaCalendars.version, ...ownedCalendars().map((c) => this.tables.get(c.key).version)].join(",");
  }

  /** Le groupe « Tes agendas » de la liste des ressources. */
  navGroup(selected: string | null): string {
    const cals = ownedCalendars();
    if (!cals.length) return "";
    return `<div class="group-label">Tes agendas</div><div class="nav-list">${cals.map((c) => {
      const got = this.tables.get(c.key).value;
      const line = got ? ownerLine(got, store.me.value?.person ?? "") : null;
      const alone = line ? [line.read, line.write === "seule"].filter(Boolean).length : 0;
      const ask = line ? [line.write === "accord", line.respond === "accord"].filter(Boolean).length : 0;
      return `<button type="button" data-res="${h(AG + c.key)}" class="${selected === AG + c.key ? "on" : ""}" title="Agenda « ${h(c.name)} » — ${h(providerShort(c))}"><span class="ag-sw ag-mx-sw" style="--c:var(--ag-${h(colorOf(c))})"></span><span class="ellipsis">${h(c.name)}</span>
        <span class="mx-mini">${alone ? `<i class="ok">${alone}</i>` : ""}${ask ? `<i class="warn">${ask}</i>` : ""}</span></button>`;
    }).join("")}</div>`;
  }

  /** Les choix du menu des ressources d'un téléphone. */
  options(selected: string | null): string {
    return ownedCalendars().map((c) => `<option value="${h(AG + c.key)}"${selected === AG + c.key ? " selected" : ""}>Agenda · ${h(c.name)}</option>`).join("");
  }

  /** Les tableaux : celui d'un agenda (`only`), sinon tous ; `q` filtre comme la recherche des outils. */
  sections(only: string | null, q: string): string {
    const cals = ownedCalendars().filter((c) => !only || AG + c.key === only);
    return cals.map((c) => this.section(c, q)).join("");
  }

  private section(c: AgendaCalendar, q: string): string {
    if (q.trim() && !norm(`agenda ${c.name} ${providerShort(c)} agenda_list agenda_events agenda_free agenda_create agenda_edit agenda_delete agenda_respond`).includes(norm(q))) return "";
    const got = this.tables.get(c.key);
    const t = got.value;
    const color = colorOf(c);
    const readOnly = !c.writable;
    const head = `<header class="mx-head"><span class="fam-ico ag-fam">${ico("agenda")}</span><div class="grow"><h3>Agenda · ${h(c.name)}</h3><p>${h(providerShort(c))} · à toi</p></div>
      <a class="btn xs ghost" href="#agenda/semaine">${ico("agenda", "xs")}Ouvrir</a>${c.can.share ? `<a class="btn xs ghost" href="#agenda/partager/${encodeURIComponent(c.key)}">${ico("user-plus", "xs")}Partager</a>` : ""}</header>`;
    if (!t) {
      return `<section class="mx-res ag-mx-res" style="--c:var(--ag-${h(color)})">${head}<div class="empty">${ico(got.error ? "alert" : "refresh")}<p>${got.error ? "Son tableau ne se lit pas." : "Chargement…"}</p></div></section>`;
    }
    const rules = ["Lues de haut en bas : la première ligne qui correspond décide", "Le propriétaire et le partage d'abord : une ligne n'ouvre jamais un agenda à qui il n'est pas"];
    if (readOnly) rules.push(c.kind === "ical" ? "Un abonnement est en lecture seule : ni toi ni elle n'y écrivez" : "Son fournisseur ne laisse pas écrire dans cet agenda");
    if ((c.shares ?? []).length) rules.push(`Partagé dans Mika avec ${(c.shares ?? []).map((s) => s.name).join(" et ")} : une ligne chacun`);
    if (!t.set) rules.push("Le tableau de départ, que son propriétaire et ses partages donnent");
    const lines = t.lines.map((l, i) => {
      const person = sharedPerson(c, l);
      return `<tr><td class="muted">${i + 1}</td><td>${who(c, l)}</td><td class="small ag-mx-ou">${h(l.words?.canal ?? l.canal.join(", "))}</td>
        <td class="small ag-mx-quand">${h(l.words?.when ?? (l.when.join(", ") || "toujours"))}</td>
        ${COLS.map(([col, , choices]) => cell(c.key, i, col, l, choices, readOnly)).join("")}
        <td class="actions">${person ? `<button class="btn xs ghost danger" type="button" data-agdroitret="${h(c.key)}|${h(person)}">Retirer</button>` : ""}</td></tr>`;
    }).join("");
    return `<section class="mx-res ag-mx-res" id="res-ag-${h(c.key.replace(/[^a-z0-9_-]/gi, "-"))}" style="--c:var(--ag-${h(color)})">${head}
      <ul class="mx-lines">${rules.map((r) => `<li>${h(r)}</li>`).join("")}</ul>
      <div class="mx-scroll"><table class="tbl ag-mx"><thead><tr><th>#</th><th>Qui</th><th>Par où</th><th>Quand</th>${COLS.map(([, l]) => `<th class="ag-mx-h">${h(l)}</th>`).join("")}<th></th></tr></thead>
        <tbody>${lines}<tr class="def"><td class="muted">—</td><td colspan="${COLS.length + 4}"><b>Par défaut</b> <span class="small muted">· ${t.default.read ? "elle le lit" : "fermé : personne d'autre"}</span></td></tr></tbody></table></div>
      <div class="ag-mx-foot">${t.set ? `<button class="btn xs" type="button" data-agdroitreset="${h(c.key)}">${ico("refresh", "xs")}Revenir au tableau de départ</button>` : ""}
        <span class="small muted">Ses outils : <code>agenda_list</code> <code>agenda_events</code> <code>agenda_free</code> (lire) · <code>agenda_create</code> <code>agenda_edit</code> <code>agenda_delete</code> (ajouter, modifier, supprimer) · <code>agenda_respond</code> (répondre). Avec ton accord : une carte dans le chat. Qui, par où et quand se règlent dans la console.</span></div></section>`;
  }

  /** Une case changée : le tableau entier repart (ses lignes, son défaut), puis se relit. */
  async change(spec: string, value: string): Promise<void> {
    const [key, index, col] = spec.split("|");
    const t = this.tables.get(key).value;
    if (!t) return;
    const strip = (l: AgendaRule): AgendaRule => {
      const out: AgendaRule = { ...l };
      delete out.words;
      return out;
    };
    const lines = t.lines.map((l, i) => {
      const out = strip(l);
      if (i !== Number(index)) return out;
      if (col === "read") return { ...out, read: value === "oui" };
      return { ...out, [col]: value };
    });
    try {
      const done = await saveAgendaRights(key, lines, strip(t.default));
      toast(done.message, { ico: "shield" });
    } catch (err) {
      toastFailure(err);
    }
    this.tables.invalidate(key);
    await this.tables.get(key).load(true);
    this.repaint();
  }

  async withdraw(spec: string): Promise<void> {
    const [key, person] = spec.split("|");
    const cal = ownedCalendars().find((c) => c.key === key);
    const name = cal?.shares?.find((s) => s.person === person)?.name ?? "cette personne";
    const sure = await confirmModal({ title: "Retirer le partage", text: `${name} ne verra plus « ${cal?.name ?? ""} » dans son Agenda, et sa ligne quitte le tableau.`, ok: "Retirer", danger: true });
    if (!sure) return;
    try {
      const done = await setShare("agenda", key, person, "");
      toast(done.message || "Partage retiré.", { ico: "x" });
    } catch (err) {
      toastFailure(err);
    }
    store.agendaCalendars.invalidate();
    this.tables.invalidate(key);
    await this.load(true);
    this.repaint();
  }

  async reset(key: string): Promise<void> {
    try {
      const done = await resetAgendaRights(key);
      toast(done.message, { ico: "refresh" });
    } catch (err) {
      toastFailure(err);
    }
    this.tables.invalidate(key);
    await this.tables.get(key).load(true);
    this.repaint();
  }
}
