/**
 * L'agenda dans le chat (la maquette validée `maquette/ecrans/agenda-chat.js`) : la carte d'accord d'un ajout que Mika
 * propose (`capability: "agenda.write"`, `protocole-chat.md` § 4) montre l'événement — son titre, quand, où, « Mika te
 * le rappelle » —, mène à « Modifier » et à la proposition qui attend dans l'Agenda. Ses boutons sont ceux de toute
 * carte : seuls eux décident. Ce que la carte montre se lit dans `GET /api/moi/agenda/proposals` (le même numéro).
 */
import type { AgendaCalendar, Proposal } from "../../api/agenda";
import { fetchProposals } from "../../api/agenda";
import * as store from "../../shared/store";
import { localOf } from "./dates";
import { colorOf, mikaReminderWords, occOfProposal, whenWords } from "./model";

/** Ce que la carte d'un ajout montre. */
export interface AgendaCardData {
  calendar: string;
  color: string;
  title: string;
  when: string;
  place: string;
  remind: string;
  /** La proposition dans l'Agenda, et sa modification (un ajout seulement). */
  href: string;
  edit: string;
}

/** Les cartes d'un ajout, par numéro : lues dans ce que Mika propose. Pur. */
export function agendaCards(items: readonly Proposal[], calendars: readonly AgendaCalendar[], zone: string, now: number): Map<number, AgendaCardData> {
  const out = new Map<number, AgendaCardData>();
  const today = localOf(now, zone).day;
  for (const p of items) {
    if (p.op !== "ajouter" || !p.draft) continue;
    const o = occOfProposal(p, zone);
    if (!o) continue;
    const cal = calendars.find((c) => c.key === p.calendar);
    out.set(p.id, {
      calendar: cal?.name ?? "ton agenda",
      color: colorOf(cal),
      title: p.draft.title || "(sans titre)",
      when: whenWords(o, today),
      place: p.draft.location,
      remind: p.remind && p.remind !== "non" ? mikaReminderWords(p.remind) : "",
      href: `#agenda/proposition/${p.id}`,
      edit: `#agenda/modifier/proposition/${p.id}`,
    });
  }
  return out;
}

/** Les cartes d'un ajout de l'agenda, lues pour les numéros donnés (une lecture ; rien si l'agenda n'est pas branché). */
export async function readAgendaCards(ids: readonly number[]): Promise<Map<number, AgendaCardData>> {
  if (!ids.length) return new Map();
  try {
    const [got] = await Promise.all([fetchProposals(), store.agendaCalendars.load()]);
    const cals = store.agendaCalendars.value;
    return agendaCards(got.items.filter((p) => ids.includes(p.id)), cals?.calendars ?? [], cals?.zone ?? "UTC", Date.now());
  } catch {
    // sans l'agenda, la carte reste celle de toute demande d'accord
    return new Map();
  }
}
