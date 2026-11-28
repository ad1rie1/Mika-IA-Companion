"""Ce qu'elle sait d'un contact, à partir de ce qu'elle lit (ADR 0298, lot 6) : le processus ``contacts.portrait``.

- **Qui** : seulement une personne avec qui un compte échange vraiment — des messages dans les deux sens, dans la
  fenêtre (``ContactsParams.window_us``, 30 jours) : dans Teams, en tête-à-tête, ou dans un petit groupe où la personne
  du compte lui a répondu (``TeamsPort.exchanged`` : jamais un canal) ; au courrier, elle a écrit à la boîte et la
  boîte lui a écrit (``MailPort.exchanged``) ; sur le téléphone, en tête-à-tête où la personne a écrit elle-même
  (``ContactsState.replied``), ou dans un petit groupe (``GROUP_MAX`` personnes au plus) où elle a écrit après lui. Un
  expéditeur qui ne fait qu'écrire n'en est pas ; une organisation non plus.
- **Ce qu'elle relit** : ses derniers messages dans la fenêtre, par vue (source, compte) — ``messages`` au plus, bornés
  à ``chars`` caractères, chacun avec sa conversation ou son objet et sa date. Charger l'historique n'en fait relire
  que la fin : rien d'avant la fenêtre ne compte, sauf si l'opératrice coche « Relire tout l'historique »
  (``history`` : sans fenêtre, des bornes plus larges).
- **Une fiche qui s'enrichit** (ADR 0303) : le modèle reçoit ce qu'elle en sait déjà dans cette vue (ses faits
  d'avant, « fait 1 »… ; jamais un fait oublié, ni un fait dont le message n'est plus — ``alive``) et rend ce que les
  messages lui apprennent : des faits nouveaux, des faits d'avant récrits (« avant ») ou retirés (« laisse ») ; un
  fait d'avant qu'il ne cite pas reste tel quel — une réponse partielle ou mal formée n'efface rien. Un fait récrit
  sans message nouveau garde ce qui le fondait (son message, sa date, quand elle l'avait appris). Après l'appel, la
  vue se relit : ce qui a été oublié entre-temps ne revient pas. Ce qu'elle en retient : qui elle est (son rôle, ses
  sujets, avec qui elle travaille, ce qu'elle attend), comment elle est (``manner`` : son ton, sa façon d'écrire) et
  ce qu'il y a entre elle et la personne du compte (``bond``).
- **Quand** : un premier portrait après ``first_after`` messages, un nouveau après ``refresh_after`` messages de plus
  depuis le dernier (la fiche complétée **remplace** celle de la même vue) ; au plus ``per_run`` appels par passage, et
  en vingt-quatre heures au plus ``contacts_per_day`` contacts et ``calls_per_day`` appels (les passages se comptent
  dans l'annuaire, ``ContactsPort.portraits``). Chaque compte à son tour (``fair``) : un compte bavard ne prend pas toute la
  journée aux autres. Un passage toutes les heures, et peu après un message remarqué.
- **Ce qu'il voit d'elle** : son nom tel que cette vue le dit (``sheet(visible=…)`` : jamais un nom lu dans le compte
  d'une autre) ; un fait qui nomme une autre personne de l'annuaire ne se garde pas (``ContactsPort.naming``).
- **Le modèle** : le rôle ``portrait`` (voie de fond, priorité basse), sa consigne dans ``persona/voix.yaml``
  (``contacts.portrait``) ; une réponse en JSON (des faits, chacun sa sorte, sa confiance, et le message qui le fonde
  ou le fait d'avant qu'il récrit ; les faits d'avant qu'elle retire ; douze faits par vue au plus), relue strictement : une réponse illisible ne garde rien — les faits d'avant restent —, et la vue attend de
  nouveaux messages avant d'être relue (pas de rafale). Un appel qui échoue (une panne, le quota d'un abonnement
  retenu) n'est pas compté : le passage s'arrête et le suivant reprend. Un fait qu'on lui a fait oublier ne se garde
  plus, même reformulé (``ports.contacts.relearned``) ; son texte n'est jamais redonné au modèle.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from mika.contracts import email as email_c
from mika.contracts import phone as phone_c
from mika.contracts import self_ as self_c
from mika.contracts import teams as teams_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.contacts import CONTACTS, ContactsState, params, replied_key
from mika.ports.contacts import (
    EMAIL,
    MAIL,
    NOTE_KINDS,
    NOTE_MAX,
    NOTES_MAX,
    PERSON_KIND,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    Note,
    Portrait,
    generic_address,
    phone_app_value,
)
from mika.ports.llm import LLMRequest, Message, json_object
from mika.ports.preprocess import cite, inert
from mika.vocab.phrasebook import family, phrase

log = logging.getLogger("mika.contacts.portrait")

#: le rôle de ses appels
ROLE = "portrait"
#: un passage : au plus tôt tant après un message remarqué (une conversation se laisse finir), sinon toutes les heures ;
#: le premier, peu après le démarrage
WAKE_GAP = 10 * MINUTE
EVERY = HOUR
START_DELAY = 2 * MINUTE
#: les plafonds se comptent sur ce qui précède (vingt-quatre heures)
CAP_SPAN = DAY
#: au plus tant de personnes regardées par source et par passage (celles qui échangent depuis le plus récemment)
SCANNED = 2000
#: un groupe du téléphone compte s'il a au plus tant de personnes (elle comprise) : au-delà, on n'y échange pas
GROUP_MAX = 8
#: un message, au plus, dans le prompt (caractères) : un long mail n'y prend pas toute la place
MESSAGE_MAX = 1500
#: la sortie d'un portrait, au plus (jetons) : douze faits en JSON tiennent en moins de 1 000
OUTPUT_MAX = 1600
#: ce que l'annuaire retient du dernier passage (la console le dit) : combien de contacts échangent, quand
CURSOR_ELIGIBLE, CURSOR_RUN = "portrait.eligible", "portrait.run"
#: la forme de la réponse, que le fournisseur garantit quand il le sait (ADR 0267) ; ``parse`` relit toujours du texte
FACT_SCHEMA = json_object(texte={"type": "string"}, sorte={"type": "string", "enum": list(NOTE_KINDS)},
                          confiance={"type": "number"}, message={"type": "integer"}, avant={"type": "integer"})
PORTRAIT_SCHEMA = json_object(faits={"type": "array", "items": FACT_SCHEMA},
                              laisse={"type": "array", "items": {"type": "integer"}})
_JSON = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True, slots=True)
class Line:
    """Un message qu'elle relit : sa référence, sa date (µs), où il a été écrit (déjà en mots), son texte ; ``group`` :
    écrit dans un groupe (le téléphone)."""

    ref: str
    at: int
    place: str
    text: str
    group: bool = False


@dataclass(frozen=True, slots=True)
class Candidate:
    """Une personne avec qui un compte échange vraiment : son contact, la vue (source, compte), ce qui la désigne dans
    la source (son identifiant Teams, son adresse, sa clé du téléphone), combien de ses messages dans la fenêtre et le
    dernier."""

    contact: int
    source: str
    account: str
    key: str
    count: int
    last: int


@dataclass(frozen=True, slots=True)
class Fact:
    """Un fait de la réponse : ``message``, le numéro du message qui le fonde (0 : aucun nouveau) ; ``before``, celui
    du fait d'avant qu'il remplace (0 : un fait nouveau). Un fait d'avant précisé par un message nouveau a les deux :
    c'est le message qui le fonde désormais ; récrit sans message nouveau, il garde ce qui fondait l'ancien."""

    text: str
    kind: str
    confidence: float
    message: int
    before: int = 0


def _number(value: object, top: int) -> int:
    """Un numéro de 1 à ``top`` (0 : absent, ou hors de ses bornes)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= top else 0


