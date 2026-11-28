/**
 * Créer et modifier un événement (la fenêtre de la maquette validée) : le titre, quand (journée entière, le fuseau),
 * la répétition (et « Personnalisée »), le lieu, un lien de visio collé, la description ; l'agenda où il s'écrit (ceux
 * où l'on écrit), ses participants (ses correspondants, ou une adresse), les rappels de son fournisseur (Google,
 * Outlook, CalDAV : notification ou e-mail ; l'agenda du système n'en a pas), « Mika te le rappelle », occupé ou
 * disponible, privé. Une modification n'envoie que ce qui a changé ; une série demande sa portée (cet événement, celui-ci
 * et les suivants, tous). Aussi : supprimer (et sa portée), et répondre avec un mot.
 */
import type { AgendaCalendar, AgendaItem, Alert, EventFields, MikaReminder, Proposal, Scope } from "../../api/agenda";
import { AGENDA_LIMITS } from "../../api/agenda";
import { mikaAvatar } from "../../mika/face";
import { $, $$, h } from "../../shell/dom";
import { closeModal, openMenu, openModal } from "../../shell/float";
import { ico } from "../../shell/icons";
import { bindRecipients, chip, readRecipients } from "../../shared/recipients";
import { addDays, hm, localInput, shortDay } from "./dates";
import {
  alertMinutes,
  alertUnit,
  choiceOf,
  colorOf,
  customOf,
  mikaReminderWords,
  MIKA_REMINDERS,
  providerShort,
  repeatChoices,
  ruleOf,
  ruleWords,
  whereWords,
  type CustomRule,
  type Occ,
  type RepeatChoice,
} from "./model";

export type FormMode = "nouveau" | "modifier" | "dupliquer" | "proposition";

export interface FormSpec {
  mode: FormMode;
  today: string;
  /** Le fuseau du serveur : ce qu'on écrit s'y lit, sauf un autre choisi. */
  zone: string;
  /** Les agendas où elle écrit (le choix de l'agenda). */
  writable: AgendaCalendar[];
  calendars: AgendaCalendar[];
  /** L'agenda de départ. */
  calendar: string;
  occ?: Occ;
  item?: AgendaItem;
  proposal?: Proposal;
  /** Un créneau choisi dans la grille : son jour et sa minute. */
  slot?: { day: string; minute: number };
  nowMinute: number;
}

/** Ce que le formulaire tient (qu'une fenêtre rouverte retrouve). */
export interface FormValues {
  calendar: string;
  title: string;
  d1: string;
  h1: string;
  d2: string;
  h2: string;
  allDay: boolean;
  zone: string;
  repeat: RepeatChoice;
  custom: CustomRule;
  location: string;
  conference: string;
  description: string;
  invite: { name: string; address: string }[];
  reminders: Alert[];
  /** Les rappels du fournisseur ont été touchés (sinon ils ne partent pas : ceux de l'agenda chez lui, ou tels quels). */
  remindersTouched: boolean;
  remind: MikaReminder;
  free: boolean;
  private: boolean;
}

export interface FormResult {
  calendar: string;
  fields: EventFields;
  /** Une série : sa portée (demandée après). */
  recurring: boolean;
}

const ZONES = ["Europe/Paris", "Europe/London", "Europe/Brussels", "Europe/Berlin", "America/New_York", "America/Montreal", "Asia/Tokyo", "UTC"];

