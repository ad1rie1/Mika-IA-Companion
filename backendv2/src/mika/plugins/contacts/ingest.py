"""La collecte de l'annuaire (ADR 0298) : qui écrit dans les comptes Teams, qui correspond avec les boîtes, rangé dans
l'annuaire (le port ``contacts``) depuis l'endroit où la lecture d'avant s'est arrêtée — chaque lot rangé avec son
curseur, dans la même écriture : un passage coupé reprend où il en était, sans rien compter deux fois.

- **Les comptes eux-mêmes** : l'identifiant Teams d'un compte et l'adresse d'une boîte sont la personne du compte
  (``own``) — jamais pour un compte à elle (``elle`` : ce serait elle) ; leur contact est relié à la personne à qui est
  le compte quand elle est une seule, sans défaire un lien posé avant.
- **Jamais elle-même** : l'identifiant Teams et l'adresse de ses comptes à elle ne sont rangés d'aucun compte (elle
  écrit à la boîte d'Adrien : elle n'est pas un contact d'Adrien) ; ce qui en avait été rangé part (``discard``).
- **Un compte supprimé des réglages** : ce que l'annuaire en tenait s'efface (``drop_source``).
- **Les profils Teams** (lot 2) : chaque profil changé (``teams.profiles_since``) dit de sa personne son nom, son poste
  et son service (sur son identifiant Teams), son e-mail (une preuve : le contact du courrier qui la porte est le
  même), ses numéros, son entreprise (son organisation) — et l'organisation Teams du compte, gardée seulement quand
  elle porte le nom de l'entreprise : un compte peut être celui d'un prestataire hébergé chez une autre. Le profil de
  la personne d'un compte à elle n'est pas rangé (ce serait elle). Un profil est daté par le dernier message de sa
  personne dans ce compte (``said_at``), jamais par sa réception : reçu après un oubli sans message neuf d'elle (un
  historique rechargé, un profil qui change), il ne la ramène pas.
- **Le téléphone** (lot 5) : les ``phone.received`` que la tranche garde (``ContactsState.phone``), d'après le
  dernier lu, relus dans le journal (le port ``store``, ``get_events``) : chaque expéditeur (``PHONE_APP``, sa clé sans son nom) vu sur le téléphone de la personne qui l'a reçu (le
  compte : sa clé — son contact à elle seule), sous le nom que le téléphone lui donne, dans chacune de ses
  conversations (le nom d'un groupe compris). Un expéditeur que le téléphone ne nomme que par son numéro est ce
  numéro (``PHONE``, une preuve) : la fiche qui l'a déjà le reçoit.
- **Ce qu'on lui raconte** (lot 5) : les éléments de sa mémoire (souvenirs, croyances, moments de vie : la porte,
  ``contracts.memory.KNOWLEDGE``) qui concernent une personne connue seulement de nom (``name:…``), depuis le dernier
  lu ; chacun compte une fois pour chaque personne qui le lui a confié (``told_by``, résolu par ``identity.PERSON`` —
  le compte de la source : son contact). Seulement ce qu'on lui a vraiment confié : un élément sans ``told_by`` (une
  réflexion de la nuit, une pensée, qui ne vient de personne), secret, gardé pour elle (``internal_only``) ou dont les
  sources posent leurs restrictions (``constraints``) ne fait connaître personne — sa fiche se dirait à qui ne doit pas
  l'apprendre. Ce qu'un expéditeur du téléphone a dit compte pour la personne qui le lui a montré (elle est parmi ceux
  qui l'ont confié), jamais pour lui. Son nom est la clé repliée, écrit comme le texte de l'élément l'écrit quand il l'y
  trouve. Une règle nouvelle (``TOLD_RULE``) fait relire toute sa mémoire : ce qui ne la suit plus part.
- **Les noms reliés** : quand l'identité relie un nom raconté à une personne (``identity.name_bound``, lu par
  ``identity.PERSON`` du nom), son contact lui est relié, sans défaire un lien posé avant ; le lien défait, un contact
  qui n'est qu'un nom raconté se délie.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import select

from mika.contracts import email as email_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import phone as phone_c
from mika.contracts import teams as teams_c
from mika.kernel.clock import MINUTE, US
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.contacts import CONTACTS, ContactsState
from mika.ports.contacts import (
    COMPANY,
    EMAIL,
    MAIL,
    NAME_PREFIX,
    PHONE,
    PHONE_APP,
    PHONE_PREFIX,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    TENANT,
    TOLD,
    TOLD_NAME,
    Observation,
    account_person,
    normalized,
    number_in_name,
    phone_app_value,
)
from mika.vocab.access import SELF
from mika.vocab.people import fold, is_identifiable, named_label

#: au plus, ce qu'une lecture d'une source parcourt d'un coup (des messages, des mails) ; au plus tant de lectures par
#: source et par passage — le reste au passage suivant
BATCH = 500
READS_PER_RUN = 8
#: un message remarqué : un passage, au plus tôt tant après le précédent (une rafale n'en fait qu'un) ; tant qu'il en
#: reste : un passage à ce rythme ; sinon, un rattrapage à ce rythme (l'historique, ses propres messages)
WAKE_GAP = 5 * US
BUSY_EVERY = 10 * US
IDLE_EVERY = 2 * MINUTE
#: les curseurs de l'annuaire : les messages Teams (le dernier lu, son arrivée), les mails gardés, les envois
CURSOR_TEAMS, CURSOR_TEAMS_AT = "teams.messages", "teams.received"
#: les profils Teams (leur rang de changement)
CURSOR_PROFILES = "teams.profiles"
CURSOR_MAIL, CURSOR_SENT = "mail.messages", "mail.sent"
#: les messages du téléphone (le numéro du dernier ``phone.received`` lu du journal) ; les éléments de sa mémoire sur
#: une personne connue de nom (le dernier lu)
CURSOR_PHONE, CURSOR_TOLD = "phone.received", "memory.told"
#: la règle sous laquelle ce qu'on lui raconte a été rangé (``TOLD_RULE``), et une relecture entière en cours (1) : une
#: règle nouvelle efface ces vues et relit sa mémoire depuis le début ; la relecture finie, ce qu'elle n'a pas revu part
CURSOR_TOLD_RULE, CURSOR_TOLD_REBUILD = "memory.told.rule", "memory.told.rebuild"
#: 2 : seulement ce qu'on lui a vraiment confié (ni réflexion, ni secret, ni gardé pour elle, ni restreint)
TOLD_RULE = 2
#: ce qui rattache un nom à sa mémoire : souvenirs, croyances, moments de sa vie (ce que la file des noms lit aussi)
TOLD_KINDS = (memory_c.EPISODE_MEMORY, memory_c.BELIEF, memory_c.EVENT)
#: les clés « connue seulement de nom » : ``name:`` ≤ clé < ``name;`` (l'index par personne se lit par plage)
_NAMED_END = "name;"
#: les mots d'un texte, pour y retrouver un nom tel qu'il est écrit
_WORDS = re.compile(r"[^\W\d_][\w'’-]*")


@CONTACTS.process("contacts.ingest", wake_on=[teams_c.NOTICED, email_c.NOTICED, phone_c.RECEIVED,
                                                identity_c.NAME_BOUND],
                  reads=[identity_c.OWNERS, identity_c.PERSON], catch_up=CatchUp.ONCE, max_quantum_s=900, priority=90,
                  deadline_s=600)
class Ingest:
    def __init__(self) -> None:
        #: les messages remarqués au début du dernier passage (``None`` : pas encore passé)
        self.handled: int | None = None
        #: le dernier passage s'est arrêté avant la fin d'une source
        self.busy = False
        #: la fin du dernier passage : la cadence se compte d'elle
        self.done_at: int | None = None
        #: les comptes déjà rangés comme leur personne (source, compte, identifiant, propriétaire, propriétaires)
        self.selves: set[tuple[Any, ...]] = set()
        #: les décisions sur un nom raconté déjà appliquées à son contact (nom → numéro de la décision)
        self.applied: dict[str, int] = {}

    def next_due(self, s: ContactsState | None, frame: Frame, last_run: int | None) -> int | None:
        if self.handled is None:
            return frame.now
        since = max(self.done_at or 0, last_run or 0)
        if self.busy:
            return max(frame.now, since + BUSY_EVERY)
        if (s.heard if s is not None else 0) != self.handled:
            return max(frame.now, since + WAKE_GAP)
        return max(frame.now, since + IDLE_EVERY)

    async def run(self, ctx: Any) -> None:
        heard = ctx.state.heard if ctx.state is not None else 0
        store = ctx.ports.get("contacts")
        more = False
        if store is not None:
            owners = tuple(ctx.frame.get(identity_c.OWNERS) or ())
            teams = ctx.ports.get("teams")
            if teams is not None:
                more = await self._teams(store, teams, owners) or more
            mail = ctx.ports.get("mail")
            if mail is not None:
                more = await self._mail(store, mail, owners) or more
            journal = ctx.ports.get("store")
            if journal is not None:
                more = await self._phone(store, journal, ctx.state.phone if ctx.state is not None else ()) or more
                more = await self._told(store, journal, ctx.frame) or more
            self._bound(store, ctx.frame, ctx.state.named if ctx.state is not None else {})
        self.busy, self.done_at, self.handled = more, ctx.now, heard

    async def _teams(self, store: Any, teams: Any, owners: tuple[str, ...]) -> bool:
        accounts = teams.accounts()
        keys = {a.key for a in accounts}
        self._drop_gone(store, TEAMS, keys)
        hers = {normalized(TEAMS_ID, a.self_id) for a in accounts if a.owner == SELF and a.self_id}
        self._not_her(store, TEAMS_ID, hers)
        await self._selves(store, owners, [(TEAMS, a.key, TEAMS_ID, a.self_id, a.self_name, a.last_batch, a.owner)
                                           for a in accounts if a.self_id])
        more = False
        for _ in range(READS_PER_RUN):
            cursor = (store.cursor(CURSOR_TEAMS), store.cursor(CURSOR_TEAMS_AT))
            got = teams.people_since(cursor, BATCH)
            seen = [Observation(TEAMS_ID, p.author_id, TEAMS, p.account, p.name, p.count, p.first, p.last)
                    for p in got.people if p.account in keys and normalized(TEAMS_ID, p.author_id) not in hers]
            if seen or got.cursor != cursor:
                await store.observe(seen, cursors={CURSOR_TEAMS: got.cursor[0], CURSOR_TEAMS_AT: got.cursor[1]})
            more = got.more
            if not more:
                break
        return await self._profiles(store, teams, keys, hers) or more

    @staticmethod
    async def _profiles(store: Any, teams: Any, keys: set[str], hers: set[str]) -> bool:
        more = False
        for _ in range(READS_PER_RUN):
            cursor = store.cursor(CURSOR_PROFILES)
            got = teams.profiles_since(cursor, BATCH)
            seen = [o for p in got.profiles if p.account in keys and p.id not in hers for o in from_profile(p)]
            if seen or got.cursor != cursor:
                await store.observe(seen, cursors={CURSOR_PROFILES: got.cursor})
            more = got.more
            if not more:
                break
        return more

    async def _mail(self, store: Any, mail: Any, owners: tuple[str, ...]) -> bool:
        accounts = mail.accounts()
        keys = {a.key for a in accounts}
        self._drop_gone(store, MAIL, keys)
        hers = {normalized(EMAIL, a.address) for a in accounts if a.owner == SELF and a.address}
        self._not_her(store, EMAIL, hers)
        await self._selves(store, owners, [(MAIL, a.key, EMAIL, a.address, a.display_name, 0, a.owner)
                                           for a in accounts if a.address])
        more = False
        for _ in range(READS_PER_RUN):
            cursor = (store.cursor(CURSOR_MAIL), store.cursor(CURSOR_SENT))
            got = mail.correspondents_since(cursor, BATCH)
            seen = [Observation(EMAIL, p.address, MAIL, p.account, p.name, p.received + p.sent, p.first, p.last)
                    for p in got.people if p.account in keys and normalized(EMAIL, p.address) not in hers]
            if seen or tuple(got.cursor) != cursor:
                await store.observe(seen, cursors={CURSOR_MAIL: got.cursor[0], CURSOR_SENT: got.cursor[1]})
            more = got.more
            if not more:
                break
        return more

    @staticmethod
    async def _phone(store: Any, journal: Any, kept: Sequence[int]) -> bool:
        """Les expéditeurs des messages du téléphone que la tranche garde, d'après le dernier lu : un lot borné par
        lecture, rangé avec son curseur."""
        more = False
        for _ in range(READS_PER_RUN):
            cursor = store.cursor(CURSOR_PHONE)
            pending = [q for q in kept if q > cursor]
            if not pending:
                break
            batch, more = pending[:BATCH], len(pending) > BATCH
            got = [e for e in journal.get_events(batch) if e.type == phone_c.RECEIVED.name]
            payloads = [(e, d) for e in got if isinstance(d := _payload(e.data), dict)]
            refs = [r for _e, d in payloads for r in (_ref(d, "sender_name"), _ref(d, "title")) if r]
            texts = journal.content(refs) if refs else {}
            await store.observe(phone_observations(payloads, texts), cursors={CURSOR_PHONE: batch[-1]})
            if not more:
                break
        return more

    async def _told(self, store: Any, journal: Any, frame: Frame) -> bool:
        """Les personnes dont on lui a parlé : les éléments de sa mémoire sur un nom, depuis le dernier lu. Sous une
        règle nouvelle (``TOLD_RULE``), tout se relit depuis le début ; la relecture finie, ce qu'elle n'a pas revu
        part (``prune_unseen``)."""
        if store.cursor(CURSOR_TOLD_RULE) != TOLD_RULE:
            store.reset_source(TOLD)
            store.set_cursor(CURSOR_TOLD, 0)
            store.set_cursor(CURSOR_TOLD_REBUILD, 1)
            store.set_cursor(CURSOR_TOLD_RULE, TOLD_RULE)
        a, i = memory_c.KNOWLEDGE_ABOUT, memory_c.KNOWLEDGE
        more = False
        for _ in range(READS_PER_RUN):
            cursor = store.cursor(CURSOR_TOLD)
            rows = journal.query_mind(
                select(a.c.person, i.c.id, i.c.told_by, i.c.born_at, i.c.text, i.c.secret, i.c.internal_only,
                       i.c.constraints)
                .select_from(a.join(i, i.c.id == a.c.item))
                .where(a.c.person >= NAME_PREFIX, a.c.person < _NAMED_END, i.c.status == "active",
                       i.c.kind.in_(list(TOLD_KINDS)), i.c.id > cursor)
                .order_by(i.c.id, a.c.person).limit(BATCH))
            if not rows:
                more = False
                break
            more = len(rows) >= BATCH
            last = int(rows[-1][1])
            if more and any(int(r[1]) != last for r in rows):  # l'élément coupé se relit en entier au lot suivant
                rows = [r for r in rows if int(r[1]) != last]
                last = int(rows[-1][1])
            seen = told_observations(rows, lambda h: frame.get(identity_c.PERSON(h)) or h)
            await store.observe(seen, cursors={CURSOR_TOLD: last})
            self._bound(store, frame, {o.value: -1 for o in seen})
            if not more:
                break
        if not more and store.cursor(CURSOR_TOLD_REBUILD):
            store.prune_unseen(TOLD_NAME)  # relue entière : ce qu'elle n'a pas revu sous la règle ne compte plus
            store.set_cursor(CURSOR_TOLD_REBUILD, 0)
        return more

    def _bound(self, store: Any, frame: Frame, names: Mapping[str, int]) -> None:
        """Chaque nom raconté que l'identité relie à une personne : son contact lui est relié (sans défaire un lien
        posé avant) ; le lien défait, un contact qui n'est qu'un nom raconté se délie. ``names`` : nom → numéro de la
        décision (-1 : un nom qu'on vient de ranger, à relire à chaque fois)."""
        for key, seq in names.items():
            if seq >= 0 and self.applied.get(key) == seq:
                continue
            found = store.contact_of(TOLD_NAME, key)
            if found is not None:
                person = bound_person(key, frame.get(identity_c.PERSON(key)) or key)
                if person:
                    store.link(found, person, replace=False)
                else:
                    sheet = store.sheet(found)
                    told = [i.value for i in sheet.identifiers] if sheet is not None else []
                    if sheet is not None and sheet.person and all(i.kind == TOLD_NAME for i in sheet.identifiers) \
                            and not any(bound_person(k, frame.get(identity_c.PERSON(k)) or k) == sheet.person
                                        for k in told):
                        store.link(found, None)
            if seq >= 0:
                self.applied[key] = seq

    @staticmethod
    def _not_her(store: Any, kind: str, values: set[str]) -> None:
        """Ses identifiants à elle (ses comptes à elle) ne sont le contact de personne : ce qui en avait été rangé
        part."""
        for value in sorted(v for v in values if v):
            if store.contact_of(kind, value) is not None:
                store.discard(kind, value)

    @staticmethod
    def _drop_gone(store: Any, source: str, keys: set[str]) -> None:
        """Ce que l'annuaire tenait d'un compte qui n'est plus dans les réglages s'efface."""
        for src, account in store.sources():
            if src == source and account not in keys:
                store.drop_source(src, account)

    async def _selves(self, store: Any, owners: tuple[str, ...],
                      accounts: list[tuple[str, str, str, str, str, int, str]]) -> None:
        """Chaque compte désigne sa personne (``own``) ; son contact lui est relié quand elle est une seule. Un compte à
        elle n'est pas rangé (ce serait elle). Une fois par compte, son identifiant et son propriétaire."""
        for source, key, kind, value, name, at, owner in accounts:
            memo = (source, key, value, owner, owners)
            if owner == SELF or memo in self.selves:
                continue
            await store.observe([Observation(kind, value, source, key, name, 0, at, at, own=True)])
            person = account_person(owner, owners)
            found = store.contact_of(kind, value) if person else None
            if found is not None:
                store.link(found, person, replace=False)
            self.selves.add(memo)


def _payload(data: str) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        return None


def _ref(data: Mapping[str, Any], name: str) -> str:
    found = data.get(name)
    return str(found.get("ref") or "") if isinstance(found, dict) else ""


def phone_observations(events: Sequence[tuple[Any, Mapping[str, Any]]], texts: Mapping[str, str]) -> list[Observation]:
    """Ce que des ``phone.received`` (événement, charge utile) disent de leurs expéditeurs : par personne qui les a
    reçus, expéditeur et conversation, combien de messages, la première et la dernière fois, le nom et le titre de
    groupe les plus récents (``texts`` : leurs contenus, absents une fois oubliés). Ses propres messages ne comptent
    pas. Un expéditeur nommé par son seul numéro est ce numéro : ``PHONE`` d'abord (le numéro va à la fiche qui l'a),
    puis sa clé, qui le rejoint (une preuve)."""
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for e, d in events:
        recipient, sender = str(d.get("recipient") or ""), str(d.get("sender") or "")
        value = phone_app_value(str(d.get("source") or ""), sender)
        if d.get("own") or not recipient or not value:
            continue
        at = int(d.get("sent_at") or 0) or int(e.at)
        got = found.setdefault((recipient, value, str(d.get("thread") or "")),
                               {"n": 0, "first": at, "last": at, "at": -1, "name": "", "title": "", "group": False})
        got["n"] += 1
        got["first"], got["last"] = min(got["first"], at), max(got["last"], at)
        got["group"] = got["group"] or bool(d.get("group"))
        if at >= got["at"]:
            got["at"] = at
            got["name"] = texts.get(_ref(d, "sender_name")) or got["name"]
            got["title"] = texts.get(_ref(d, "title")) or got["title"]
    out: list[Observation] = []
    for (recipient, value, thread), got in found.items():
        number = number_in_name(got["name"])
        where = {"thread": thread, "thread_title": got["title"] if got["group"] else "", "group": got["group"]}
        if number:
            out.append(Observation(PHONE, number, PHONE_SOURCE, recipient, "", 0, got["first"], got["last"],
                                   same=((PHONE_APP, value),)))
            out.append(Observation(PHONE_APP, value, PHONE_SOURCE, recipient, "", got["n"], got["first"],
                                   got["last"], joins=(PHONE, number), proof=True, **where))
        else:
            out.append(Observation(PHONE_APP, value, PHONE_SOURCE, recipient, got["name"], got["n"], got["first"],
                                   got["last"], **where))
    return out


def tellers(told_by: Iterable[str], person: Any) -> tuple[str, ...]:
    """Les personnes qui ont confié un élément (``told_by`` ; ``person`` : la clé de personne d'une adresse), celles
    dont il est le contact : jamais un expéditeur du téléphone (le compte est la personne qui le lui a montré), une
    personne connue de nom, une adresse interne ou de passage."""
    out = []
    for h in told_by:
        if not h or h.startswith((PHONE_PREFIX, NAME_PREFIX)) or not is_identifiable(h):
            continue
        who = str(person(h) or h)
        if who and not who.startswith((PHONE_PREFIX, NAME_PREFIX)):
            out.append(who)
    return tuple(dict.fromkeys(out))


def spelled(key: str, text: str) -> str:
    """Le nom d'une clé ``name:…`` tel que ce texte l'écrit (« Léa Martin » pour ``lea martin``), vide s'il n'y est
    pas : la clé est repliée, sans accents ni majuscules."""
    want = named_label(key).split()
    words = _WORDS.findall(text or "")
    for at in range(len(words) - len(want) + 1) if want else ():
        found = words[at:at + len(want)]
        if [fold(w) for w in found] == want:
            return " ".join(found)
    return ""


def confided(secret: Any = 0, internal_only: Any = 0, constraints: Any = None) -> bool:
    """Un élément qu'on peut faire connaître à qui le lui a confié : ni secret, ni gardé pour elle, sans restrictions
    venues de ses sources (``constraints``, illisibles comprises)."""
    if secret or internal_only:
        return False
    try:
        found = json.loads(constraints) if isinstance(constraints, str) else constraints
    except ValueError:
        return False
    return not found


def told_observations(rows: Sequence[Sequence[Any]], person: Any) -> list[Observation]:
    """Ce que des éléments de sa mémoire (clé du nom, élément, ``told_by`` en JSON, né à, texte, puis — s'ils y sont —
    ``secret``, ``internal_only``, ``constraints``) disent des personnes dont on lui a parlé : par nom et par personne
    qui le lui a confié, combien d'éléments, le premier et le dernier, le nom tel qu'un texte l'écrit (sinon la clé, en
    capitales). Un élément que personne ne lui a confié (une réflexion, une pensée), secret, gardé pour elle ou
    restreint ne compte pour personne (``confided``) ; un élément confié seulement par des expéditeurs du téléphone ou
    des inconnus de passage non plus."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key, _item, told_by, born, text = row[:5]
        if not confided(*row[5:8]):
            continue
        try:
            raw = json.loads(told_by or "[]")
        except (TypeError, ValueError):
            raw = []
        told = [str(h) for h in raw if h] if isinstance(raw, list) else []
        accounts = tellers(told, person)
        at = int(born or 0)
        for account in accounts:
            got = found.setdefault((str(key), account), {"n": 0, "first": at, "last": at, "name": ""})
            got["n"] += 1
            got["first"], got["last"] = min(got["first"], at), max(got["last"], at)
            got["name"] = got["name"] or spelled(str(key), str(text or ""))
    return [Observation(TOLD_NAME, key, TOLD, account, got["name"] or named_label(key).title(), got["n"],
                        got["first"], got["last"]) for (key, account), got in found.items()]


def bound_person(key: str, person: str) -> str:
    """La personne qu'un nom raconté désigne pour l'identité (``identity.PERSON`` du nom) ; vide s'il n'est relié à
    personne."""
    return person if person and person != key and not person.startswith((NAME_PREFIX, PHONE_PREFIX)) else ""


def from_profile(p: Any) -> list[Observation]:
    """Ce qu'un profil Teams (``ports.teams.TeamsProfile``) dit de sa personne, à ranger dans cet ordre : son
    identifiant Teams (son nom, son poste, son service, son entreprise), son e-mail (une preuve), ses numéros, son
    entreprise, et l'organisation Teams du compte quand elle porte le nom de l'entreprise. Chacun vu au dernier message
    de sa personne dans ce compte (``said_at`` ; 0 sans message : face à un oubli, il ne ramène rien), sans compter
    comme un message — jamais à l'heure où le serveur l'a reçu."""
    at, me = int(getattr(p, "said_at", 0) or 0), (TEAMS_ID, p.id)
    email = ((EMAIL, p.email),) if p.email else ()
    out = [Observation(TEAMS_ID, p.id, TEAMS, p.account, p.name, 0, at, at, title=p.title, department=p.department,
                       same=email, company=p.company)]
    if p.email:
        out.append(Observation(EMAIL, p.email, TEAMS, p.account, p.name, 0, at, at, joins=me, proof=True))
    out += [Observation(PHONE, n, TEAMS, p.account, p.name, 0, at, at, joins=me) for n in p.phones]
    if normalized(COMPANY, p.company):
        out.append(Observation(COMPANY, p.company, TEAMS, p.account, p.company, 0, at, at, joins=me))
        if normalized(TENANT, p.tenant) == normalized(COMPANY, p.company):
            out.append(Observation(TENANT, p.tenant, TEAMS, p.account, p.tenant, 0, at, at, joins=me))
    return out