def parse(text: str, count: int, known: int = 0) -> list[Fact] | None:
    """Les faits d'une réponse, relus strictement : un objet JSON qui a « faits », une liste ; chaque fait un texte
    d'au plus ``NOTE_MAX`` caractères, une confiance de 0 à 1, et le numéro d'un des ``count`` messages qui le fonde
    — ou, pour un fait d'avant repris sans message nouveau, le numéro d'un des ``known`` faits d'avant (« avant », ADR
    0303) ; une sorte inconnue devient « other », au plus ``NOTES_MAX`` — un fait qui ne tient pas tombe. ``None`` :
    rien de lisible (pas de JSON, pas de liste, ou une liste dont aucun fait ne tient) ; une liste vide : rien de
    sûr."""
    found = _JSON.search(text or "")
    if not found:
        return None
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return None
    raw = data.get("faits") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    out: list[Fact] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        said = " ".join(str(item.get("texte") or "").split()) if isinstance(item.get("texte"), str) else ""
        confidence = item.get("confiance")
        if not said or len(said) > NOTE_MAX or isinstance(confidence, bool):
            continue
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            continue
        message, before = _number(item.get("message"), count), _number(item.get("avant"), known)
        if not message and not before:
            continue
        kind = item.get("sorte") if item.get("sorte") in NOTE_KINDS else "other"
        if said.casefold() not in {f.text.casefold() for f in out}:
            out.append(Fact(said, str(kind), float(confidence), message, before))
    if raw and not out:
        return None
    return out[:NOTES_MAX]