/** Les valeurs de départ du formulaire. */
export function initialValues(spec: FormSpec): FormValues {
  const o = spec.occ;
  const item = spec.item;
  const draft = spec.proposal?.draft;
  const zone = (item && !item.all_day && item.zone) || (draft && draft.zone) || spec.zone;
  let d1: string;
  let h1: string;
  let d2: string;
  let h2: string;
  let allDay = false;
  if (o) {
    allDay = o.allDay && (item ? item.all_day : !!draft?.all_day);
    if (allDay) {
      d1 = o.day;
      d2 = o.last;
      h1 = "09:00";
      h2 = "10:00";
    } else {
      [d1, h1] = localInput(o.startMs, zone).split("T");
      [d2, h2] = localInput(o.endMs, zone).split("T");
    }
  } else {
    const slot = spec.slot;
    const day = slot?.day ?? spec.today;
    const start = slot ? slot.minute : day === spec.today ? Math.min(23 * 60, Math.ceil((spec.nowMinute + 1) / 30) * 30) : 600;
    d1 = day;
    d2 = start + 60 >= 1440 ? addDays(day, 1) : day;
    h1 = hm(start);
    h2 = hm((start + 60) % 1440);
  }
  const rule = item?.rule || draft?.rule || "";
  const repeat = spec.mode === "dupliquer" ? choiceOf(rule, d1) : choiceOf(rule, d1);
  const cal = spec.calendars.find((c) => c.key === spec.calendar);
  const invite = item
    ? item.participants.filter((p) => !p.me && p.address).map((p) => ({ name: p.name, address: p.address }))
    : (draft?.invite ?? []).map((address) => ({ name: "", address }));
  return {
    calendar: spec.calendar,
    title: spec.mode === "dupliquer" ? `${item?.title || o?.title || ""}${spec.calendar === item?.calendar ? " (copie)" : ""}` : item?.title ?? draft?.title ?? "",
    d1, h1, d2, h2, allDay, zone,
    repeat,
    custom: customOf(rule || ruleOf("semaine", d1), d1),
    location: item?.location ?? draft?.location ?? "",
    conference: item?.conference ?? "",
    description: item?.description ?? draft?.description ?? "",
    invite: spec.mode === "dupliquer" ? [] : invite,
    reminders: item ? [...(item.reminders ?? [])] : [...(cal?.provider_reminders?.defaults ?? [])],
    remindersTouched: false,
    remind: (spec.mode === "dupliquer" ? "" : item?.remind ?? (spec.proposal?.remind as MikaReminder | null) ?? "") as MikaReminder,
    free: item ? !item.busy : false,
    private: item ? item.private : false,
  };
}

function zoneChoices(current: string): string[] {
  return ZONES.includes(current) ? ZONES : [current, ...ZONES];
}

function zoneLabel(zone: string): string {
  return zone.replace(/_/g, " ").replace("/", " · ");
}

function alertRow(a: Alert, i: number, email: boolean): string {
  const { n, unit } = alertUnit(a.minutes);
  return `<div class="row" data-agalert="${i}"><select class="sm-select" data-alert-method aria-label="Comment">${email || a.method === "email"
    ? `<option value="notification"${a.method === "notification" ? " selected" : ""}>Notification</option><option value="email"${a.method === "email" ? " selected" : ""}>E-mail</option>`
    : '<option value="notification" selected>Notification</option>'}</select>
    <input type="number" min="0" value="${n}" class="ag-n" data-alert-n aria-label="Combien">
    <select class="sm-select" data-alert-unit aria-label="Unité">${["minutes", "heures", "jours"].map((u) => `<option${u === unit ? " selected" : ""}>${u}</option>`).join("")}</select> avant
    <button class="btn xs icon ghost" type="button" data-agrappelx="${i}" title="Retirer" aria-label="Retirer ce rappel">${ico("x", "xs")}</button></div>`;
}

function providerWho(cal: AgendaCalendar | undefined): string {
  return cal ? ({ google: "de Google", microsoft: "d'Outlook", caldav: "du serveur CalDAV" } as Record<string, string>)[cal.kind] ?? "" : "";
}

function remindersBox(cal: AgendaCalendar | undefined, values: FormValues): string {
  if (!cal) return "";
  const max = cal.provider_reminders?.max ?? 0;
  if (cal.kind === "systeme") return '<p class="small muted">L\'agenda du système n\'envoie rien lui-même : c\'est Mika qui te le rappelle.</p>';
  if (!max) return `<p class="small muted">${h(cal.name)} ne garde pas de rappel d'ici.</p>`;
  const email = cal.provider_reminders?.email ?? false;
  const rows = values.reminders.map((a, i) => alertRow(a, i, email)).join("");
  const one = max === 1 ? '<p class="small muted">Outlook n\'en garde qu\'un, une notification.</p>' : "";
  return `${rows || '<p class="small muted">Aucun.</p>'}${one}`;
}