def left(text: str, known: int) -> frozenset[int]:
    """Les faits d'avant que la réponse retire (« laisse » : leurs numéros, de 1 à ``known``, ADR 0303) — ce que ses
    nouveaux messages démentent, ou qu'un autre fait dit mieux. Un fait d'avant qu'elle ne cite nulle part reste tel
    quel : une réponse partielle ou mal formée n'efface rien."""
    found = _JSON.search(text or "")
    try:
        data = json.loads(found.group(0)) if found else None
    except ValueError:
        return frozenset()
    raw = data.get("laisse") if isinstance(data, dict) else None
    return frozenset(n for n in (_number(x, known) for x in raw) if n) if isinstance(raw, list) else frozenset()


def system(name: str) -> str:
    """La consigne du portrait, au nom de celle qui lit (celui de sa persona : jamais écrit ici)."""
    return phrase("contacts.portrait.system", name=name)


def when(frame: Frame, at: int) -> str:
    then = frame.local(at)
    return phrase("contacts.portrait.when", day=f"{then.day:02d}", month=f"{then.month:02d}", year=then.year,
                  hour=then.hour, minute=f"{then.minute:02d}")


def ask(frame: Frame, who: str, source: str, lines: Sequence[Line], chars: int,
        known: Sequence[Note] = ()) -> tuple[str, list[Line]]:
    """Le message du portrait : ce qu'elle en sait déjà dans cette vue (``known``, ses faits d'avant, numérotés : la
    fiche qu'elle complète, ADR 0303 — jamais un fait oublié, qui n'y est plus), puis ses messages, du plus récent au
    plus ancien, chacun numéroté avec sa date et sa conversation, son texte cité — tant que ``chars`` le permet (le
    premier toujours). Rend le message et les lignes qu'il porte, dans l'ordre de leurs numéros."""
    where = family("contacts.portrait.where")
    shown: list[Line] = []
    parts: list[str] = []
    used = 0
    for line in lines:
        body = cite(line.text, MESSAGE_MAX)
        if shown and used + len(body) > chars:
            break
        shown.append(line)
        used += len(body)
        parts.append(phrase("contacts.portrait.line", n=len(shown), when=when(frame, line.at), place=line.place)
                     + "\n" + body)
    text = phrase("contacts.portrait.ask", who=inert(who, 80), where=where.get(source, where["teams"]),
                  count=len(shown), messages="\n\n".join(parts))
    if known:
        facts = "\n".join(phrase("contacts.portrait.known_line", n=i, kind=k.kind, text=inert(k.text, NOTE_MAX))
                          for i, k in enumerate(known, 1))
        text = phrase("contacts.portrait.known", who=inert(who, 80), facts=facts) + "\n\n" + text
    return text, shown