function formBody(spec: FormSpec, v: FormValues): string {
  const cal = spec.calendars.find((c) => c.key === v.calendar);
  const color = colorOf(cal);
  const owner = cal?.level === "proprietaire";
  const custom = v.custom;
  const days = ["L", "M", "M", "J", "V", "S", "D"];
  const prop = spec.mode === "proposition";
  const max = cal?.provider_reminders?.max ?? 0;
  return `<div class="ag-form">
    ${prop ? `<div class="mika-note small">${mikaAvatar("xs")}<div class="mn-body"><div class="mn-title">${ico("sparkle", "xs")}Ce que Mika propose</div><span>Change ce que tu veux : « Ajouter » l'enregistre dans ton agenda, avec tes changements.</span></div></div>` : ""}
    <input class="ag-titre" data-f="title" placeholder="Ajouter un titre" value="${h(v.title)}" maxlength="${AGENDA_LIMITS.title}" aria-label="Titre">
    <div class="ag-form-cols"><div class="ag-fcol">
      <div class="ag-frow">${ico("clock")}<div class="ag-fval">
        <div class="row wrap ag-dates"><input type="date" data-f="d1" value="${h(v.d1)}" aria-label="Début, le jour"><input type="time" data-f="h1" class="ag-h" value="${h(v.h1)}" aria-label="Début, l'heure"${v.allDay ? " hidden" : ""}><span class="muted">→</span>
          <input type="time" data-f="h2" class="ag-h" value="${h(v.h2)}" aria-label="Fin, l'heure"${v.allDay ? " hidden" : ""}><input type="date" data-f="d2" value="${h(v.d2)}" aria-label="Fin, le jour"></div>
        <div class="row wrap"><label class="row small"><span class="switch"><input type="checkbox" data-f="allDay"${v.allDay ? " checked" : ""}><i></i></span>Journée entière</label>
          <select class="sm-select" data-f="zone" title="Le fuseau horaire" aria-label="Le fuseau horaire"${v.allDay ? " hidden" : ""}>${zoneChoices(v.zone).map((z) => `<option value="${h(z)}"${z === v.zone ? " selected" : ""}>${h(zoneLabel(z))}</option>`).join("")}</select></div></div></div>
      <div class="ag-frow">${ico("repeat")}<div class="ag-fval"><select data-f="repeat" aria-label="La répétition">${repeatChoices(v.d1).map(([k, l]) => `<option value="${k}"${k === v.repeat ? " selected" : ""}>${h(l)}</option>`).join("")}</select>
        <div class="ag-perso" data-recperso${v.repeat === "perso" ? "" : " hidden"}><div class="row wrap small">Tous les <input type="number" min="1" value="${custom.interval}" class="ag-n" data-f="interval" aria-label="Tous les"> <select class="sm-select" data-f="unit" aria-label="Unité">${(["jours", "semaines", "mois", "ans"] as const).map((u) => `<option${u === custom.unit ? " selected" : ""}>${u}</option>`).join("")}</select><span data-jsemrow${custom.unit === "semaines" ? "" : " hidden"}>, le
          <span class="ag-jsem">${days.map((x, i) => `<button type="button" class="${custom.days.includes((i + 1) % 7) ? "on" : ""}" data-agjsem="${(i + 1) % 7}" aria-pressed="${custom.days.includes((i + 1) % 7)}">${x}</button>`).join("")}</span></span></div>
          <div class="row wrap small">Se termine <select class="sm-select" data-f="ends" aria-label="Se termine"><option value="jamais"${custom.ends === "jamais" ? " selected" : ""}>jamais</option><option value="le"${custom.ends === "le" ? " selected" : ""}>le…</option><option value="apres"${custom.ends === "apres" ? " selected" : ""}>après…</option></select>
            <input type="date" data-f="until" value="${h(custom.until || addDays(v.d1, 90))}" class="ag-fin-rec" aria-label="Le dernier jour"${custom.ends === "le" ? "" : " hidden"}><span data-countrow${custom.ends === "apres" ? "" : " hidden"}><input type="number" min="1" value="${custom.count}" class="ag-n" data-f="count" aria-label="Combien de fois"> fois</span></div></div></div></div>
      <div class="ag-frow">${ico("pin")}<div class="ag-fval"><input data-f="location" placeholder="Ajouter un lieu" value="${h(v.location)}" maxlength="${AGENDA_LIMITS.location}" aria-label="Lieu"></div></div>
      <div class="ag-frow">${ico("video")}<div class="ag-fval"><select data-f="visio" aria-label="La visio"><option value=""${v.conference ? "" : " selected"}>Pas de visio</option><option value="lien"${v.conference ? " selected" : ""}>Coller un lien…</option></select>
        <input data-f="conference" class="mono" placeholder="https://…" value="${h(v.conference)}" maxlength="${AGENDA_LIMITS.link}" aria-label="Le lien de la réunion"${v.conference ? "" : " hidden"}></div></div>
      <div class="ag-frow">${ico("file")}<div class="ag-fval"><textarea rows="4" data-f="description" placeholder="Ajouter une description" maxlength="${AGENDA_LIMITS.description}" aria-label="Description">${h(v.description)}</textarea></div></div>
    </div>
    <div class="ag-fcol ag-fcol-d">
      <div class="field"><span>Agenda</span><button type="button" class="ag-pick" data-agpick${spec.mode === "modifier" ? " disabled" : ""}>${`<span class="ag-sw" style="--c:var(--ag-${h(color)})"></span>`}<b>${h(cal?.name ?? "")}</b><small>${h(cal ? providerShort(cal) : "")}</small>${spec.mode === "modifier" ? "" : ico("chev-down", "sm")}</button>
        <small class="muted">${spec.mode === "modifier" ? "Un événement reste dans son agenda : pour le mettre ailleurs, duplique-le." : "Seuls ceux où tu peux écrire. Pas les abonnements, ni ceux qu'on te partage en lecture, ni celui de Mika."}</small></div>
      <div class="field ag-ppl-f" data-compose><span>Participants</span><div class="rcpt" data-rcpt="to">${v.invite.map((p) => chip(p)).join("")}<input data-ac placeholder="Un nom, une adresse…" autocomplete="off" aria-label="Participants"></div>
        <div class="ac-pop" data-acpop hidden></div>
        <small class="muted">${cal?.kind === "systeme" ? "Une personne qui a un compte ici reçoit l'invitation dans son Agenda ; les autres, rien." : "L'invitation part par l'agenda choisi."}</small></div>
      <div class="field"><span>Rappels <span class="muted" data-agrfourn>${h(providerWho(cal))}</span></span><div class="ag-rappels" data-agrappels>${remindersBox(cal, v)}</div>
        <button class="btn xs ghost ag-add" type="button" data-agrappeladd${max && v.reminders.length < max ? "" : " hidden"}>${ico("plus", "xs")}Ajouter un rappel</button></div>
      ${owner ? `<div class="field ag-f-mika"><span>${ico("sparkle", "xs")}Mika te le rappelle</span><select data-f="remind" aria-label="Mika te le rappelle"><option value=""${v.remind === "" ? " selected" : ""}>Comme l'agenda (${h(mikaReminderWords(cal?.reminder ?? "non"))})</option>${MIKA_REMINDERS.map(([k, l]) => `<option value="${k}"${k === v.remind ? " selected" : ""}>${h(l)}</option>`).join("")}</select>
        <small>Elle te l'écrit dans le chat ou par une notification, comme ses autres rappels.</small></div>` : ""}
      <div class="row wrap ag-segs"><div class="field"><span>Afficher comme</span><div class="seg" data-seg="agdispo"><button type="button" data-v="occupe" aria-pressed="${!v.free}">Occupé</button><button type="button" data-v="libre" aria-pressed="${v.free}">Disponible</button></div></div>
        <div class="field"><span>Visibilité</span><div class="seg" data-seg="agvis"><button type="button" data-v="defaut" aria-pressed="${!v.private}">Par défaut</button><button type="button" data-v="prive" aria-pressed="${v.private}">Privée</button></div></div></div>
    </div></div></div>`;
}

function footWords(cal: AgendaCalendar | undefined): string {
  return cal ? `Enregistré dans « ${cal.name} », il part tout de suite ${whereWords(cal.kind)}.` : "";
}

/** Ce que le formulaire dit, lu dans la fenêtre. */
function read(el: HTMLElement, v: FormValues): FormValues {
  const f = (name: string) => $<HTMLInputElement>(`[data-f="${name}"]`, el);
  const out = { ...v };
  out.title = f("title")?.value ?? "";
  out.d1 = f("d1")?.value ?? v.d1;
  out.h1 = f("h1")?.value ?? v.h1;
  out.d2 = f("d2")?.value ?? v.d2;
  out.h2 = f("h2")?.value ?? v.h2;
  out.allDay = f("allDay")?.checked ?? v.allDay;
  out.zone = f("zone")?.value || v.zone;
  out.repeat = (f("repeat")?.value ?? "") as RepeatChoice;
  out.custom = {
    interval: Number(f("interval")?.value) || 1,
    unit: (f("unit")?.value ?? "semaines") as CustomRule["unit"],
    days: $$<HTMLElement>("[data-agjsem].on", el).map((b) => Number(b.dataset.agjsem)),
    ends: (f("ends")?.value ?? "jamais") as CustomRule["ends"],
    until: f("until")?.value ?? "",
    count: Number(f("count")?.value) || 1,
  };
  out.location = f("location")?.value ?? "";
  out.conference = f("visio")?.value === "lien" ? (f("conference")?.value ?? "").trim() : "";
  out.description = $<HTMLTextAreaElement>('[data-f="description"]', el)?.value ?? "";
  out.invite = readRecipients(el, "to");
  out.reminders = $$<HTMLElement>("[data-agalert]", el).map((row) => ({
    method: ($<HTMLSelectElement>("[data-alert-method]", row)?.value ?? "notification") as Alert["method"],
    minutes: alertMinutes(Number($<HTMLInputElement>("[data-alert-n]", row)?.value), $<HTMLSelectElement>("[data-alert-unit]", row)?.value ?? "minutes"),
  }));
  out.remind = (f("remind")?.value ?? v.remind) as MikaReminder;
  out.free = $<HTMLElement>('[data-seg="agdispo"] [aria-pressed="true"]', el)?.dataset.v === "libre";
  out.private = $<HTMLElement>('[data-seg="agvis"] [aria-pressed="true"]', el)?.dataset.v === "prive";
  return out;
}

/** Un texte tel qu'une zone de texte le rend : ses fins de ligne en « \n », sans le saut de ligne de tête que le HTML
 *  avale. Une description venue d'un fournisseur (« \r\n ») et relue ainsi n'a pas changé : renvoyée, elle écraserait
 *  sa mise en forme chez lui (le corps HTML d'Outlook), ou serait refusée si elle est longue. */
function asTyped(text: string): string {
  return text.replace(/\r\n?/g, "\n").replace(/^\n/, "");
}

/** Ce qui part : tout pour une création ; pour une modification, ce qui a changé depuis le départ. */
export function fieldsOf(mode: FormMode, v: FormValues, start: FormValues, owner: boolean): EventFields {
  const when = v.allDay
    ? { start: v.d1, end: v.d2 < v.d1 ? v.d1 : v.d2, all_day: true }
    : { start: `${v.d1}T${v.h1}`, end: `${v.d2}T${v.h2}`, all_day: false, zone: v.zone };
  const rule = ruleOf(v.repeat, v.d1, v.custom);
  const all: EventFields = {
    title: v.title.trim(),
    ...when,
    location: v.location.trim(),
    description: v.description,
    conference: v.conference,
    rule,
    invite: v.invite.map((p) => p.address),
    free: v.free,
    private: v.private,
  };
  if (owner) all.remind = v.remind;
  if (v.remindersTouched) all.reminders = v.reminders;
  if (mode !== "modifier") return all;
  const out: EventFields = {};
  const before = fieldsOf("nouveau", start, start, owner);
  if (all.title !== before.title) out.title = all.title;
  if (all.start !== before.start || all.end !== before.end || all.all_day !== before.all_day || all.zone !== before.zone) {
    out.start = all.start;
    out.end = all.end;
    out.all_day = all.all_day;
    if (!v.allDay) out.zone = v.zone;
  }
  for (const k of ["location", "conference", "rule"] as const) if (all[k] !== before[k]) out[k] = all[k];
  if (asTyped(all.description ?? "") !== asTyped(before.description ?? "")) out.description = all.description;
  if (JSON.stringify(all.invite) !== JSON.stringify(before.invite)) out.invite = all.invite;
  if (all.free !== before.free) out.free = all.free;
  if (all.private !== before.private) out.private = all.private;
  if (owner && all.remind !== before.remind) out.remind = all.remind;
  if (v.remindersTouched) out.reminders = v.reminders;
  return out;
}

export interface FormHandlers {
  /** Enregistrer ; rend vrai si c'est fait (la fenêtre se ferme). */
  save: (result: FormResult, values: FormValues) => Promise<boolean>;
  /** La fenêtre fermée sans enregistrer. */
  closed: () => void;
}

/** La fenêtre « Nouvel événement », « Modifier l'événement », « Dupliquer », « Modifier ce que Mika propose ». */
export function openEventForm(spec: FormSpec, handlers: FormHandlers, values?: FormValues): void {
  const start = initialValues(spec);
  let v = values ?? start;
  const prop = spec.mode === "proposition";
  const title = spec.mode === "modifier" ? "Modifier l'événement" : spec.mode === "dupliquer" ? "Dupliquer l'événement" : prop ? "Modifier ce que Mika propose" : "Nouvel événement";
  const cal = () => spec.calendars.find((c) => c.key === v.calendar);
  const el = openModal({
    title,
    size: "wide",
    body: formBody(spec, v),
    foot: `<span class="grow small muted" data-agpied>${h(footWords(cal()))}</span><button class="btn" type="button" data-close>Annuler</button>
      <button class="btn primary" type="button" data-agsave>${prop ? `${ico("check", "sm")}Ajouter` : "Enregistrer"}</button>`,
  });
  el.classList.add("ag-modal");
  let saved = false;
  const scrim = el.parentElement;
  const watch = new MutationObserver(() => {
    if (!scrim?.isConnected) {
      watch.disconnect();
      if (!saved) handlers.closed();
    }
  });
  if (scrim?.parentElement) watch.observe(scrim.parentElement, { childList: true });
  bindRecipients(el);
  const f = (name: string) => $<HTMLInputElement>(`[data-f="${name}"]`, el);
  const paintReminders = () => {
    const c = cal();
    const box = $<HTMLElement>("[data-agrappels]", el);
    if (box) box.innerHTML = remindersBox(c, v);
    const add = $<HTMLElement>("[data-agrappeladd]", el);
    const max = c?.provider_reminders?.max ?? 0;
    if (add) add.hidden = !max || v.reminders.length >= max;
  };
  el.addEventListener("change", (e) => {
    const t = e.target as HTMLElement;
    if (t.matches('[data-f="allDay"]')) {
      const on = (t as HTMLInputElement).checked;
      for (const x of $$<HTMLElement>(".ag-h", el)) x.hidden = on;
      const zone = f("zone");
      if (zone) zone.hidden = on;
    }
    if (t.matches('[data-f="repeat"]')) $<HTMLElement>("[data-recperso]", el)!.hidden = (t as HTMLSelectElement).value !== "perso";
    if (t.matches('[data-f="unit"]')) $<HTMLElement>("[data-jsemrow]", el)!.hidden = (t as HTMLSelectElement).value !== "semaines";
    if (t.matches('[data-f="ends"]')) {
      const value = (t as HTMLSelectElement).value;
      f("until")!.hidden = value !== "le";
      $<HTMLElement>("[data-countrow]", el)!.hidden = value !== "apres";
    }
    if (t.matches('[data-f="visio"]')) {
      const link = f("conference")!;
      link.hidden = (t as HTMLSelectElement).value !== "lien";
      if (!link.hidden) link.focus();
    }
    if (t.matches('[data-f="d1"]')) {
      // le jour de début change : la fin suit (même durée), et les choix de répétition se redisent pour ce jour
      const before = v.d1;
      const now = (t as HTMLInputElement).value;
      const d2 = f("d2");
      if (before && now && d2) {
        const shift = (Date.parse(`${now}T00:00:00Z`) - Date.parse(`${before}T00:00:00Z`)) / 86_400_000;
        if (Number.isFinite(shift)) d2.value = addDays(d2.value || before, shift);
      }
      v = { ...v, d1: now };
      const rep = f("repeat") as unknown as HTMLSelectElement | null;
      if (rep) {
        const chosen = rep.value;
        rep.innerHTML = repeatChoices(now).map(([k, l]) => `<option value="${k}"${k === chosen ? " selected" : ""}>${h(l)}</option>`).join("");
      }
    }
    if (t.closest("[data-agalert]")) v.remindersTouched = true;
  });
  el.addEventListener("input", (e) => {
    if ((e.target as HTMLElement).closest("[data-agalert]")) v.remindersTouched = true;
  });
  el.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    const day = t.closest<HTMLElement>("[data-agjsem]");
    if (day) {
      day.classList.toggle("on");
      day.setAttribute("aria-pressed", String(day.classList.contains("on")));
    }
    const x = t.closest<HTMLElement>("[data-agrappelx]");
    if (x) {
      v = read(el, v);
      v.reminders = v.reminders.filter((_a, i) => i !== Number(x.dataset.agrappelx));
      v.remindersTouched = true;
      paintReminders();
    }
    if (t.closest("[data-agrappeladd]")) {
      v = read(el, v);
      v.reminders = [...v.reminders, { method: "notification", minutes: v.reminders.length ? 1440 : 30 }];
      v.remindersTouched = true;
      paintReminders();
    }
    const pick = t.closest<HTMLButtonElement>("[data-agpick]");
    if (pick && !pick.disabled) {
      openMenu(pick, [
        { header: "Où tu peux écrire" },
        ...spec.writable.map((c) => ({ html: `<button class="mi" type="button" data-agpicki="${h(c.key)}"${c.key === v.calendar ? ' aria-checked="true"' : ""}><span class="ag-sw" style="--c:var(--ag-${h(colorOf(c))})"></span><span>${h(c.name)}</span><span class="cnt">${h(providerShort(c))}</span></button>` })),
      ], { align: "left" });
    }
  });
  // le menu des agendas vit hors de la fenêtre
  const onPick = (e: Event) => {
    const b = (e.target as Element).closest?.<HTMLElement>("[data-agpicki]");
    if (!b || !el.isConnected) return;
    document.querySelector(".menu")?.remove();
    v = read(el, v);
    v.calendar = b.dataset.agpicki ?? v.calendar;
    const c = cal();
    if (!v.remindersTouched) v.reminders = [...(c?.provider_reminders?.defaults ?? [])];
    const host = $<HTMLElement>("[data-agpick]", el);
    if (host && c) host.innerHTML = `<span class="ag-sw" style="--c:var(--ag-${h(colorOf(c))})"></span><b>${h(c.name)}</b><small>${h(providerShort(c))}</small>${ico("chev-down", "sm")}`;
    $<HTMLElement>("[data-agpied]", el)!.textContent = footWords(c);
    const who = $<HTMLElement>("[data-agrfourn]", el);
    if (who) who.textContent = providerWho(c);
    paintReminders();
    const remind = f("remind");
    if (remind && c) (remind.firstElementChild as HTMLOptionElement).textContent = `Comme l'agenda (${mikaReminderWords(c.reminder)})`;
  };
  document.addEventListener("click", onPick, true);
  const stop = new MutationObserver(() => {
    if (!el.isConnected) {
      stop.disconnect();
      document.removeEventListener("click", onPick, true);
    }
  });
  if (scrim?.parentElement) stop.observe(scrim.parentElement, { childList: true });
  const button = $<HTMLButtonElement>("[data-agsave]", el)!;
  button.addEventListener("click", () => {
    v = read(el, v);
    const owner = cal()?.level === "proprietaire";
    const result: FormResult = {
      calendar: v.calendar,
      fields: fieldsOf(spec.mode, v, start, owner),
      recurring: spec.mode === "modifier" && !!spec.item?.recurring && !!spec.item.occurrence,
    };
    button.disabled = true;
    void handlers.save(result, v).then((ok) => {
      if (ok) {
        saved = true;
        closeModal();
      } else if (button.isConnected) button.disabled = false;
    });
  });
  if (!v.title) window.setTimeout(() => f("title")?.focus(), 40);
}