def note_of(c: Candidate, fact: Fact, shown: Sequence[Line], known: Sequence[Note], now: int, call_id: str) -> Note:
    """Le fait à garder : fondé sur le message qu'il cite (appris maintenant), ou, récrit d'avant sans message
    nouveau, sur ce qui fondait le fait d'avant — son message, sa date, quand elle l'avait appris (ADR 0303)."""
    if fact.message:
        line = shown[fact.message - 1]
        return Note(0, c.contact, c.source, c.account, fact.text, fact.kind, fact.confidence, line.ref, line.place,
                    line.at, now, call_id)
    was = known[fact.before - 1]
    return Note(0, c.contact, c.source, c.account, fact.text, fact.kind, fact.confidence, was.ref, was.place,
                was.said_at, was.at or now, call_id)


def alive(ctx: Any, source: str, note: Note) -> bool:
    """Le message qui fonde ce fait est-il encore là (ADR 0303) ? Un message Teams effacé (son texte vidé) ou parti, un
    mail retiré du cache, un message du téléphone oublié (son texte n'est plus) : le fait qui en vient ne se redit plus
    au modèle et part au passage suivant — la fiche qui s'enrichit ne garde pas ce que l'oubli a atteint."""
    if not note.ref:
        return False
    if source == TEAMS:
        teams = ctx.ports.get("teams")
        found = teams.message(note.ref) if teams is not None else None
        return found is not None and bool((found.text or "").strip())
    if source == MAIL:
        mail = ctx.ports.get("mail")
        return mail is not None and mail.cached_one(note.ref) is not None
    if source == PHONE_SOURCE:
        journal, seq = ctx.ports.get("store"), phone_c.message_seq(note.ref)
        return journal is not None and seq is not None and bool(phone_text(journal, seq))
    return False


def phone_text(journal: Any, seq: int) -> str:
    """Le texte d'un message reçu sur le téléphone (l'événement ``seq``), tant que l'oubli ne l'a pas emporté."""
    for e in journal.get_events([seq]):
        if e.type != phone_c.RECEIVED.name:
            continue
        try:
            d = json.loads(e.data)
        except ValueError:
            return ""
        ref = (d.get("text") or {}).get("ref") if isinstance(d, dict) and isinstance(d.get("text"), dict) else None
        return str(journal.content([ref]).get(ref) or "") if ref else ""
    return ""


def teams_place(kind: str, title: str) -> str:
    """Où un message Teams a été écrit, en mots (« dans le groupe « Projet » ») ; son nom, venu d'ailleurs, inerte."""
    if kind == "dm":
        return phrase("contacts.portrait.place.dm")
    if not title:
        return phrase("contacts.portrait.place.other")
    named = inert(title, 80)
    if kind == "channel":
        return phrase("contacts.portrait.place.channel", title=named)
    if kind == "meeting":
        return phrase("contacts.portrait.place.meeting", title=named)
    return phrase("contacts.portrait.place.group", title=named)


def mail_place(subject: str) -> str:
    return phrase("contacts.portrait.place.mail", title=inert(subject, 120)) if subject.strip() \
        else phrase("contacts.portrait.place.no_subject")


def phone_place(group: bool, title: str) -> str:
    return phrase("contacts.portrait.place.phone_group", title=inert(title, 80)) if group and title \
        else phrase("contacts.portrait.place.phone_dm")


@CONTACTS.process("contacts.portrait", wake_on=[teams_c.NOTICED, email_c.NOTICED, phone_c.RECEIVED],
                  reads=[self_c.PERSONA], catch_up=CatchUp.ONCE, max_quantum_s=3600,
                  priority=95, deadline_s=1800)