/** La portée d'un geste sur une série : « Cet événement », « Celui-ci et les suivants », « Tous les événements ». */
export function askScope(o: Occ, what: "modifier" | "supprimer", today: string, withFollowing = true): Promise<Scope | null> {
  return new Promise((resolve) => {
    const item = o.item;
    const words = item?.rule ? ruleWords(item.rule, o.day, today).toLowerCase() : "elle fait partie d'une série";
    const el = openModal({
      title: what === "supprimer" ? "Supprimer un événement récurrent" : "Modifier un événement récurrent",
      size: "narrow",
      body: `<div class="stack ag-recq"><p class="small text-2">« ${h(o.title)} » se répète : ${h(words)}.</p>
        <label class="row"><input type="radio" name="agrq" value="un" checked> Cet événement <span class="muted small">· ${h(shortDay(o.day))}</span></label>
        ${withFollowing ? '<label class="row"><input type="radio" name="agrq" value="suivants"> Celui-ci et les suivants</label>' : ""}
        <label class="row"><input type="radio" name="agrq" value="tous"> Tous les événements</label>
        ${item && item.participants.length > 1 ? '<p class="small muted">Les participants sont prévenus par l\'agenda.</p>' : ""}</div>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn ${what === "supprimer" ? "danger" : "primary"}" type="button" data-ok>${what === "supprimer" ? "Supprimer" : "OK"}</button>`,
    });
    el.classList.add("ag-modal");
    let answered = false;
    el.querySelector("[data-ok]")?.addEventListener("click", () => {
      answered = true;
      const got = (el.querySelector<HTMLInputElement>('input[name="agrq"]:checked')?.value ?? "un") as Scope;
      closeModal();
      resolve(got);
    });
    const scrim = el.parentElement;
    const watch = new MutationObserver(() => {
      if (!scrim?.isConnected) {
        watch.disconnect();
        if (!answered) resolve(null);
      }
    });
    if (scrim?.parentElement) watch.observe(scrim.parentElement, { childList: true });
  });
}