class Portraits:
    def __init__(self) -> None:
        #: les messages remarqués au début du dernier passage (``None`` : pas encore passé)
        self.handled: int | None = None
        #: la fin du dernier passage : la cadence se compte d'elle
        self.done_at: int | None = None
        #: le démarrage (le premier passage attend un peu)
        self.born: int | None = None
        #: les messages du téléphone lus pendant ce passage, par (personne, expéditeur)
        self._phone: dict[tuple[str, str], list[Line]] = {}

    def next_due(self, s: ContactsState | None, frame: Frame, last_run: int | None) -> int | None:
        if not params(frame.env.params_of(CONTACTS.name, frame.root)).portraits:
            return None
        if self.handled is None:
            self.born = self.born if self.born is not None else frame.now
            return max(frame.now, self.born + START_DELAY)
        since = max(self.done_at or 0, last_run or 0)
        if (s.heard if s is not None else 0) != self.handled:
            return max(frame.now, since + WAKE_GAP)
        return max(frame.now, since + EVERY)

    async def run(self, ctx: Any) -> None:
        heard = ctx.state.heard if ctx.state is not None else 0
        try:
            await self._run(ctx)
        finally:
            self.handled, self.done_at = heard, ctx.now

    async def _run(self, ctx: Any) -> None:
        store = ctx.ports.get("contacts")
        p = params(ctx.frame.env.params_of(CONTACTS.name, ctx.frame.root))
        serving = getattr(ctx.llm, "serving", None)
        if store is None or ctx.llm is None or not p.portraits or (callable(serving) and not serving(ROLE)):
            return
        now = ctx.now
        since = 0 if p.history else now - p.window_us
        limit, chars = (p.history_messages, p.history_chars) if p.history else (p.messages, p.chars)
        candidates = self.candidates(ctx, store, since)
        store.set_cursor(CURSOR_ELIGIBLE, len({c.contact for c in candidates}))
        store.set_cursor(CURSOR_RUN, now)
        today = store.portraits(since=now - CAP_SPAN)
        calls, contacts = len(today), {x.contact for x in today}
        if calls >= p.calls_per_day or not candidates:
            return
        held = getattr(ctx.llm, "held", None)
        if callable(held) and held(ROLE, 3):
            return  # le quota est réservé à la conversation : le passage suivant reprendra
        last: dict[tuple[int, str, str], Portrait] = {}
        for x in store.portraits(contacts={c.contact for c in candidates}):
            last.setdefault((x.contact, x.source, x.account), x)
        due = fair([c for c in candidates if (c.contact, c.source, c.account) not in last
                    or c.last > last[(c.contact, c.source, c.account)].upto])
        her = self_c.name_of(ctx.frame.get(self_c.PERSONA))
        made = 0
        for c in due:
            if made >= p.per_run or calls >= p.calls_per_day:
                break
            if c.contact not in contacts and len(contacts) >= p.contacts_per_day:
                continue
            previous = last.get((c.contact, c.source, c.account))
            sheet = store.sheet(c.contact, visible={(c.source, c.account)})  # son nom tel que cette vue le dit
            if sheet is None or sheet.kind != PERSON_KIND:
                continue
            lines = self.lines(ctx, c, since, limit)
            fresh = [x for x in lines if previous is None or x.at > previous.upto]
            if not lines or len(fresh) < (p.refresh_after if previous is not None else p.first_after):
                continue
            # ce qu'elle en sait déjà dans cette vue : la fiche qu'elle complète (ADR 0303) ; un fait dont le message
            # n'est plus (effacé, oublié, retiré) ne se montre plus et part avec ce passage
            view = {(c.source, c.account)}
            had = store.notes(c.contact, visible=view)
            known = [n for n in had if alive(ctx, c.source, n)][:NOTES_MAX]
            text, shown = ask(ctx.frame, sheet.name, c.source, lines, chars, known)
            request = LLMRequest(role=ROLE, call_id=f"{ctx.run_id}#{c.contact}:{c.source}:{c.account}",
                                 system_stable=system(her), messages=(Message("user", text),), max_tokens=OUTPUT_MAX,
                                 lane="background", priority=3, output_schema=PORTRAIT_SCHEMA)
            response = await ctx.ask(request)
            if response is None:
                return  # une panne, un quota : pas compté, le passage suivant reprend
            made, calls = made + 1, calls + 1
            contacts.add(c.contact)
            facts = parse(response.text, len(shown), len(known))
            mark = Portrait(c.contact, c.source, c.account, now, max(x.at for x in shown), len(shown),
                            ok=facts is not None, call_id=request.call_id)
            if facts is None:
                log.warning("portrait illisible pour le contact %s (%s, %s) : rien n'est gardé (%s)", c.contact,
                            c.source, c.account, request.call_id)
                store.portrayed(mark, None)
                continue
            if facts:  # un fait sur lui ne nomme pas un tiers (l'oublier ne l'atteindrait pas)
                named = store.naming([f.text for f in facts], but=c.contact)
                facts = [f for f, says in zip(facts, named, strict=True) if not says]
            gone = left(response.text, len(known))
            if store.sheet(c.contact, visible=view) is None:  # la vue est partie pendant l'appel : rien n'y revient
                store.portrayed(mark, None)
                continue
            # ce qui a été oublié pendant l'appel ne revient pas, ni repris, ni tel quel
            still = {n.id for n in store.notes(c.contact, visible=view)}
            kept = [f for f in facts if not f.before or known[f.before - 1].id in still]
            replaced = {f.before for f in kept} | gone
            untouched = [replace(n, id=0) for i, n in enumerate(known, 1) if i not in replaced and n.id in still]
            sheet_now = [note_of(c, f, shown, known, now, request.call_id) for f in kept] + untouched
            changed = bool(kept or gone or len(known) < len(had))
            store.portrayed(mark, sheet_now[:NOTES_MAX] if changed else None)

    # ── qui échange vraiment ──
    def candidates(self, ctx: Any, store: Any, since: int) -> list[Candidate]:
        """Les personnes avec qui un compte échange vraiment, par vue : Teams, le courrier, le téléphone."""
        out: list[Candidate] = []
        teams = ctx.ports.get("teams")
        if teams is not None:
            keys = [a.key for a in teams.accounts()]
            for account, author, n, at in teams.exchanged(since, limit=SCANNED, accounts=keys):
                cid = store.contact_of(TEAMS_ID, author)
                if cid is not None:
                    out.append(Candidate(cid, TEAMS, account, author, n, at))
        mail = ctx.ports.get("mail")
        if mail is not None:
            boxes = [a.key for a in mail.accounts()]
            for x in mail.exchanged(since, limit=SCANNED, accounts=boxes):
                cid = store.contact_of(EMAIL, x.address) if not generic_address(x.address) else None
                if cid is not None:
                    out.append(Candidate(cid, MAIL, x.account, x.address, x.received, x.last))
        journal = ctx.ports.get("store")
        if journal is not None and ctx.state is not None:
            self._phone = phone_lines(journal, ctx.state.phone, since)
            people = thread_people(self._phone)
            for (recipient, value), lines in self._phone.items():
                if not any(phone_exchange(ctx.state.replied.get(replied_key(recipient, value.split(":", 1)[0], t), 0),
                                          since, [x for x in lines if x.ref.split("#", 1)[1] == t],
                                          people.get((recipient, value.split(":", 1)[0], t), 0))
                           for t in {x.ref.split("#", 1)[1] for x in lines}):
                    continue
                cid = store.contact_of(PHONE_APP, value)
                if cid is not None:
                    out.append(Candidate(cid, PHONE_SOURCE, recipient, value, len(lines),
                                         max(x.at for x in lines)))
        return out

    # ── ce qu'elle relit ──
    def lines(self, ctx: Any, c: Candidate, since: int, limit: int) -> list[Line]:
        """Ses derniers messages dans cette vue, du plus récent au plus ancien."""
        if c.source == TEAMS:
            teams = ctx.ports.get("teams")
            got = teams.authored([c.key], since=since, limit=limit, accounts=[c.account]) if teams else []
            places: dict[str, str] = {}
            out = []
            for m in got:
                if m.conversation not in places:
                    found = teams.conversation(m.account, m.conversation)
                    places[m.conversation] = teams_place(found.kind if found is not None else "other",
                                                         found.title if found is not None else "")
                if m.text.strip():
                    out.append(Line(m.ref, m.at, places[m.conversation], m.text))
            return out
        if c.source == MAIL:
            mail = ctx.ports.get("mail")
            got = mail.letters_from(c.key, since=since, limit=limit, accounts=[c.account]) if mail else []
            return [Line(m.ref, m.date, mail_place(m.subject or ""), m.body) for m in got if (m.body or "").strip()]
        if c.source == PHONE_SOURCE:
            found = self._phone.get((c.account, c.key), [])
            return [Line(x.ref.split("#", 1)[0], x.at, x.place, x.text) for x in found][:limit]
        return []


def fair(due: Sequence[Candidate]) -> list[Candidate]:
    """Chaque vue (source, compte) à son tour : la plus riche de chacune (le plus de messages, puis la plus récente),
    puis la suivante de chacune… — un compte bavard ne prend pas toute la journée aux autres."""
    by_place: dict[tuple[str, str], list[Candidate]] = {}
    for c in sorted(due, key=lambda c: (-c.count, -c.last, c.contact, c.source, c.account)):
        by_place.setdefault((c.source, c.account), []).append(c)
    out: list[Candidate] = []
    rank = 0
    while len(out) < len(due):
        for place in sorted(by_place):
            if rank < len(by_place[place]):
                out.append(by_place[place][rank])
        rank += 1
    return out


def thread_people(lines: Mapping[tuple[str, str], Sequence[Line]]) -> dict[tuple[str, str, str], int]:
    """Combien de personnes écrivent dans chaque conversation du téléphone (personne, appli, conversation) — elle
    comprise : ses expéditeurs dans ce qu'elle garde, plus un."""
    senders: dict[tuple[str, str, str], set[str]] = {}
    for (recipient, value), found in lines.items():
        for x in found:
            senders.setdefault((recipient, value.split(":", 1)[0], x.ref.split("#", 1)[1]), set()).add(value)
    return {k: len(v) + 1 for k, v in senders.items()}