/** Répondre à une invitation avec un mot (« Modifier le mot » de la réponse que Mika a préparée). */
export function askAnswer(to: string, answer: string, comment: string, via: string): Promise<{ answer: "oui" | "peut" | "non"; comment: string } | null> {
  return new Promise((resolve) => {
    const words = [["oui", "Accepter"], ["peut", "Peut-être"], ["non", "Refuser"]] as const;
    const el = openModal({
      title: `Répondre à ${to}`,
      size: "narrow",
      body: `<div class="stack"><div class="seg" data-seg="agrepm">${words.map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${k === answer}">${l}</button>`).join("")}</div>
        <label class="field"><span>Le mot qui part avec</span><textarea rows="3" data-agmot maxlength="${AGENDA_LIMITS.comment}">${h(comment)}</textarea></label><p class="small muted">Préparé par Mika ; il part ${h(via)}.</p></div>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("send", "sm")}Envoyer</button>`,
    });
    let answered = false;
    el.querySelector("[data-ok]")?.addEventListener("click", () => {
      answered = true;
      const got = (el.querySelector<HTMLElement>('[data-seg="agrepm"] [aria-pressed="true"]')?.dataset.v ?? answer) as "oui" | "peut" | "non";
      const text = el.querySelector<HTMLTextAreaElement>("[data-agmot]")?.value ?? "";
      closeModal();
      resolve({ answer: got, comment: text.trim() });
    });
    const scrim = el.parentElement;
    const watch = new MutationObserver(() => {
      if (!scrim?.isConnected) {
        watch.disconnect();
        if (!answered) resolve(null);
      }
    });
    if (scrim?.parentElement) watch.observe(scrim.parentElement, { childList: true });
  });
}