def phone_exchange(replied_at: int, since: int, lines: Sequence[Line], people: int) -> bool:
    """Une conversation du téléphone où l'on échange avec cet expéditeur : la personne y a écrit dans la fenêtre — en
    tête-à-tête, cela suffit ; dans un groupe, il faut qu'il soit petit (``GROUP_MAX``) et qu'elle y ait écrit après
    lui (elle lui répond, pas seulement aux autres)."""
    if not lines or replied_at < since or not replied_at:
        return False
    if not any(x.group for x in lines):
        return True
    return people <= GROUP_MAX and replied_at > min(x.at for x in lines)


def phone_lines(journal: Any, kept: Sequence[int], since: int) -> dict[tuple[str, str], list[Line]]:
    """Les messages du téléphone que la tranche garde (``ContactsState.phone``), depuis ``since`` : par personne qui
    les a reçus et par expéditeur (``<appli>:<empreinte>``), du plus récent au plus ancien. La référence d'une ligne
    porte sa conversation après « # » (``p<seq>#<conversation>``), le temps de juger qu'on y échange."""
    events = [e for e in journal.get_events(list(kept)) if e.type == phone_c.RECEIVED.name] if kept else []
    payloads = []
    for e in events:
        try:
            d = json.loads(e.data)
        except ValueError:
            continue
        if isinstance(d, dict) and not d.get("own") and (int(d.get("sent_at") or 0) or int(e.at)) >= since:
            payloads.append((e, d))
    refs = [str(d[k].get("ref") or "") for _e, d in payloads for k in ("text", "title")
            if isinstance(d.get(k), dict)]
    texts: Mapping[str, str] = journal.content([r for r in refs if r]) if refs else {}
    out: dict[tuple[str, str], list[Line]] = {}
    for e, d in payloads:
        value = phone_app_value(str(d.get("source") or ""), str(d.get("sender") or ""))
        recipient = str(d.get("recipient") or "")
        said = texts.get(str((d.get("text") or {}).get("ref") or "")) if isinstance(d.get("text"), dict) else None
        if not value or not recipient or not said:
            continue  # un message oublié depuis (son texte n'est plus) ne se relit pas
        title = texts.get(str((d.get("title") or {}).get("ref") or ""), "") if isinstance(d.get("title"), dict) \
            else ""
        at = int(d.get("sent_at") or 0) or int(e.at)
        out.setdefault((recipient, value), []).append(
            Line(f"{phone_c.message_ref(e.seq)}#{d.get('thread') or ''}", at, phone_place(bool(d.get("group")), title),
                 said, bool(d.get("group"))))
    for lines in out.values():
        lines.sort(key=lambda x: -x.at)
    return out


__all__ = ["CURSOR_ELIGIBLE", "CURSOR_RUN", "GROUP_MAX", "PORTRAIT_SCHEMA", "ROLE", "Candidate", "Fact", "Line",
           "Portraits", "ask", "fair", "note_of", "parse", "phone_exchange", "phone_lines", "system", "thread_people"]
